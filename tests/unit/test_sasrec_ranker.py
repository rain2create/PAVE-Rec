# ruff: noqa: E402

from __future__ import annotations

import io
from pathlib import Path

import pytest
from pydantic import ValidationError

torch = pytest.importorskip("torch")

from pave_rec.domain import ComponentDescriptor, ResourceRef
from pave_rec.errors import ArtifactIntegrityError, ContractError, DatasetValidationError
from pave_rec.phase3.derived import (
    build_derived_dataset,
    build_derived_publication_plan,
)
from pave_rec.phase3.ranker import (
    CheckpointPayload,
    FilesystemSasrecCheckpointPublisher,
    SasrecCheckpointManifest,
    SasrecInitialRanker,
    SasrecModel,
    SasrecModelConfig,
    SasrecTrainingRecipeConfig,
    build_sasrec_checkpoint_plan,
    deterministic_uniform_negative,
    epoch_sample_order,
    load_sasrec_checkpoint_manifest,
    load_sasrec_initial_ranker,
)
from pave_rec.phase3.tsinghua import TsinghuaSnapshotIdentity, adapt_tsinghua_snapshot
from pave_rec.preprocessing.components import CanonicalBehaviorProcessor
from pave_rec.preprocessing.paths import FilesystemPathResolver, build_root_registry


def _model_config() -> SasrecModelConfig:
    return SasrecModelConfig(
        recipe="sasrec-pytorch-v1",
        max_history_length=50,
        hidden_size=64,
        block_count=2,
        attention_head_count=2,
        feed_forward_size=256,
        activation="gelu",
        normalization="pre-ln-final-ln",
        dropout=0.2,
        initializer_std=0.02,
        tied_item_embeddings=True,
        pad_index=0,
    )


def _training_config() -> SasrecTrainingRecipeConfig:
    return SasrecTrainingRecipeConfig(
        loss="sampled-binary-last-position-v1",
        negative_sampler="uniform-train-vocabulary-user-train-exclusion-v1",
        negatives_per_positive=1,
        optimizer="adam",
        learning_rate=0.001,
        beta1=0.9,
        beta2=0.98,
        epsilon=1e-8,
        weight_decay=0.0,
        scheduler="none",
        batch_size=128,
        max_epochs=200,
        gradient_clip_global_norm=5.0,
        precision="fp32",
        amp=False,
        validation_metric="warm-full-catalog-ndcg-at-10",
        selection_rule="maximum-metric-earliest-epoch-v1",
        patience=10,
        training_seed=20260804,
    )


@pytest.fixture
def derived_fixture(repo_root: Path):
    root = repo_root / "tests/fixtures/phase3/tsinghua/v1"
    snapshot = TsinghuaSnapshotIdentity.model_validate_json((root / "snapshot.json").read_bytes())
    adapted = adapt_tsinghua_snapshot(snapshot, root)
    sequences = CanonicalBehaviorProcessor().process(adapted.behavior_events)
    source_version = f"p2-{'a' * 64}"
    source_ref = ResourceRef(
        store="processed",
        key=f"releases/{source_version}.json",
        version=source_version,
        checksum=f"sha256:{'b' * 64}",
    )
    return build_derived_dataset(
        sequences=sequences,
        source_data_version=source_version,
        source_release_ref=source_ref,
        include_development_candidates=False,
    )


def _torch_bytes(value: object) -> bytes:
    buffer = io.BytesIO()
    torch.save(value, buffer)
    return buffer.getvalue()


def test_sampler_is_keyed_deterministic_and_never_uses_excluded_items() -> None:
    first = deterministic_uniform_negative(
        vocabulary_size=20,
        excluded_model_indices=frozenset({1, 2, 3, 4}),
        training_seed=20260804,
        epoch=3,
        sample_id="sample-a",
    )
    second = deterministic_uniform_negative(
        vocabulary_size=20,
        excluded_model_indices=frozenset({1, 2, 3, 4}),
        training_seed=20260804,
        epoch=3,
        sample_id="sample-a",
    )
    assert first == second
    assert first not in {1, 2, 3, 4}
    assert epoch_sample_order(
        ("a", "b", "c"), training_seed=20260804, epoch=1
    ) == epoch_sample_order(("a", "b", "c"), training_seed=20260804, epoch=1)

    for kwargs, pattern in (
        ({"vocabulary_size": 0}, "non-empty vocabulary"),
        ({"excluded_model_indices": frozenset({0})}, "outside the vocabulary"),
        ({"excluded_model_indices": frozenset(range(1, 21))}, "exhaust"),
        ({"training_seed": -1}, "invalid deterministic"),
        ({"epoch": 0}, "invalid deterministic"),
        ({"sample_id": ""}, "invalid deterministic"),
        ({"negative_index": -1}, "invalid deterministic"),
    ):
        values = {
            "vocabulary_size": 20,
            "excluded_model_indices": frozenset({1}),
            "training_seed": 1,
            "epoch": 1,
            "sample_id": "sample",
        }
        values.update(kwargs)
        with pytest.raises(DatasetValidationError, match=pattern):
            deterministic_uniform_negative(**values)
    with pytest.raises(DatasetValidationError, match="epoch positive"):
        epoch_sample_order(("a",), training_seed=-1, epoch=1)


