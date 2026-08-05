from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from pave_rec.domain import ResourceRef
from pave_rec.errors import ArtifactIntegrityError, ContractError
from pave_rec.phase3.derived import TrainVocabulary, VocabularyEntry, build_derived_dataset
from pave_rec.phase3.evaluation import (
    EvaluationArtifactManifest,
    EvaluationExecutionRecipe,
    FilesystemEvaluationArtifactPublisher,
    MetricAggregate,
    MostPopInitialRanker,
    RankingEvaluationAggregate,
    TargetRankingOutcome,
    build_evaluation_artifact_plan,
    build_mostpop_ranker,
    evaluate_full_catalog,
    load_evaluation_artifact,
)
from pave_rec.phase3.tsinghua import TsinghuaSnapshotIdentity, adapt_tsinghua_snapshot
from pave_rec.preprocessing.components import CanonicalBehaviorProcessor
from pave_rec.preprocessing.paths import FilesystemPathResolver, build_root_registry


def _dataset(repo_root: Path):
    root = repo_root / "tests/fixtures/phase3/tsinghua/v1"
    snapshot = TsinghuaSnapshotIdentity.model_validate_json((root / "snapshot.json").read_bytes())
    adapted = adapt_tsinghua_snapshot(snapshot, root)
    sequences = CanonicalBehaviorProcessor().process(adapted.behavior_events)
    version = f"p2-{'a' * 64}"
    return build_derived_dataset(
        sequences=sequences,
        source_data_version=version,
        source_release_ref=ResourceRef(
            store="processed",
            key=f"releases/{version}.json",
            version=version,
            checksum=f"sha256:{'b' * 64}",
        ),
        include_development_candidates=False,
    )


@pytest.mark.parametrize("split", ["validation", "test"])
def test_full_catalog_metrics_and_cold_coverage(repo_root: Path, split: str) -> None:
    dataset = _dataset(repo_root)
    evaluation = evaluate_full_catalog(
        dataset,
        split=split,
        ranker=build_mostpop_ranker(dataset),
    )
    aggregate = evaluation.aggregate
    assert aggregate.all_target_count == 2
    assert aggregate.warm_target_count == 1
    assert aggregate.cold_target_count == 1
    assert aggregate.all_target_retrieval_coverage.mean == 0.5
    warm = next(outcome for outcome in evaluation.outcomes if outcome.warm_target)
    cold = next(outcome for outcome in evaluation.outcomes if not outcome.warm_target)
    assert warm.target_rank is not None
    expected_ndcg = 1.0 / math.log2(warm.target_rank + 1) if warm.target_rank <= 10 else 0.0
    assert aggregate.warm_metrics["ndcg_at_10"].mean == expected_ndcg
    assert aggregate.warm_metrics["hr_at_10"].mean == float(warm.target_rank <= 10)
    assert aggregate.warm_metrics["recall_at_100"].mean == float(warm.target_rank <= 100)
    assert cold.target_rank is None
    assert cold.miss_reason == "cold_target"
    assert cold.candidate_count == 0
    assert cold.top_100_item_ids == ()


def test_repeat_target_is_retained_while_other_seen_positives_are_filtered(
    repo_root: Path,
) -> None:
    dataset = _dataset(repo_root)
    evaluation = evaluate_full_catalog(
        dataset,
        split="validation",
        ranker=build_mostpop_ranker(dataset),
    )
    warm = next(outcome for outcome in evaluation.outcomes if outcome.warm_target)
    target = next(
        split.validation_target
        for split in dataset.user_splits
        if split.validation_target.sample_id == warm.sample_id
    )
    assert target.target.item_id in {event.item_id for event in target.history}
    assert warm.target_item_id in warm.top_100_item_ids
    vocabulary_size = len(dataset.vocabulary.entries)
    filtered_seen = len({event.item_id for event in target.history}) - 1
    assert warm.candidate_count == vocabulary_size - filtered_seen


