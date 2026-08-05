from __future__ import annotations

import csv
import hashlib
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from pave_rec.errors import ArtifactIntegrityError, DatasetValidationError
from pave_rec.phase3.tsinghua import (
    FilesystemTsinghuaSourcePublisher,
    SnapshotArtifactIdentity,
    TsinghuaAdapterAudit,
    TsinghuaSnapshotIdentity,
    TsinghuaSourceAdapterConfig,
    adapt_tsinghua_from_config,
    adapt_tsinghua_snapshot,
    build_tsinghua_source_bundle,
    classify_tsinghua_interaction,
)
from pave_rec.preprocessing.config import LoadedPreprocessingConfig, Phase2PreprocessingConfig
from pave_rec.preprocessing.paths import build_root_registry
from pave_rec.preprocessing.source import load_source_dataset

INVENTORY = ("README.md", "categories_cn_en.csv", "interaction_sampled.csv")


@pytest.fixture
def fixture_root(repo_root: Path) -> Path:
    return repo_root / "tests/fixtures/phase3/tsinghua/v1"


def _snapshot_for(root: Path) -> TsinghuaSnapshotIdentity:
    artifacts = []
    for name in INVENTORY:
        payload = (root / name).read_bytes()
        artifacts.append(
            SnapshotArtifactIdentity(
                relative_path=name,
                size_bytes=len(payload),
                checksum=f"sha256:{hashlib.sha256(payload).hexdigest()}",
            )
        )
    return TsinghuaSnapshotIdentity(
        schema_version="tsinghua-shortvideo-snapshot-v1",
        snapshot_id="synthetic-tsinghua-adapter-fixture-v1",
        upstream_commit="0" * 40,
        artifacts=tuple(artifacts),
    )


def _copy_fixture(fixture_root: Path, tmp_path: Path) -> Path:
    copied = tmp_path / "tsinghua"
    shutil.copytree(fixture_root, copied)
    return copied


def _mutate_interaction(root: Path, row_index: int, field: str, value: str) -> None:
    path = root / "interaction_sampled.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        rows = list(reader)
    rows[row_index][field] = value
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_tsinghua_adapter_aggregates_expansions_and_preserves_order(
    fixture_root: Path,
) -> None:
    snapshot = TsinghuaSnapshotIdentity.model_validate_json(
        (fixture_root / "snapshot.json").read_bytes()
    )
    adapted = adapt_tsinghua_snapshot(snapshot, fixture_root)

    assert adapted.audit.source_logical_row_count == 19
    assert adapted.audit.duplicate_expansion_row_count == 1
    assert adapted.audit.max_expansion_rows_per_exposure == 3
    assert (adapted.audit.exposure_count, adapted.audit.user_count, adapted.audit.item_count) == (
        17,
        3,
        7,
    )
    assert (
        adapted.audit.positive_count,
        adapted.audit.explicit_negative_count,
        adapted.audit.passive_nonpositive_count,
    ) == (15, 1, 1)

    user_a = tuple(
        event for event in adapted.behavior_events if event.user_id == "tsv:user:fixture-a"
    )
    assert tuple(event.interaction_index for event in user_a) == tuple(range(8))
    assert tuple(event.item_id for event in user_a[:4]) == (
        "tsv:item:1",
        "tsv:item:2",
        "tsv:item:3",
        "tsv:item:1",
    )
    assert tuple(event.occurred_at_ms for event in user_a[1:3]) == (200_000, 200_000)
    assert tuple(classify_tsinghua_interaction(event) for event in user_a[-2:]) == (
        "explicit_negative_v1",
        "passive_nonpositive_v1",
    )


def test_tsinghua_adapter_emits_only_confirmed_semantic_and_behavior_fields(
    fixture_root: Path,
) -> None:
    adapted = adapt_tsinghua_snapshot(_snapshot_for(fixture_root), fixture_root)
    item = next(entry for entry in adapted.items if entry.item_id == "tsv:item:1")
    assert item.metadata["title_cn"] == "虚构社会新闻一"
    assert set(item.metadata["tags"]) == {"法治", "社会"}
    assert item.metadata["category_paths_cn"] == ["新闻 > 社会"]
    assert item.metadata["category_paths_en"] == ["news > society"]
    assert item.metadata["author_id"] == "tsv:author:author-1"
    assert "gender" not in item.metadata and "description" not in item.metadata

    event = adapted.behavior_events[0]
    assert event.interaction_type == "short_video_exposure"
    assert event.metadata["effective_view"] is True
    assert event.metadata["effective_view_recipe"] == "watch-time-gt-3-seconds-v1"
    assert "p_date" not in event.metadata and "p_hour" not in event.metadata
    assert adapted.audit.watch_time_exceeds_duration_count == 1
    assert adapted.audit.mutable_author_fans_item_count == 1
    assert adapted.audit.calendar_mismatch_exposure_count == 0


