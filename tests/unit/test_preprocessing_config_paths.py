from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pave_rec.domain import ResourceRef
from pave_rec.errors import ConfigurationError, ResourceResolutionError
from pave_rec.preprocessing.config import load_preprocessing_config
from pave_rec.preprocessing.paths import (
    FilesystemPathResolver,
    build_root_registry,
    require_sha256,
    validate_case_collisions,
    validate_filesystem_key,
    validate_resource_ref_collisions,
    validate_root_id,
)


def write_project(tmp_path: Path, *, child: str = "extends: base.yaml\n") -> Path:
    root = tmp_path / "project"
    (root / "configs/preprocessing").mkdir(parents=True)
    for relative in ("source", "processed", "features"):
        (root / relative).mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "synthetic"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    checksum = f"sha256:{'0' * 64}"
    (root / "configs/preprocessing/base.yaml").write_text(
        f"""schema_version: "1"
source:
  manifest_ref:
    store: source
    key: fixture/source_manifest.json
    version: fixture-v1
    checksum: {checksum}
storage:
  roots:
    source: {{path: source, access: read_only}}
    processed: {{path: processed, access: write_new}}
    features: {{path: features, access: write_new}}
output:
  processed_root_id: processed
  features_root_id: features
codecs:
  source_manifest: canonical-json-v1
  source_records: canonical-jsonl-v1
  behavior_sequences: canonical-jsonl-v1
  feature_records: canonical-json-v1
  manifests_and_indexes: canonical-json-v1
  compression: none
features:
  item_attributes:
    - source_key: category
      output_key: category
      value_type: string
      required: false
  segment_attributes: []
components:
  behavior_processor: canonical
  segment_definition_provider: manifest
  item_feature_extractor: structural
  segment_proxy_extractor: structural
limits:
  max_items: 10
  max_behavior_events: 20
  max_total_segments: 30
  max_segments_per_item: 10
""",
        encoding="utf-8",
    )
    child_path = root / "configs/preprocessing/fixture.yaml"
    child_path.write_text(child, encoding="utf-8")
    return child_path


def test_preprocessing_config_loads_single_parent(tmp_path: Path) -> None:
    loaded = load_preprocessing_config(write_project(tmp_path))
    assert loaded.config.limits.max_items == 10
    assert loaded.root_registry.require("source").access == "read_only"
    assert loaded.root_registry.require("processed").path.name == "processed"


def test_preprocessing_config_rejects_invalid_roles_and_unknown_fields(tmp_path: Path) -> None:
    child = write_project(
        tmp_path,
        child="extends: base.yaml\noutput:\n  features_root_id: source\nunknown: true\n",
    )
    with pytest.raises(ConfigurationError, match="invalid Phase 2"):
        load_preprocessing_config(child)


def test_preprocessing_config_detects_cycle(tmp_path: Path) -> None:
    child = write_project(tmp_path, child="extends: cycle.yaml\n")
    cycle = child.with_name("cycle.yaml")
    cycle.write_text("extends: fixture.yaml\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="cycle"):
        load_preprocessing_config(child)


def test_root_registry_rejects_overlap_and_missing(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    with pytest.raises(ConfigurationError, match="overlap"):
        build_root_registry(
            {"outer": (str(outer), "read_only"), "inner": (str(inner), "write_new")},
            project_root=tmp_path,
        )
    with pytest.raises(ConfigurationError, match="does not exist"):
        build_root_registry(
            {"missing": (str(tmp_path / "missing"), "read_only")}, project_root=tmp_path
        )


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/absolute",
        "C:/windows",
        "../escape",
        "a//b",
        "a\\b",
        "a/./b",
        "NUL.txt",
        "trailing. ",
        "control\x00value",
        "e\u0301.json",
    ],
)
def test_filesystem_key_rejects_unsafe_cross_platform_forms(key: str) -> None:
    with pytest.raises(ValueError):
        validate_filesystem_key(key)


def test_filesystem_key_and_root_id_accept_portable_values() -> None:
    assert validate_filesystem_key("items/é.json") == "items/é.json"
    assert validate_root_id("processed-v1") == "processed-v1"
    with pytest.raises(ValueError):
        validate_root_id("Processed")
    with pytest.raises(ValueError):
        require_sha256("SHA256:bad")


def test_case_collision_validation() -> None:
    assert validate_case_collisions(("a/file.json", "b/file.json"))
    with pytest.raises(ValueError, match="collide"):
        validate_case_collisions(("A/file.json", "a/FILE.json"))
    refs = (
        ResourceRef(store="a", key="A/file.json", version="v1", checksum=None),
        ResourceRef(store="a", key="a/FILE.json", version="v1", checksum=None),
    )
    with pytest.raises(ValueError, match="collide"):
        validate_resource_ref_collisions(refs)
    assert validate_resource_ref_collisions((refs[0], refs[1].model_copy(update={"store": "b"})))


def test_resolver_reads_only_verified_contained_resources(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()
    payload = b"fixture-bytes"
    (source / "fixture.bin").write_bytes(payload)
    registry = build_root_registry(
        {"source": (str(source), "read_only"), "output": (str(output), "write_new")},
        project_root=tmp_path,
    )
    resolver = FilesystemPathResolver(registry)
    checksum = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    ref = ResourceRef(store="source", key="fixture.bin", version="v1", checksum=checksum)
    assert resolver.read_verified_bytes(ref, expected_size=len(payload)) == payload
    assert resolver.resolve_new_path("output", "bundles/new.json").parent.name == "bundles"
    with pytest.raises(ResourceResolutionError, match="not writable"):
        resolver.resolve_new_path("source", "new.json")
    with pytest.raises(ResourceResolutionError, match="checksum"):
        resolver.read_verified_bytes(ref.model_copy(update={"checksum": f"sha256:{'f' * 64}"}))
    with pytest.raises(ResourceResolutionError, match="size"):
        resolver.read_verified_bytes(ref, expected_size=999)
    with pytest.raises(ResourceResolutionError, match="unknown storage"):
        resolver.resolve_read_path(ref.model_copy(update={"store": "unknown"}))


def test_resolver_rejects_child_symlink_escape(tmp_path: Path) -> None:
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    (outside / "secret.bin").write_bytes(b"secret")
    try:
        (source / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    registry = build_root_registry({"source": (str(source), "read_only")}, project_root=tmp_path)
    resolver = FilesystemPathResolver(registry)
    ref = ResourceRef(
        store="source",
        key="link/secret.bin",
        version="v1",
        checksum=f"sha256:{hashlib.sha256(b'secret').hexdigest()}",
    )
    with pytest.raises(ResourceResolutionError, match="contained"):
        resolver.resolve_read_path(ref)
