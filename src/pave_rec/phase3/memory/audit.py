"""Deterministic aggregate audit for one exact Dynamic Hybrid Memory artifact."""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationInfo, field_validator, model_validator

from pave_rec.domain import ResourceRef
from pave_rec.domain.base import FrozenModel, require_finite
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ArtifactIntegrityError, ArtifactPublicationError, DatasetValidationError
from pave_rec.phase3.config import LoadedPhase3Config, Phase3ConfigBase, load_phase3_config
from pave_rec.preprocessing.codecs import decode_canonical_json, encode_json
from pave_rec.preprocessing.paths import (
    FilesystemPathResolver,
    RootRegistry,
    require_sha256,
    validate_filesystem_key,
    validate_root_id,
)
from pave_rec.preprocessing.publisher import publication_staging_key

from .artifact import LoadedMemoryArtifact, load_memory_artifact

AUDIT_RECIPE = "dynamic-hybrid-memory-aggregate-audit-v1"


class ScalarDistribution(FrozenModel):
    count: int
    minimum: float | None
    mean: float | None
    p50: float | None
    p90: float | None
    p99: float | None
    maximum: float | None

    @field_validator("count")
    @classmethod
    def _validate_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("distribution count must be non-negative")
        return value

    @field_validator("minimum", "mean", "p50", "p90", "p99", "maximum")
    @classmethod
    def _validate_values(cls, value: float | None, info: ValidationInfo) -> float | None:
        if value is not None:
            return require_finite(value, info.field_name)
        return value

    @model_validator(mode="after")
    def _validate_presence(self) -> "ScalarDistribution":
        values = (self.minimum, self.mean, self.p50, self.p90, self.p99, self.maximum)
        if (self.count == 0) != all(value is None for value in values):
            raise ValueError("empty distribution/value presence mismatch")
        if self.count > 0 and any(value is None for value in values):
            raise ValueError("non-empty distribution requires every summary")
        return self