def test_sasrec_model_uses_tied_item_scores_and_keeps_pad_zero() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        SasrecModel(vocabulary_size=0, config=_model_config())
    torch.manual_seed(7)
    model = SasrecModel(vocabulary_size=8, config=_model_config())
    model.eval()
    history = torch.tensor(((0,) * 47 + (1, 2, 3),), dtype=torch.long)
    feature = model.encode(history)
    scores = model.score_items(feature, torch.tensor((1, 4, 8), dtype=torch.long))
    assert feature.shape == (1, 64)
    assert scores.shape == (1, 3)
    assert torch.isfinite(scores).all()
    assert torch.count_nonzero(model.item_embedding.weight[0]).item() == 0
    loss = model.sampled_binary_loss(
        history,
        torch.tensor((4,), dtype=torch.long),
        torch.tensor((8,), dtype=torch.long),
    )
    assert torch.isfinite(loss)
    invalid_inputs = (
        (torch.zeros(50, dtype=torch.long), "shape"),
        (torch.zeros((1, 49), dtype=torch.long), "sequence length"),
        (torch.zeros((1, 50), dtype=torch.float32), "torch.long"),
        (torch.full((1, 50), 9, dtype=torch.long), "outside the exact vocabulary"),
        (torch.zeros((1, 50), dtype=torch.long), "at least one known"),
    )
    for invalid, pattern in invalid_inputs:
        with pytest.raises(ValueError, match=pattern):
            model.encode(invalid)
    with pytest.raises(ValueError, match="scoring tensor shapes"):
        model.score_items(torch.zeros(64), torch.tensor((1,), dtype=torch.long))


