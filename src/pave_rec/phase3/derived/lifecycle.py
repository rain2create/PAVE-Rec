"""Authoritative P3-02 derived dataset lifecycle API."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pave_rec.domain import ResourceRef
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ArtifactIntegrityError, DatasetValidationError
from pave_rec.preprocessing.codecs import decode_jsonl, encode_jsonl
from pave_rec.preprocessing.models import UserBehaviorSequence
from pave_rec.preprocessing.paths import FilesystemPathResolver
from pave_rec.stores.release import ReleaseLoader

from .artifact import FilesystemDerivedDatasetPublisher, build_derived_publication_plan
from .builder import build_derived_dataset
from .config import load_phase3_derived_sequences_config


@dataclass(frozen=True)
class DerivedSequencesResult:
    execution_id: str
    outcome: str
    derived_version: str
    manifest_ref: ResourceRef
    eligible_user_count: int
    training_sample_count: int
    vocabulary_item_count: int


def _execution_id(config_path: Path, release_ref: ResourceRef) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "config_path": config_path.as_posix(),
                "source_release_ref": release_ref.model_dump(mode="json", exclude_none=False),
            },
            pretty=False,
        )
    ).hexdigest()[:16]
    return f"p3-derive-{digest}"


def _load_behavior_sequences(loaded_release) -> tuple[UserBehaviorSequence, ...]:
    matches = tuple(
        entry
        for entry in loaded_release.inventory.values()
        if entry.artifact_kind == "behavior-sequences"
    )
    if len(matches) != 1:
        raise ArtifactIntegrityError("release requires exactly one behavior-sequences artifact")
    entry = matches[0]
    payload = FilesystemPathResolver(loaded_release.root_registry).read_verified_bytes(
        entry.resource_ref,
        expected_size=entry.size_bytes,
    )
    try:
        sequences = decode_jsonl(
            payload,
            UserBehaviorSequence,
            logical_name="P2 behavior sequences",
        )
    except DatasetValidationError as exc:
        raise ArtifactIntegrityError("published P2 behavior sequences are invalid") from exc
    if encode_jsonl(sequences) != payload:
        raise ArtifactIntegrityError("published P2 behavior sequences are non-canonical")
    return sequences


def derive_sequences_from_config(
    config_path: str | Path,
    *,
    execution_id: str | None = None,
) -> DerivedSequencesResult:
    loaded = load_phase3_derived_sequences_config(config_path)
    config = loaded.config
    actual_execution_id = execution_id or _execution_id(
        loaded.config_path.relative_to(loaded.project_root),
        config.source_release_ref,
    )
    release = ReleaseLoader(loaded.root_registry).load(config.source_release_ref)
    sequences = _load_behavior_sequences(release)
    dataset = build_derived_dataset(
        sequences=sequences,
        source_data_version=release.data_version,
        source_release_ref=release.release_ref,
        include_development_candidates=config.include_development_candidates,
        eval_negative_seed=config.eval_negative_seed,
    )
    plan = build_derived_publication_plan(dataset, output_root_id=config.output_root_id)
    publication = FilesystemDerivedDatasetPublisher(loaded.root_registry).publish(
        plan,
        execution_id=actual_execution_id,
    )
    return DerivedSequencesResult(
        execution_id=actual_execution_id,
        outcome=publication.outcome,
        derived_version=plan.derived_version,
        manifest_ref=publication.manifest_ref,
        eligible_user_count=len(dataset.user_splits),
        training_sample_count=len(dataset.training_samples),
        vocabulary_item_count=len(dataset.vocabulary.entries),
    )