def test_tsinghua_adapter_omits_conflicting_optional_title(
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    copied = _copy_fixture(fixture_root, tmp_path)
    _mutate_interaction(copied, 1, "title", "另一个虚构标题")
    adapted = adapt_tsinghua_snapshot(_snapshot_for(copied), copied)
    item = next(entry for entry in adapted.items if entry.item_id == "tsv:item:1")
    assert "title_cn" not in item.metadata
    assert adapted.audit.title_conflict_count == 1
    assert adapted.audit.title_available_count == 6


@pytest.mark.parametrize(
    "row_index, field, value, pattern",
    [
        (0, "cvm_like", "1", "must be True or False"),
        (1, "watch_time", "5", "feedback conflicts"),
        (3, "duration", "11", "critical author_id/duration conflicts"),
        (3, "category_id", "999", "absent from the pinned mapping"),
    ],
)
def test_tsinghua_adapter_fails_closed_on_critical_row_conflicts(
    fixture_root: Path,
    tmp_path: Path,
    row_index: int,
    field: str,
    value: str,
    pattern: str,
) -> None:
    copied = _copy_fixture(fixture_root, tmp_path)
    _mutate_interaction(copied, row_index, field, value)
    with pytest.raises(DatasetValidationError, match=pattern):
        adapt_tsinghua_snapshot(_snapshot_for(copied), copied)


def test_tsinghua_adapter_verifies_snapshot_before_parsing(
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    copied = _copy_fixture(fixture_root, tmp_path)
    snapshot = _snapshot_for(copied)
    with (copied / "README.md").open("a", encoding="utf-8") as handle:
        handle.write("tampered\n")
    with pytest.raises(DatasetValidationError, match="size mismatch"):
        adapt_tsinghua_snapshot(snapshot, copied)


def test_committed_real_snapshot_identity_is_exact(repo_root: Path) -> None:
    snapshot = TsinghuaSnapshotIdentity.model_validate_json(
        (repo_root / "configs/phase3/tsinghua_sampled_snapshot_v1.json").read_bytes()
    )
    assert snapshot.snapshot_id == "tsinghua-shortvideo-sampled-20260129-snapshot-v1"
    assert tuple(entry.size_bytes for entry in snapshot.artifacts) == (
        5382,
        31506,
        159920078,
    )


def test_tsinghua_source_bundle_is_immutable_and_p2_compatible(
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    snapshot = _snapshot_for(fixture_root)
    adapted = adapt_tsinghua_snapshot(snapshot, fixture_root)
    source = tmp_path / "source"
    processed = tmp_path / "processed"
    features = tmp_path / "features"
    for path in (source, processed, features):
        path.mkdir()
    write_registry = build_root_registry(
        {"source": (str(source), "write_new")},
        project_root=tmp_path,
    )
    plan = build_tsinghua_source_bundle(
        snapshot=snapshot,
        adapted=adapted,
        output_root_id="source",
    )
    publisher = FilesystemTsinghuaSourcePublisher(write_registry)
    assert publisher.publish(plan, execution_id="fixture-first").outcome == "created"
    assert publisher.publish(plan, execution_id="fixture-second").outcome == "reused"

    config = Phase2PreprocessingConfig.model_validate(
        {
            "schema_version": "1",
            "source": {"manifest_ref": plan.source_manifest_ref.model_dump(mode="python")},
            "storage": {
                "roots": {
                    "source": {"path": str(source), "access": "read_only"},
                    "processed": {"path": str(processed), "access": "write_new"},
                    "features": {"path": str(features), "access": "write_new"},
                }
            },
            "output": {
                "processed_root_id": "processed",
                "features_root_id": "features",
            },
            "codecs": {
                "source_manifest": "canonical-json-v1",
                "source_records": "canonical-jsonl-v1",
                "behavior_sequences": "canonical-jsonl-v1",
                "feature_records": "canonical-json-v1",
                "manifests_and_indexes": "canonical-json-v1",
                "compression": "none",
            },
            "features": {
                "item_attributes": [
                    {
                        "source_key": "category_paths_cn",
                        "output_key": "category_paths_cn",
                        "value_type": "string_list",
                        "required": True,
                    },
                    {
                        "source_key": "tags",
                        "output_key": "tags",
                        "value_type": "string_list",
                        "required": True,
                    },
                    {
                        "source_key": "title_cn",
                        "output_key": "title_cn",
                        "value_type": "string",
                        "required": False,
                    },
                ],
                "segment_attributes": [],
            },
            "components": {
                "behavior_processor": "canonical",
                "segment_definition_provider": "manifest",
                "item_feature_extractor": "structural",
                "segment_proxy_extractor": "structural",
            },
            "limits": {
                "max_items": 100,
                "max_behavior_events": 100,
                "max_total_segments": 1,
                "max_segments_per_item": 1,
            },
        }
    )
    read_registry = build_root_registry(
        {
            "source": (str(source), "read_only"),
            "processed": (str(processed), "write_new"),
            "features": (str(features), "write_new"),
        },
        project_root=tmp_path,
    )
    loaded = load_source_dataset(
        LoadedPreprocessingConfig(
            config=config,
            project_root=tmp_path,
            config_path=tmp_path / "fixture.yaml",
            root_registry=read_registry,
        )
    )
    assert loaded.items == adapted.items
    assert loaded.behavior_events == adapted.behavior_events
    assert loaded.segment_definitions == ()


def test_tsinghua_source_bundle_reuse_detects_corruption(
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    snapshot = _snapshot_for(fixture_root)
    adapted = adapt_tsinghua_snapshot(snapshot, fixture_root)
    source = tmp_path / "source"
    source.mkdir()
    registry = build_root_registry(
        {"source": (str(source), "write_new")},
        project_root=tmp_path,
    )
    plan = build_tsinghua_source_bundle(
        snapshot=snapshot,
        adapted=adapted,
        output_root_id="source",
    )
    publisher = FilesystemTsinghuaSourcePublisher(registry)
    publisher.publish(plan, execution_id="fixture-first")
    behavior_ref = plan.source_manifest.behavior_events_ref
    target = registry.require("source").path.joinpath(*behavior_ref.key.split("/"))
    target.write_bytes(b"corrupt")
    with pytest.raises(ArtifactIntegrityError, match="artifact mismatch"):
        publisher.publish(plan, execution_id="fixture-second")


def test_tsinghua_source_lifecycle_runs_from_strict_config(
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "tsv-lifecycle-fixture"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    raw = project / "raw"
    output = project / "source-output"
    shutil.copytree(fixture_root, raw)
    output.mkdir()
    config_path = project / "tsinghua-source.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "kind": "tsinghua-source-adapter",
                "storage": {
                    "roots": {
                        "raw": {"path": "raw", "access": "read_only"},
                        "source": {"path": "source-output", "access": "write_new"},
                    }
                },
                "source_root_id": "raw",
                "output_root_id": "source",
                "snapshot": _snapshot_for(raw).model_dump(mode="json"),
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    first = adapt_tsinghua_from_config(config_path, execution_id="lifecycle-first")
    second = adapt_tsinghua_from_config(config_path, execution_id="lifecycle-second")
    assert (first.outcome, second.outcome) == ("created", "reused")
    assert first.source_manifest_ref == second.source_manifest_ref
    assert (first.item_count, first.behavior_event_count) == (7, 17)


def test_tsinghua_snapshot_audit_and_config_contracts_reject_drift(
    fixture_root: Path,
) -> None:
    snapshot = _snapshot_for(fixture_root)

    def reject(model, value, match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            model.model_validate(value)

    artifact = snapshot.artifacts[0].model_dump(mode="python")
    reject(SnapshotArtifactIdentity, {**artifact, "relative_path": "../escape"}, "dot path")
    reject(SnapshotArtifactIdentity, {**artifact, "size_bytes": -1}, "non-negative")
    reject(SnapshotArtifactIdentity, {**artifact, "checksum": "bad"}, "sha256")
    snapshot_data = snapshot.model_dump(mode="python")
    reject(TsinghuaSnapshotIdentity, {**snapshot_data, "snapshot_id": ""}, "non-empty")
    reject(TsinghuaSnapshotIdentity, {**snapshot_data, "upstream_commit": "bad"}, "40 lowercase")
    reject(
        TsinghuaSnapshotIdentity,
        {**snapshot_data, "artifacts": list(reversed(snapshot.artifacts))},
        "exact canonical three-file inventory",
    )

    audit = adapt_tsinghua_snapshot(snapshot, fixture_root).audit
    audit_data = audit.model_dump(mode="python")
    reject(TsinghuaAdapterAudit, {**audit_data, "snapshot_id": ""}, "non-empty")
    reject(TsinghuaAdapterAudit, {**audit_data, "positive_count": -1}, "non-negative")
    reject(
        TsinghuaAdapterAudit,
        {**audit_data, "positive_count": audit.positive_count + 1},
        "label counts must partition",
    )
    reject(
        TsinghuaAdapterAudit,
        {**audit_data, "title_available_count": audit.title_available_count + 1},
        "title audit counts must partition",
    )
    reject(
        TsinghuaAdapterAudit,
        {
            **audit_data,
            "category_paths_en_available_count": audit.category_paths_en_available_count + 1,
        },
        "English category-path counts must partition",
    )

    config = {
        "schema_version": "1",
        "kind": "tsinghua-source-adapter",
        "storage": {
            "roots": {
                "raw": {"path": "raw", "access": "read_only"},
                "output": {"path": "output", "access": "write_new"},
            }
        },
        "source_root_id": "raw",
        "output_root_id": "output",
        "snapshot": snapshot.model_dump(mode="python"),
    }
    assert TsinghuaSourceAdapterConfig.model_validate(config).snapshot == snapshot
    invalid = yaml.safe_load(yaml.safe_dump(config, sort_keys=False))
    invalid["storage"]["roots"]["raw"]["access"] = "write_new"
    reject(TsinghuaSourceAdapterConfig, invalid, "declared read_only")
    invalid = yaml.safe_load(yaml.safe_dump(config, sort_keys=False))
    invalid["storage"]["roots"]["output"]["access"] = "read_only"
    reject(TsinghuaSourceAdapterConfig, invalid, "declared write_new")