def test_ranker_drops_history_oov_but_fails_candidate_oov_and_is_chunk_invariant(
    derived_fixture,
) -> None:
    torch.manual_seed(11)
    model = SasrecModel(
        vocabulary_size=len(derived_fixture.vocabulary.entries),
        config=_model_config(),
    )
    candidates = tuple(entry.item_id for entry in derived_fixture.vocabulary.entries)
    sequence = ("cold-history", candidates[0], candidates[1])
    first = SasrecInitialRanker(
        model=model,
        vocabulary=derived_fixture.vocabulary,
        checkpoint_id=f"p3ckpt-{'c' * 64}",
        device="cpu",
        candidate_chunk_size=1,
    ).score("user-a", sequence, candidates)
    second = SasrecInitialRanker(
        model=model,
        vocabulary=derived_fixture.vocabulary,
        checkpoint_id=f"p3ckpt-{'c' * 64}",
        device="cpu",
        candidate_chunk_size=100,
    ).score("user-a", sequence, candidates)
    assert first == second
    assert first.metadata["history_oov_dropped_count"] == 1
    assert {entry.item_id for entry in first.candidates} == set(candidates)
    target = candidates[-1]
    exact_ranker = SasrecInitialRanker(
        model=model,
        vocabulary=derived_fixture.vocabulary,
        checkpoint_id=f"p3ckpt-{'c' * 64}",
        device="cpu",
        candidate_chunk_size=2,
    )
    target_rank, top_100 = exact_ranker.rank_target("user-a", sequence, candidates, target)
    assert target_rank == next(entry.rank for entry in first.candidates if entry.item_id == target)
    assert top_100 == tuple(entry.item_id for entry in first.candidates[:100])
    evaluation_candidates = tuple(
        item_id for item_id in candidates if item_id not in set(sequence) or item_id == target
    )
    expected_evaluation = exact_ranker.rank_target(
        "user-a", sequence, evaluation_candidates, target
    )
    assert exact_ranker.rank_targets(
        (("user-a", sequence, evaluation_candidates, target),),
        user_batch_size=2,
    ) == (expected_evaluation,)
    with pytest.raises(ContractError, match="OOV"):
        SasrecInitialRanker(
            model=model,
            vocabulary=derived_fixture.vocabulary,
            checkpoint_id=f"p3ckpt-{'c' * 64}",
            device="cpu",
            candidate_chunk_size=2,
        ).score("user-a", sequence, (*candidates, "cold-candidate"))

    with pytest.raises(ContractError, match="must be positive"):
        SasrecInitialRanker(
            model=model,
            vocabulary=derived_fixture.vocabulary,
            checkpoint_id="checkpoint",
            device="cpu",
            candidate_chunk_size=0,
        )
    with pytest.raises(ValueError, match="non-empty"):
        SasrecInitialRanker(
            model=model,
            vocabulary=derived_fixture.vocabulary,
            checkpoint_id="",
            device="cpu",
            candidate_chunk_size=1,
        )
    with pytest.raises(ContractError, match="cpu or cuda"):
        SasrecInitialRanker(
            model=model,
            vocabulary=derived_fixture.vocabulary,
            checkpoint_id="checkpoint",
            device="meta",
            candidate_chunk_size=1,
        )
    with pytest.raises(ContractError, match="explicit index"):
        SasrecInitialRanker(
            model=model,
            vocabulary=derived_fixture.vocabulary,
            checkpoint_id="checkpoint",
            device="cuda",
            candidate_chunk_size=1,
        )

    with pytest.raises(ValueError, match="non-empty"):
        exact_ranker.score("", sequence, candidates)
    with pytest.raises(ContractError, match="must not be empty"):
        exact_ranker.score("user", sequence, ())
    with pytest.raises(ContractError, match="duplicates"):
        exact_ranker.score("user", sequence, (candidates[0], candidates[0]))
    with pytest.raises(ContractError, match="no known"):
        exact_ranker.score("user", ("cold",), candidates)
    with pytest.raises(ContractError, match="outside"):
        exact_ranker.rank_target("user", sequence, candidates, "cold")
    with pytest.raises(ContractError, match="batch size"):
        exact_ranker.rank_targets((), user_batch_size=0)
    assert exact_ranker.rank_targets((), user_batch_size=1) == ()

    valid_candidates = tuple(
        item_id for item_id in candidates if item_id not in set(sequence) or item_id == target
    )
    request = ("user", sequence, valid_candidates, target)
    invalid_requests = (
        (("", sequence, valid_candidates, target), "non-empty"),
        (("user", sequence, (), target), "must not be empty"),
        (("user", sequence, (target, target), target), "duplicates"),
        (("user", sequence, (*valid_candidates, "cold"), target), "OOV"),
        (("user", sequence, valid_candidates, "cold"), "outside"),
        (("user", ("cold",), candidates, target), "no known"),
        (("user", sequence, candidates, target), "seen-item mask"),
    )
    for invalid_request, match in invalid_requests:
        with pytest.raises((ContractError, ValueError), match=match):
            exact_ranker.rank_targets((invalid_request,), user_batch_size=1)
    assert exact_ranker.rank_targets((request,), user_batch_size=1)