class MemoryAggregateAudit(FrozenModel):
    schema_version: Literal["p3-memory-aggregate-audit-v1"]
    audit_version: str
    memory_artifact_ref: ResourceRef
    audit_recipe: Literal["dynamic-hybrid-memory-aggregate-audit-v1"]
    counts: dict[str, int]
    rates: dict[str, float]
    distributions: dict[str, ScalarDistribution]

    @field_validator("audit_version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if not value.startswith("p3memoryaudit-") or len(value) != 78:
            raise ValueError("audit_version must be p3memoryaudit-<64 lowercase hex>")
        try:
            int(value.removeprefix("p3memoryaudit-"), 16)
        except ValueError as exc:
            raise ValueError("audit_version must be p3memoryaudit-<64 lowercase hex>") from exc
        return value

    @model_validator(mode="after")
    def _validate_inventory(self) -> "MemoryAggregateAudit":
        expected_counts = {
            "cosine_observations",
            "emerging_tracks",
            "fading_tracks",
            "inactive_tracks",
            "long_empty_snapshots",
            "long_tracks",
            "pending_tracks",
            "preference_matches",
            "projected_long_atoms",
            "projected_short_atoms",
            "promotions",
            "semantic_observations",
            "short_empty_snapshots",
            "snapshot_with_semantics",
            "snapshots",
            "stable_tracks",
        }
        expected_rates = {
            "pending_tracks_per_snapshot",
            "projected_long_atoms_per_snapshot",
            "promotion_per_semantic_observation",
            "snapshot_long_nonempty_rate",
            "snapshot_semantic_coverage",
            "snapshot_short_nonempty_rate",
        }
        expected_distributions = {
            "cosine_similarity",
            "drop_interest_drift",
            "global_drift",
            "long_persistence",
            "long_strength",
            "new_interest_drift",
            "pending_persistence",
            "pending_strength",
        }
        if set(self.counts) != expected_counts or any(value < 0 for value in self.counts.values()):
            raise ValueError("memory audit count inventory mismatch")
        if set(self.rates) != expected_rates:
            raise ValueError("memory audit rate inventory mismatch")
        if any(not math.isfinite(value) or value < 0.0 for value in self.rates.values()):
            raise ValueError("memory audit rates must be finite and non-negative")
        if set(self.distributions) != expected_distributions:
            raise ValueError("memory audit distribution inventory mismatch")
        require_sha256(self.memory_artifact_ref.checksum)
        validate_filesystem_key(self.memory_artifact_ref.key)
        return self


class Phase3MemoryAuditConfig(Phase3ConfigBase):
    kind: Literal["phase3-memory-audit"]
    memory_artifact_ref: ResourceRef
    output_root_id: str

    @field_validator("output_root_id")
    @classmethod
    def _validate_output(cls, value: str) -> str:
        return validate_root_id(value)

    @model_validator(mode="after")
    def _validate_roots(self) -> "Phase3MemoryAuditConfig":
        require_sha256(self.memory_artifact_ref.checksum)
        validate_filesystem_key(self.memory_artifact_ref.key)
        source = self.storage.roots.get(self.memory_artifact_ref.store)
        if source is None or source.access != "read_only":
            raise ValueError("memory_artifact_ref must use a declared read_only root")
        output = self.storage.roots.get(self.output_root_id)
        if output is None or output.access != "write_new":
            raise ValueError("output_root_id must use a declared write_new root")
        if self.output_root_id == self.memory_artifact_ref.store:
            raise ValueError("memory audit output root must differ from its input root")
        return self


@dataclass(frozen=True)
class MemoryAuditPlan:
    audit_version: str
    output_root_id: str
    audit: MemoryAggregateAudit
    audit_ref: ResourceRef
    payload: bytes


@dataclass(frozen=True)
class MemoryAuditPublicationResult:
    outcome: Literal["created", "reused"]
    audit_ref: ResourceRef


@dataclass(frozen=True)
class MemoryAuditResult:
    execution_id: str
    outcome: str
    audit_version: str
    audit_ref: ResourceRef
    snapshots: int
    semantic_observations: int
    stable_tracks: int
    emerging_tracks: int
    fading_tracks: int
    inactive_tracks: int


def _percentile(sorted_values: tuple[float, ...], quantile: float) -> float:
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _distribution(values) -> ScalarDistribution:
    ordered = tuple(sorted(float(value) for value in values))
    if not ordered:
        return ScalarDistribution(
            count=0,
            minimum=None,
            mean=None,
            p50=None,
            p90=None,
            p99=None,
            maximum=None,
        )
    if any(not math.isfinite(value) for value in ordered):
        raise ArtifactIntegrityError("memory audit input contains a non-finite scalar")
    return ScalarDistribution(
        count=len(ordered),
        minimum=ordered[0],
        mean=math.fsum(ordered) / len(ordered),
        p50=_percentile(ordered, 0.50),
        p90=_percentile(ordered, 0.90),
        p99=_percentile(ordered, 0.99),
        maximum=ordered[-1],
    )


def build_memory_audit_plan(
    *,
    output_root_id: str,
    memory_artifact_ref: ResourceRef,
    loaded: LoadedMemoryArtifact,
) -> MemoryAuditPlan:
    if loaded.manifest.artifact_version != memory_artifact_ref.version or loaded.manifest.counts[
        "snapshots"
    ] != len(loaded.states):
        raise ArtifactIntegrityError("memory audit input identity/coverage mismatch")
    tracks = tuple(track for state in loaded.states for track in state.tracks)
    long_tracks = tuple(track for track in tracks if track.kind == "long")
    pending_tracks = tuple(track for track in tracks if track.kind == "pending")
    views = tuple(record.view for record in loaded.views)
    similarities = tuple(
        match.similarity
        for view in views
        for match in view.preference_matches
        if match.similarity is not None
    )
    snapshot_count = len(loaded.states)
    semantic_observations = sum(state.observed_semantic_count for state in loaded.states)
    promotions = sum(state.promotion_count for state in loaded.states)
    projected_long_atoms = sum(len(view.long_term_atoms) for view in views)
    projected_short_atoms = sum(len(view.short_term_atoms) for view in views)
    counts = {
        "cosine_observations": len(similarities),
        "emerging_tracks": sum(track.state == "emerging" for track in tracks),
        "fading_tracks": sum(track.state == "fading" for track in tracks),
        "inactive_tracks": sum(track.state == "inactive" for track in tracks),
        "long_empty_snapshots": sum(not view.long_term_atoms for view in views),
        "long_tracks": len(long_tracks),
        "pending_tracks": len(pending_tracks),
        "preference_matches": sum(len(view.preference_matches) for view in views),
        "projected_long_atoms": projected_long_atoms,
        "projected_short_atoms": projected_short_atoms,
        "promotions": promotions,
        "semantic_observations": semantic_observations,
        "short_empty_snapshots": sum(not view.short_term_atoms for view in views),
        "snapshot_with_semantics": sum(
            state.observed_semantic_count > 0 for state in loaded.states
        ),
        "snapshots": snapshot_count,
        "stable_tracks": sum(track.state == "stable" for track in tracks),
    }
    if snapshot_count == 0 or semantic_observations == 0:
        raise ArtifactIntegrityError("memory audit requires non-empty real snapshot observations")
    rates = {
        "pending_tracks_per_snapshot": len(pending_tracks) / snapshot_count,
        "projected_long_atoms_per_snapshot": projected_long_atoms / snapshot_count,
        "promotion_per_semantic_observation": promotions / semantic_observations,
        "snapshot_long_nonempty_rate": 1.0 - counts["long_empty_snapshots"] / snapshot_count,
        "snapshot_semantic_coverage": counts["snapshot_with_semantics"] / snapshot_count,
        "snapshot_short_nonempty_rate": 1.0 - counts["short_empty_snapshots"] / snapshot_count,
    }
    distributions = {
        "cosine_similarity": _distribution(similarities),
        "drop_interest_drift": _distribution(
            view.drop_interest_drift for view in views if view.drop_interest_drift is not None
        ),
        "global_drift": _distribution(
            view.global_drift for view in views if view.global_drift is not None
        ),
        "long_persistence": _distribution(track.persistence for track in long_tracks),
        "long_strength": _distribution(track.strength for track in long_tracks),
        "new_interest_drift": _distribution(
            view.new_interest_drift for view in views if view.new_interest_drift is not None
        ),
        "pending_persistence": _distribution(track.persistence for track in pending_tracks),
        "pending_strength": _distribution(track.strength for track in pending_tracks),
    }
    identity = {
        "identity_schema_version": "p3-memory-aggregate-audit-identity-v1",
        "memory_artifact_ref": memory_artifact_ref.model_dump(mode="json", exclude_none=False),
        "audit_recipe": AUDIT_RECIPE,
    }
    audit_version = (
        "p3memoryaudit-" + hashlib.sha256(canonical_json_bytes(identity, pretty=False)).hexdigest()
    )
    audit = MemoryAggregateAudit(
        schema_version="p3-memory-aggregate-audit-v1",
        audit_version=audit_version,
        memory_artifact_ref=memory_artifact_ref,
        audit_recipe=AUDIT_RECIPE,
        counts=counts,
        rates=rates,
        distributions=distributions,
    )
    payload = encode_json(audit)
    audit_ref = ResourceRef(
        store=output_root_id,
        key=f"bundles/{audit_version}/memory_audit.json",
        version=audit_version,
        checksum=f"sha256:{hashlib.sha256(payload).hexdigest()}",
    )
    return MemoryAuditPlan(audit_version, output_root_id, audit, audit_ref, payload)


class FilesystemMemoryAuditPublisher:
    def __init__(self, registry: RootRegistry) -> None:
        self._resolver = FilesystemPathResolver(registry)

    @staticmethod
    def _verify(plan: MemoryAuditPlan, directory: Path) -> None:
        target = directory / "memory_audit.json"
        try:
            actual = target.read_bytes()
            files = tuple(
                path.relative_to(directory).as_posix()
                for path in directory.rglob("*")
                if path.is_file()
            )
        except OSError as exc:
            raise ArtifactIntegrityError("cannot verify memory audit artifact") from exc
        if actual != plan.payload or files != ("memory_audit.json",):
            raise ArtifactIntegrityError("memory audit artifact payload/inventory mismatch")

    def publish(self, plan: MemoryAuditPlan, *, execution_id: str) -> MemoryAuditPublicationResult:
        target = self._resolver.resolve_new_path(
            plan.output_root_id, f"bundles/{plan.audit_version}"
        )
        if target.exists():
            self._verify(plan, target)
            return MemoryAuditPublicationResult("reused", plan.audit_ref)
        stage = self._resolver.resolve_new_path(
            plan.output_root_id,
            publication_staging_key(plan.output_root_id, plan.audit_version, execution_id),
        )
        try:
            stage.mkdir(parents=True, exist_ok=False)
            with (stage / "memory_audit.json").open("xb") as handle:
                handle.write(plan.payload)
                handle.flush()
                os.fsync(handle.fileno())
            self._verify(plan, stage)
            target.parent.mkdir(parents=True, exist_ok=True)
            stage.rename(target)
        except ArtifactIntegrityError:
            raise
        except OSError as exc:
            if target.exists():
                self._verify(plan, target)
                return MemoryAuditPublicationResult("reused", plan.audit_ref)
            raise ArtifactPublicationError("cannot publish memory audit artifact") from exc
        self._verify(plan, target)
        return MemoryAuditPublicationResult("created", plan.audit_ref)


def load_memory_audit(
    resolver: FilesystemPathResolver,
    audit_ref: ResourceRef,
) -> MemoryAggregateAudit:
    try:
        audit = decode_canonical_json(
            resolver.read_verified_bytes(audit_ref),
            MemoryAggregateAudit,
            logical_name="memory aggregate audit",
        )
    except DatasetValidationError as exc:
        raise ArtifactIntegrityError("invalid memory aggregate audit") from exc
    if (
        audit.audit_version != audit_ref.version
        or audit_ref.key != f"bundles/{audit.audit_version}/memory_audit.json"
    ):
        raise ArtifactIntegrityError("memory audit identity mismatch")
    return audit


def load_phase3_memory_audit_config(
    config_path: str | Path,
) -> LoadedPhase3Config[Phase3MemoryAuditConfig]:
    return load_phase3_config(config_path, Phase3MemoryAuditConfig)


def audit_memory_from_config(config_path: str | Path) -> MemoryAuditResult:
    loaded_config = load_phase3_memory_audit_config(config_path)
    config = loaded_config.config
    resolver = FilesystemPathResolver(loaded_config.root_registry)
    memory = load_memory_artifact(resolver, config.memory_artifact_ref)
    plan = build_memory_audit_plan(
        output_root_id=config.output_root_id,
        memory_artifact_ref=config.memory_artifact_ref,
        loaded=memory,
    )
    execution_id = (
        "p3-memory-audit-"
        + hashlib.sha256(
            canonical_json_bytes(
                {
                    "config_path": loaded_config.config_path.relative_to(
                        loaded_config.project_root
                    ).as_posix(),
                    "audit_version": plan.audit_version,
                },
                pretty=False,
            )
        ).hexdigest()[:16]
    )
    publication = FilesystemMemoryAuditPublisher(loaded_config.root_registry).publish(
        plan,
        execution_id=execution_id,
    )
    counts = plan.audit.counts
    return MemoryAuditResult(
        execution_id=execution_id,
        outcome=publication.outcome,
        audit_version=plan.audit_version,
        audit_ref=publication.audit_ref,
        snapshots=counts["snapshots"],
        semantic_observations=counts["semantic_observations"],
        stable_tracks=counts["stable_tracks"],
        emerging_tracks=counts["emerging_tracks"],
        fading_tracks=counts["fading_tracks"],
        inactive_tracks=counts["inactive_tracks"],
    )
