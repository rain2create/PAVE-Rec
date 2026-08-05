"""Exact, self-verifying Phase 3 input boundary for one Agent invocation."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationInfo, field_validator, model_validator

from pave_rec.domain import AgentRunRequest, ResourceRef
from pave_rec.domain.base import FrozenModel, require_non_empty, require_unique
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ArtifactIntegrityError, ArtifactPublicationError
from pave_rec.phase3.derived.builder import DerivedDataset
from pave_rec.phase3.derived.models import DerivedDatasetManifest
from pave_rec.preprocessing.codecs import decode_canonical_json, encode_json
from pave_rec.preprocessing.paths import (
    FilesystemPathResolver,
    RootRegistry,
    require_sha256,
    validate_filesystem_key,
    validate_root_id,
)
from pave_rec.preprocessing.publisher import publication_staging_key

AGENT_INPUT_SCHEMA_VERSION = "agent-input-bundle-v1"
HISTORY_PROJECTION_RECIPE = "p3-positive-item-history-v1"


def _sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def history_prefix_checksum(user_id: str, ordered_history_prefix: tuple[str, ...]) -> str:
    """Hash the one public positive-history projection consumed by Memory and ranker."""

    record = {
        "history_projection_recipe": HISTORY_PROJECTION_RECIPE,
        "ordered_history_prefix": ordered_history_prefix,
        "user_id": user_id,
    }
    return _sha256(canonical_json_bytes(record, pretty=False))


def _validate_exact_ref(ref: ResourceRef, field_name: str) -> ResourceRef:
    validate_root_id(ref.store)
    validate_filesystem_key(ref.key)
    require_sha256(ref.checksum, f"{field_name}.checksum")
    return ref


class AgentInputBundle(FrozenModel):
    schema_version: Literal["agent-input-bundle-v1"]
    user_id: str
    history_projection_recipe: Literal["p3-positive-item-history-v1"]
    ordered_history_prefix: tuple[str, ...]
    history_prefix_sha256: str
    candidate_ids: tuple[str, ...]
    cutoff_identity: str
    derived_dataset_ref: ResourceRef
    candidate_set_ref: ResourceRef
    bundle_checksum: str

    @field_validator("user_id", "cutoff_identity")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("ordered_history_prefix", "candidate_ids")
    @classmethod
    def _validate_item_ids(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        for item_id in value:
            require_non_empty(item_id, info.field_name)
        return value

    @field_validator("history_prefix_sha256", "bundle_checksum")
    @classmethod
    def _validate_checksums(cls, value: str, info: ValidationInfo) -> str:
        return require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def _validate_identity_and_coverage(self) -> "AgentInputBundle":
        if not self.candidate_ids:
            raise ValueError("candidate_ids must not be empty")
        require_unique(self.candidate_ids, "candidate_ids")
        _validate_exact_ref(self.derived_dataset_ref, "derived_dataset_ref")
        _validate_exact_ref(self.candidate_set_ref, "candidate_set_ref")
        expected_history = history_prefix_checksum(self.user_id, self.ordered_history_prefix)
        if self.history_prefix_sha256 != expected_history:
            raise ValueError("history_prefix_sha256 does not match the canonical history record")
        expected_bundle = agent_input_bundle_checksum(self)
        if self.bundle_checksum != expected_bundle:
            raise ValueError("bundle_checksum does not match the canonical bundle record")
        return self

    def to_agent_run_request(self, run_id: str) -> AgentRunRequest:
        """Project the internal provenance bundle onto the unchanged public request."""

        return AgentRunRequest(
            run_id=run_id,
            user_id=self.user_id,
            user_history=self.ordered_history_prefix,
            candidate_ids=self.candidate_ids,
        )


def agent_input_bundle_checksum(bundle: AgentInputBundle) -> str:
    payload = bundle.model_dump(mode="json", exclude={"bundle_checksum"})
    return _sha256(canonical_json_bytes(payload, pretty=False))


def build_agent_input_bundle(
    *,
    user_id: str,
    ordered_history_prefix: tuple[str, ...],
    candidate_ids: tuple[str, ...],
    cutoff_identity: str,
    derived_dataset_ref: ResourceRef,
    candidate_set_ref: ResourceRef,
) -> AgentInputBundle:
    payload = {
        "schema_version": AGENT_INPUT_SCHEMA_VERSION,
        "user_id": user_id,
        "history_projection_recipe": HISTORY_PROJECTION_RECIPE,
        "ordered_history_prefix": ordered_history_prefix,
        "history_prefix_sha256": history_prefix_checksum(user_id, ordered_history_prefix),
        "candidate_ids": candidate_ids,
        "cutoff_identity": cutoff_identity,
        "derived_dataset_ref": derived_dataset_ref.model_dump(mode="json", exclude_none=False),
        "candidate_set_ref": candidate_set_ref.model_dump(mode="json", exclude_none=False),
    }
    checksum = _sha256(canonical_json_bytes(payload, pretty=False))
    return AgentInputBundle.model_validate({**payload, "bundle_checksum": checksum})


def load_agent_input_bundle(
    resolver: FilesystemPathResolver,
    ref: ResourceRef,
) -> AgentInputBundle:
    """Resolve an exact canonical bundle ref and validate its internal identities."""

    _validate_exact_ref(ref, "agent_input_bundle_ref")
    payload = resolver.read_verified_bytes(ref)
    bundle = decode_canonical_json(
        payload,
        AgentInputBundle,
        logical_name="AgentInputBundle",
    )
    return bundle


@dataclass(frozen=True)
class AgentInputPublicationPlan:
    input_version: str
    output_root_id: str
    bundle: AgentInputBundle
    bundle_ref: ResourceRef
    payload: bytes


@dataclass(frozen=True)
class AgentInputPublicationResult:
    outcome: Literal["created", "reused"]
    bundle_ref: ResourceRef


def build_development_agent_input(
    *,
    dataset: DerivedDataset,
    manifest: DerivedDatasetManifest,
    derived_manifest_ref: ResourceRef,
    output_root_id: str,
    target_sample_id: str,
) -> AgentInputPublicationPlan:
    candidate_set = next(
        (
            entry
            for entry in dataset.development_candidates
            if entry.target_sample_id == target_sample_id
        ),
        None,
    )
    targets = {
        target.sample_id: target
        for split in dataset.user_splits
        for target in (split.validation_target, split.test_target)
    }
    target = targets.get(target_sample_id)
    if candidate_set is None or target is None:
        raise ArtifactIntegrityError("unknown development target sample for Agent input")
    if target.target.item_id != candidate_set.target_item_id:
        raise ArtifactIntegrityError("development target/candidate identity mismatch")
    candidate_ref = next(
        (ref for ref in manifest.payload_refs if ref.key.endswith("/development_candidates.jsonl")),
        None,
    )
    if candidate_ref is None:
        raise ArtifactIntegrityError("derived artifact has no development candidate payload")
    bundle = build_agent_input_bundle(
        user_id=target.user_id,
        ordered_history_prefix=tuple(event.item_id for event in target.history),
        candidate_ids=(target.target.item_id, *candidate_set.negative_item_ids),
        cutoff_identity=target.cutoff_identity,
        derived_dataset_ref=derived_manifest_ref,
        candidate_set_ref=candidate_ref,
    )
    input_version = "p3input-" + bundle.bundle_checksum.removeprefix("sha256:")
    payload = encode_json(bundle)
    bundle_ref = ResourceRef(
        store=output_root_id,
        key=f"bundles/{input_version}/agent_input_bundle.json",
        version=input_version,
        checksum=_sha256(payload),
    )
    return AgentInputPublicationPlan(
        input_version=input_version,
        output_root_id=output_root_id,
        bundle=bundle,
        bundle_ref=bundle_ref,
        payload=payload,
    )


class FilesystemAgentInputPublisher:
    def __init__(self, registry: RootRegistry) -> None:
        self._resolver = FilesystemPathResolver(registry)

    def publish(
        self, plan: AgentInputPublicationPlan, *, execution_id: str
    ) -> AgentInputPublicationResult:
        target = self._resolver.resolve_new_path(
            plan.output_root_id, f"bundles/{plan.input_version}"
        )
        destination = target / "agent_input_bundle.json"
        if target.exists():
            try:
                actual = destination.read_bytes()
                actual_files = {
                    path.relative_to(target).as_posix()
                    for path in target.rglob("*")
                    if path.is_file()
                }
            except OSError as exc:
                raise ArtifactIntegrityError("cannot verify existing Agent input") from exc
            if actual != plan.payload or actual_files != {"agent_input_bundle.json"}:
                raise ArtifactIntegrityError("existing Agent input artifact conflicts")
            return AgentInputPublicationResult("reused", plan.bundle_ref)
        stage = self._resolver.resolve_new_path(
            plan.output_root_id,
            publication_staging_key(plan.output_root_id, plan.input_version, execution_id),
        )
        try:
            stage.mkdir(parents=True, exist_ok=False)
            with (stage / "agent_input_bundle.json").open("xb") as handle:
                handle.write(plan.payload)
                handle.flush()
                os.fsync(handle.fileno())
            target.parent.mkdir(parents=True, exist_ok=True)
            stage.rename(target)
        except OSError as exc:
            if target.exists() and destination.read_bytes() == plan.payload:
                return AgentInputPublicationResult("reused", plan.bundle_ref)
            raise ArtifactPublicationError("cannot publish Agent input bundle") from exc
        return AgentInputPublicationResult("created", plan.bundle_ref)