def test_checkpoint_publishes_loads_and_reconstructs_exact_ranker(
    derived_fixture,
    tmp_path: Path,
) -> None:
    torch.manual_seed(13)
    model = SasrecModel(
        vocabulary_size=len(derived_fixture.vocabulary.entries),
        config=_model_config(),
    )
    derived_plan = build_derived_publication_plan(
        derived_fixture,
        output_root_id="derived",
    )
    vocabulary_ref = next(
        ref for ref in derived_plan.manifest.payload_refs if ref.key.endswith("/vocabulary.json")
    )
    root = tmp_path / "checkpoints"
    root.mkdir()
    write_registry = build_root_registry(
        {"checkpoints": (str(root), "write_new")},
        project_root=tmp_path,
    )
    plan = build_sasrec_checkpoint_plan(
        output_root_id="checkpoints",
        checkpoint_kind="best",
        model_config=_model_config(),
        training_recipe=_training_config(),
        source_data_version=derived_fixture.source_data_version,
        source_release_ref=derived_fixture.source_release_ref,
        derived_manifest_ref=derived_plan.manifest_ref,
        derived_manifest=derived_plan.manifest,
        vocabulary_ref=vocabulary_ref,
        vocabulary=derived_fixture.vocabulary,
        selected_best_manifest_ref=None,
        epoch=1,
        global_step=1,
        best_epoch=1,
        validation_ndcg_at_10=0.5,
        best_validation_ndcg_at_10=0.5,
        model_state=_torch_bytes(model.state_dict()),
        optimizer_state=None,
        trainer_state=None,
        operational_provenance={"python_version": "fixture", "device": "cpu"},
    )
    publisher = FilesystemSasrecCheckpointPublisher(write_registry)
    assert publisher.publish(plan, execution_id="first").outcome == "created"
    assert publisher.publish(plan, execution_id="second").outcome == "reused"

    read_registry = build_root_registry(
        {"checkpoints": (str(root), "read_only")},
        project_root=tmp_path,
    )
    resolver = FilesystemPathResolver(read_registry)
    assert load_sasrec_checkpoint_manifest(resolver, plan.manifest_ref) == plan.manifest
    loaded = load_sasrec_initial_ranker(
        resolver=resolver,
        manifest_ref=plan.manifest_ref,
        expected_derived_manifest_ref=derived_plan.manifest_ref,
        derived_manifest=derived_plan.manifest,
        vocabulary=derived_fixture.vocabulary,
        device="cpu",
        candidate_chunk_size=2,
    )
    candidates = tuple(entry.item_id for entry in derived_fixture.vocabulary.entries)
    output = loaded.score("user-a", candidates[:2], candidates)
    assert len(output.candidates) == len(candidates)
    assert output.metadata["checkpoint_id"] == plan.checkpoint_id

    model_path = root / "bundles" / plan.checkpoint_id / "model_state.pt"
    model_path.write_bytes(b"corrupt")
    with pytest.raises(ArtifactIntegrityError):
        load_sasrec_initial_ranker(
            resolver=resolver,
            manifest_ref=plan.manifest_ref,
            expected_derived_manifest_ref=derived_plan.manifest_ref,
            derived_manifest=derived_plan.manifest,
            vocabulary=derived_fixture.vocabulary,
            device="cpu",
            candidate_chunk_size=2,
        )

    payload = plan.manifest.payloads[0]
    payload_data = payload.model_dump(mode="python")
    with pytest.raises(ValidationError, match="must be sha256"):
        CheckpointPayload.model_validate({**payload_data, "checksum": "bad"})
    with pytest.raises(ValidationError, match="must be positive"):
        CheckpointPayload.model_validate({**payload_data, "size_bytes": 0})
    with pytest.raises(ValidationError, match="role/filename/format mismatch"):
        CheckpointPayload.model_validate({**payload_data, "filename": "optimizer_state.pt"})

    manifest = plan.manifest.model_dump(mode="python")

    def reject(value, match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            SasrecCheckpointManifest.model_validate(value)

    reject({**manifest, "checkpoint_id": "bad"}, "p3ckpt")
    reject({**manifest, "source_data_version": "bad"}, "data version")
    reject({**manifest, "epoch": 0}, "must be positive")
    reject({**manifest, "validation_ndcg_at_10": float("nan")}, "must be finite")
    reject({**manifest, "validation_ndcg_at_10": 2.0}, "must be in")
    reject(
        {
            **manifest,
            "ranker_descriptor": ComponentDescriptor(
                role="initial_ranker",
                implementation="Other",
                version="v1",
            ),
        },
        "invalid SASRec ranker descriptor",
    )
    reject({**manifest, "payloads": ()}, "payload inventory")
    reject({**manifest, "best_epoch": 2}, "later than checkpoint epoch")
    reject({**manifest, "validation_ndcg_at_10": 0.4}, "metric mismatch")
    reject(
        {**manifest, "selected_best_manifest_ref": plan.manifest_ref},
        "must not point",
    )
    reject(
        {
            **manifest,
            "source_release_ref": plan.manifest.source_release_ref.model_copy(
                update={"version": "other"}
            ),
        },
        "source release ref/data version mismatch",
    )
    reject(
        {
            **manifest,
            "derived_manifest_ref": plan.manifest.derived_manifest_ref.model_copy(
                update={"key": "bundles/other/manifest.json"}
            ),
        },
        "derived manifest ref key/version mismatch",
    )
    reject(
        {
            **manifest,
            "vocabulary_ref": plan.manifest.vocabulary_ref.model_copy(update={"version": "other"}),
        },
        "versions must match",
    )
    reject(
        {
            **manifest,
            "vocabulary_ref": plan.manifest.vocabulary_ref.model_copy(update={"key": "wrong.json"}),
        },
        "vocabulary ref key/version mismatch",
    )