def test_mostpop_counts_train_only_events(repo_root: Path) -> None:
    dataset = _dataset(repo_root)
    ranker = build_mostpop_ranker(dataset)
    candidates = tuple(entry.item_id for entry in dataset.vocabulary.entries)
    output = ranker.score("user", (), candidates)
    expected_counts = {item_id: 0 for item_id in candidates}
    for split in dataset.user_splits:
        for event in split.train_events:
            expected_counts[event.item_id] += 1
    assert {entry.item_id: entry.score for entry in output.candidates} == {
        item_id: float(count) for item_id, count in expected_counts.items()
    }
    target = candidates[-1]
    target_rank, top_100 = ranker.rank_target("user", (), candidates, target)
    expected = next(entry for entry in output.candidates if entry.item_id == target)
    assert target_rank == expected.rank
    assert top_100 == tuple(entry.item_id for entry in output.candidates[:100])


def test_evaluation_artifact_publish_reload_and_reuse(repo_root: Path, tmp_path: Path) -> None:
    dataset = _dataset(repo_root)
    evaluation = evaluate_full_catalog(
        dataset,
        split="test",
        ranker=build_mostpop_ranker(dataset),
    )
    plan = build_evaluation_artifact_plan(
        output_root_id="evaluations",
        source_release_ref=dataset.source_release_ref,
        derived_artifact_ref=ResourceRef(
            store="derived",
            key="bundles/derived/derived_dataset_manifest.json",
            version="derived",
            checksum=f"sha256:{'c' * 64}",
        ),
        method="mostpop-v1",
        checkpoint_ref=None,
        evaluation=evaluation,
        device="cpu",
        candidate_chunk_size=16,
        user_batch_size=2,
    )
    root = tmp_path / "evaluations"
    root.mkdir()
    registry = build_root_registry({"evaluations": (str(root), "write_new")}, project_root=tmp_path)
    publisher = FilesystemEvaluationArtifactPublisher(registry)
    first = publisher.publish(plan, execution_id="first")
    second = publisher.publish(plan, execution_id="second")
    assert first.outcome == "created"
    assert second.outcome == "reused"
    loaded = load_evaluation_artifact(FilesystemPathResolver(registry), first.manifest_ref)
    assert loaded.aggregate == evaluation.aggregate
    assert loaded.outcomes == evaluation.outcomes


