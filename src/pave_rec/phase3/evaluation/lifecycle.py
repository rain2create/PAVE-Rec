"""Authoritative full-catalog evaluation lifecycle."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pave_rec.domain import ResourceRef
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.phase3.derived import load_derived_dataset
from pave_rec.preprocessing.paths import FilesystemPathResolver

from .artifact import FilesystemEvaluationArtifactPublisher, build_evaluation_artifact_plan
from .config import load_phase3_evaluation_config
from .evaluator import build_mostpop_ranker, evaluate_full_catalog


@dataclass(frozen=True)
class EvaluationResult:
    execution_id: str
    outcome: str
    evaluation_version: str
    manifest_ref: ResourceRef
    all_target_count: int
    warm_target_count: int
    cold_target_count: int
    ndcg_at_10: float


def evaluate_from_config(config_path: str | Path) -> EvaluationResult:
    loaded = load_phase3_evaluation_config(config_path)
    config = loaded.config
    resolver = FilesystemPathResolver(loaded.root_registry)
    derived_manifest, dataset = load_derived_dataset(resolver, config.derived_artifact_ref)
    if config.method == "mostpop-v1":
        ranker = build_mostpop_ranker(dataset)
    else:
        from pave_rec.phase3.ranker import load_sasrec_initial_ranker

        if config.checkpoint_ref is None:
            raise AssertionError("validated SASRec config lost its checkpoint ref")
        ranker = load_sasrec_initial_ranker(
            resolver=resolver,
            manifest_ref=config.checkpoint_ref,
            expected_derived_manifest_ref=config.derived_artifact_ref,
            derived_manifest=derived_manifest,
            vocabulary=dataset.vocabulary,
            device=config.device,
            candidate_chunk_size=config.candidate_chunk_size,
        )
    evaluation = evaluate_full_catalog(
        dataset,
        split=config.split,
        ranker=ranker,
        user_batch_size=config.user_batch_size,
    )
    plan = build_evaluation_artifact_plan(
        output_root_id=config.output_root_id,
        source_release_ref=derived_manifest.source_release_ref,
        derived_artifact_ref=config.derived_artifact_ref,
        method=config.method,
        checkpoint_ref=config.checkpoint_ref,
        evaluation=evaluation,
        device=config.device,
        candidate_chunk_size=config.candidate_chunk_size,
        user_batch_size=config.user_batch_size,
    )
    execution_id = (
        "p3-evaluate-"
        + hashlib.sha256(
            canonical_json_bytes(
                {
                    "config_path": loaded.config_path.relative_to(loaded.project_root).as_posix(),
                    "evaluation_version": plan.evaluation_version,
                },
                pretty=False,
            )
        ).hexdigest()[:16]
    )
    publication = FilesystemEvaluationArtifactPublisher(loaded.root_registry).publish(
        plan, execution_id=execution_id
    )
    aggregate = evaluation.aggregate
    return EvaluationResult(
        execution_id=execution_id,
        outcome=publication.outcome,
        evaluation_version=plan.evaluation_version,
        manifest_ref=publication.manifest_ref,
        all_target_count=aggregate.all_target_count,
        warm_target_count=aggregate.warm_target_count,
        cold_target_count=aggregate.cold_target_count,
        ndcg_at_10=aggregate.warm_metrics["ndcg_at_10"].mean,
    )
