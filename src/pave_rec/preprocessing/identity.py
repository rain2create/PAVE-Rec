"""Deterministic Phase 2 recipe identity and opaque filesystem keys."""

from __future__ import annotations

import hashlib
import re

from pave_rec.domain.serialization import canonical_json_bytes

from .config import Phase2PreprocessingConfig
from .models import DataIdentity, SourceDatasetManifest
from .source import LoadedSourceDataset

DATA_VERSION_PATTERN = re.compile(r"^p2-[0-9a-f]{64}$")

OUTPUT_VERSIONS = {
    "artifact_entry": "artifact-entry-v1",
    "behavior_sequence": "user-behavior-sequence-v1",
    "item_feature": "item-feature-v1",
    "item_feature_index": "item-feature-store-index-v1",
    "release_manifest": "release-manifest-v1",
    "root_bundle_manifest": "root-bundle-manifest-v1",
    "segment_proxy": "segment-proxy-v1",
    "segment_store_index": "segment-store-index-v1",
}


def semantic_config_payload(config: Phase2PreprocessingConfig) -> dict[str, object]:
    return {
        "codecs": config.codecs.model_dump(mode="json", exclude_none=False),
        "components": config.components.model_dump(mode="json", exclude_none=False),
        "features": config.features.model_dump(mode="json", exclude_none=False),
        "logical_roots": {
            "features": config.output.features_root_id,
            "processed": config.output.processed_root_id,
            "source_manifest": config.source.manifest_ref.store,
        },
    }


def build_data_identity(
    *,
    source: LoadedSourceDataset,
    config: Phase2PreprocessingConfig,
    component_descriptors: tuple,
) -> DataIdentity:
    return DataIdentity(
        identity_schema_version="data-identity-v1",
        source_manifest=source.manifest,
        source_artifacts=source.source_artifacts,
        semantic_config=semantic_config_payload(config),
        component_descriptors=component_descriptors,
        output_versions=OUTPUT_VERSIONS,
    )


def identity_digest(identity: DataIdentity) -> str:
    return hashlib.sha256(canonical_json_bytes(identity, pretty=False)).hexdigest()


def data_version(identity: DataIdentity) -> str:
    return f"p2-{identity_digest(identity)}"


def validate_data_version(value: str) -> str:
    if DATA_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("data version must be p2-<64 lowercase hex>")
    return value


def item_identity_hash(item_id: str) -> str:
    return hashlib.sha256(canonical_json_bytes({"item_id": item_id}, pretty=False)).hexdigest()


def segment_identity_hash(item_id: str, segment_id: str) -> str:
    return hashlib.sha256(
        canonical_json_bytes({"item_id": item_id, "segment_id": segment_id}, pretty=False)
    ).hexdigest()


def item_feature_key(version: str, item_id: str) -> str:
    digest = item_identity_hash(item_id)
    return f"bundles/{version}/item-features/{digest[:2]}/{digest}.json"


def segment_proxy_key(version: str, item_id: str, segment_id: str) -> str:
    digest = segment_identity_hash(item_id, segment_id)
    return f"bundles/{version}/segment-proxies/{digest[:2]}/{digest}.json"


def canonical_manifest_semantics(manifest: SourceDatasetManifest) -> bytes:
    """Expose the exact formatting-independent source-manifest identity input."""

    return canonical_json_bytes(manifest, pretty=False)