def _reject(model, value, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        model.model_validate(value)


def test_target_outcome_and_metric_contracts_reject_inconsistent_records(
    repo_root: Path,
) -> None:
    evaluation = evaluate_full_catalog(
        _dataset(repo_root),
        split="test",
        ranker=build_mostpop_ranker(_dataset(repo_root)),
    )
    warm = next(outcome for outcome in evaluation.outcomes if outcome.warm_target)
    cold = next(outcome for outcome in evaluation.outcomes if not outcome.warm_target)
    warm_data = warm.model_dump(mode="python")
    for field in ("sample_id", "user_id", "target_item_id", "cutoff_identity"):
        invalid = dict(warm_data)
        invalid[field] = ""
        _reject(TargetRankingOutcome, invalid, "must be a non-empty string")
    _reject(TargetRankingOutcome, {**warm_data, "candidate_count": -1}, "non-negative")
    _reject(TargetRankingOutcome, {**warm_data, "target_rank": 0}, "one-based")
    _reject(
        TargetRankingOutcome,
        {**warm_data, "top_100_item_ids": ("a", "a")},
        "must not contain duplicates",
    )
    _reject(
        TargetRankingOutcome,
        {**warm_data, "candidate_count": 1, "top_100_item_ids": ("a", "b")},
        "exceeds candidate coverage",
    )
    _reject(TargetRankingOutcome, {**warm_data, "target_rank": None}, "requires an exact rank")
    _reject(
        TargetRankingOutcome,
        {**warm_data, "miss_reason": "cold_target"},
        "requires an exact rank",
    )
    _reject(
        TargetRankingOutcome,
        {**warm_data, "target_rank": warm.candidate_count + 1},
        "rank exceeds candidate count",
    )
    cold_data = cold.model_dump(mode="python")
    _reject(
        TargetRankingOutcome,
        {**cold_data, "target_rank": 1},
        "requires an explicit cold miss",
    )
    _reject(
        TargetRankingOutcome,
        {**cold_data, "miss_reason": None},
        "requires an explicit cold miss",
    )

    _reject(
        MetricAggregate,
        {"numerator": float("nan"), "denominator": 1, "mean": 0.0},
        "must be finite",
    )
    _reject(
        MetricAggregate,
        {"numerator": 1.0, "denominator": 0, "mean": 1.0},
        "must be positive",
    )
    _reject(
        MetricAggregate,
        {"numerator": 1.0, "denominator": 2, "mean": 1.0},
        "does not equal",
    )


def test_evaluation_aggregate_and_manifest_reject_identity_drift(repo_root: Path) -> None:
    dataset = _dataset(repo_root)
    evaluation = evaluate_full_catalog(
        dataset,
        split="test",
        ranker=build_mostpop_ranker(dataset),
    )
    aggregate_data = evaluation.aggregate.model_dump(mode="python")
    _reject(
        RankingEvaluationAggregate,
        {**aggregate_data, "cold_target_count": -1},
        "must be non-negative",
    )
    _reject(
        RankingEvaluationAggregate,
        {**aggregate_data, "all_target_count": 0},
        "must not be empty",
    )
    _reject(
        RankingEvaluationAggregate,
        {**aggregate_data, "warm_target_count": 0},
        "warm evaluation subset must not be empty",
    )
    _reject(
        RankingEvaluationAggregate,
        {**aggregate_data, "cold_target_count": 2},
        "must partition",
    )
    metrics = dict(evaluation.aggregate.warm_metrics)
    metrics.pop("mrr_at_10")
    _reject(
        RankingEvaluationAggregate,
        {**aggregate_data, "warm_metrics": metrics},
        "inventory mismatch",
    )
    metrics = dict(evaluation.aggregate.warm_metrics)
    metrics["mrr_at_10"] = MetricAggregate(numerator=0.0, denominator=2, mean=0.0)
    _reject(
        RankingEvaluationAggregate,
        {**aggregate_data, "warm_metrics": metrics},
        "denominator mismatch",
    )
    wrong_coverage = MetricAggregate(numerator=0.0, denominator=2, mean=0.0)
    _reject(
        RankingEvaluationAggregate,
        {**aggregate_data, "all_target_retrieval_coverage": wrong_coverage},
        "coverage count mismatch",
    )

    plan = build_evaluation_artifact_plan(
        output_root_id="evaluations",
        source_release_ref=dataset.source_release_ref,
        derived_artifact_ref=ResourceRef(
            store="derived",
            key="bundles/derived/derived_dataset_manifest.json",
            version="derived",
            checksum=f"sha256:{'c' * 64}",
        ),
        method="mostpop-v1",
        checkpoint_ref=None,
        evaluation=evaluation,
        device="cpu",
        candidate_chunk_size=16,
        user_batch_size=2,
    )
    manifest = plan.manifest.model_dump(mode="python")
    _reject(
        EvaluationExecutionRecipe,
        {
            "evaluator_version": "full-catalog-evaluator-v2",
            "device": "",
            "candidate_chunk_size": 1,
            "user_batch_size": 1,
        },
        "non-empty string",
    )
    _reject(
        EvaluationExecutionRecipe,
        {
            "evaluator_version": "full-catalog-evaluator-v2",
            "device": "cpu",
            "candidate_chunk_size": 0,
            "user_batch_size": 1,
        },
        "must be positive",
    )
    _reject(EvaluationArtifactManifest, {**manifest, "evaluation_version": "bad"}, "p3eval")
    _reject(
        EvaluationArtifactManifest,
        {**manifest, "checkpoint_ref": dataset.source_release_ref},
        "checkpoint presence mismatch",
    )
    _reject(
        EvaluationArtifactManifest,
        {
            **manifest,
            "aggregate_ref": plan.manifest.aggregate_ref.model_copy(update={"version": "other"}),
        },
        "payload version mismatch",
    )
    _reject(
        EvaluationArtifactManifest,
        {**manifest, "counts": {"all_targets": 2}},
        "inventory mismatch",
    )
    _reject(
        EvaluationArtifactManifest,
        {**manifest, "counts": {"all_targets": 2, "warm_targets": 1, "cold_targets": -1}},
        "must be non-negative",
    )
    _reject(
        EvaluationArtifactManifest,
        {**manifest, "counts": {"all_targets": 3, "warm_targets": 1, "cold_targets": 1}},
        "do not partition",
    )


def test_mostpop_and_full_catalog_fail_closed_on_invalid_coverage(repo_root: Path) -> None:
    dataset = _dataset(repo_root)
    with pytest.raises(ValueError, match="non-negative train-only"):
        MostPopInitialRanker({})
    with pytest.raises(ValueError, match="non-negative train-only"):
        MostPopInitialRanker({"item": -1})
    ranker = build_mostpop_ranker(dataset)
    candidates = tuple(entry.item_id for entry in dataset.vocabulary.entries)
    for user_id, candidate_ids, pattern in (
        ("", candidates, "unique non-empty"),
        ("user", (), "unique non-empty"),
        ("user", (candidates[0], candidates[0]), "unique non-empty"),
        ("user", (*candidates, "cold"), "outside the train vocabulary"),
    ):
        with pytest.raises(ContractError, match=pattern):
            ranker.score(user_id, (), candidate_ids)
    with pytest.raises(ContractError, match="outside the candidate set"):
        ranker.rank_target("user", (), candidates, "cold")
    with pytest.raises(ContractError, match="batch size"):
        ranker.rank_targets((), user_batch_size=0)

    with pytest.raises(ContractError, match="user_batch_size"):
        evaluate_full_catalog(dataset, split="test", ranker=ranker, user_batch_size=0)
    with pytest.raises(ArtifactIntegrityError, match="target subset is empty"):
        evaluate_full_catalog(
            replace(dataset, user_splits=()),
            split="test",
            ranker=ranker,
        )
    cold_vocabulary = TrainVocabulary(
        schema_version="p3-train-vocabulary-v1",
        recipe="train-positive-utf8-order-pad0-v1",
        pad_index=0,
        entries=(VocabularyEntry(item_id="zzzz", model_index=1),),
    )
    with pytest.raises(ArtifactIntegrityError, match="warm evaluation subset is empty"):
        evaluate_full_catalog(
            replace(dataset, vocabulary=cold_vocabulary),
            split="test",
            ranker=MostPopInitialRanker({"zzzz": 0}),
        )


def test_full_catalog_rejects_malformed_batched_ranker_results(repo_root: Path) -> None:
    dataset = _dataset(repo_root)
    valid = evaluate_full_catalog(dataset, split="test", ranker=build_mostpop_ranker(dataset))
    warm = next(outcome for outcome in valid.outcomes if outcome.warm_target)

    class FixedRanker:
        def __init__(self, response) -> None:
            self.response = response

        def rank_targets(self, requests, *, user_batch_size):
            return self.response

    cases = (
        ((), "wrong batch result count"),
        (((0, warm.top_100_item_ids),), "invalid exact target rank"),
        (
            ((warm.target_rank, ()),),
            "Top-100 coverage",
        ),
        (
            ((warm.target_rank, ("foreign", *warm.top_100_item_ids[1:])),),
            "foreign candidate",
        ),
    )
    for response, pattern in cases:
        with pytest.raises(ArtifactIntegrityError, match=pattern):
            evaluate_full_catalog(dataset, split="test", ranker=FixedRanker(response))
