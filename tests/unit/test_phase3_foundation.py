from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Literal

import pytest
import yaml
from pydantic import ValidationError, field_validator

from pave_rec.domain import ResourceRef
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ComponentExecutionError, ConfigurationError, DatasetValidationError
from pave_rec.phase3 import (
    AgentInputBundle,
    Phase3ConfigBase,
    Phase3RuntimeConfig,
    UnavailableEvidenceUpdater,
    UnavailableInformationNeedEstimator,
    UnavailableObservationUpdater,
    UnavailableScoreUpdater,
    UnavailableSegmentPerceiver,
    UnavailableSegmentValueModel,
    build_agent_input_bundle,
    history_prefix_checksum,
    load_agent_input_bundle,
    load_phase3_config,
)
from pave_rec.preprocessing.paths import FilesystemPathResolver, build_root_registry


class RuntimeFixtureConfig(Phase3ConfigBase):
    kind: Literal["phase3-runtime"]
    max_perception_actions: int

    @field_validator("max_perception_actions")
    @classmethod
    def _validate_budget(cls, value: int) -> int:
        if value < 0:
            raise ValueError("max_perception_actions must be non-negative")
        return value


def _write_phase3_project(tmp_path: Path, *, child: str) -> Path:
    root = tmp_path / "project"
    (root / "configs/phase3").mkdir(parents=True)
    (root / "source").mkdir()
    (root / "runs").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "phase3-fixture"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    (root / "configs/phase3/base.yaml").write_text(
        """schema_version: "1"
kind: phase3-runtime
storage:
  roots:
    source:
      path: source
      access: read_only
    runs:
      path: runs
      access: write_new
max_perception_actions: 1
""",
        encoding="utf-8",
    )
    child_path = root / "configs/phase3/runtime.yaml"
    child_path.write_text(child, encoding="utf-8")
    return child_path


def _ref(store: str, key: str, marker: str) -> ResourceRef:
    return ResourceRef(
        store=store,
        key=key,
        version=f"version-{marker}",
        checksum=f"sha256:{marker * 64}",
    )


def _bundle() -> AgentInputBundle:
    return build_agent_input_bundle(
        user_id="user-1",
        ordered_history_prefix=("item-a", "item-a", "item-b"),
        candidate_ids=("item-c", "item-d"),
        cutoff_identity="cutoff-v1-user-1-17",
        derived_dataset_ref=_ref("derived", "bundles/derived.json", "a"),
        candidate_set_ref=_ref("derived", "bundles/candidates.json", "b"),
    )


def _runtime_payload() -> dict[str, object]:
    artifacts = {
        "p2_release_ref": _ref("artifacts", "p2/release.json", "1").model_dump(mode="python"),
        "derived_dataset_ref": _ref("artifacts", "derived/manifest.json", "2").model_dump(
            mode="python"
        ),
        "item_semantics_ref": _ref("artifacts", "semantics/manifest.json", "3").model_dump(
            mode="python"
        ),
        "sasrec_checkpoint_ref": _ref("artifacts", "checkpoints/manifest.json", "4").model_dump(
            mode="python"
        ),
        "memory_snapshot_ref": _ref("artifacts", "memory/manifest.json", "5").model_dump(
            mode="python"
        ),
        "agent_input_bundle_ref": _ref("artifacts", "inputs/bundle.json", "6").model_dump(
            mode="python"
        ),
    }
    return {
        "schema_version": "1",
        "kind": "phase3-runtime",
        "seed": 20260804,
        "data_version": f"p2-{'a' * 64}",
        "device": "cuda:0",
        "storage": {
            "roots": {
                "artifacts": {"path": "artifacts", "access": "read_only"},
                "runs": {"path": "runs", "access": "write_new"},
            }
        },
        "run": {"output_root_id": "runs", "run_id": None},
        "agent": {"max_perception_actions": 0},
        "stop": {"ranking_margin_threshold": None, "min_segment_value": None},
        "components": {
            "user_memory": "artifact",
            "initial_ranker": "sasrec",
            "item_feature_store": "persistent",
            "segment_store": "persistent",
            "state_builder": "default",
            "information_need": "unavailable",
            "segment_value": "unavailable",
            "perceiver": "unavailable",
            "evidence_updater": "unavailable",
            "observation_updater": "unavailable",
            "score_updater": "unavailable",
            "stop_policy": "threshold",
            "trace_writer": "jsonl",
        },
        "artifacts": artifacts,
    }


def test_phase3_config_loader_shares_strict_inheritance_and_root_rules(tmp_path: Path) -> None:
    config_path = _write_phase3_project(
        tmp_path,
        child="extends: base.yaml\nmax_perception_actions: 0\n",
    )
    loaded = load_phase3_config(config_path, RuntimeFixtureConfig)
    assert loaded.config.kind == "phase3-runtime"
    assert loaded.config.max_perception_actions == 0
    assert tuple(sorted(loaded.root_registry.roots)) == ("runs", "source")
    assert loaded.root_registry.require("runs").path.name == "runs"


@pytest.mark.parametrize(
    "child, pattern",
    [
        ("extends: base.yaml\nunknown: true\n", "Extra inputs"),
        ("extends: base.yaml\nkind: phase3-evaluation\n", "phase3-runtime"),
        ("extends: C:/outside.yaml\n", "relative path"),
    ],
)
def test_phase3_config_loader_rejects_foreign_unknown_and_anchored_extends(
    tmp_path: Path,
    child: str,
    pattern: str,
) -> None:
    config_path = _write_phase3_project(tmp_path, child=child)
    with pytest.raises(ConfigurationError, match=pattern):
        load_phase3_config(config_path, RuntimeFixtureConfig)


def test_phase3_config_loader_rejects_missing_project_invalid_yaml_and_cycles(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_phase3_config(missing, RuntimeFixtureConfig)

    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(ConfigurationError, match="not a file"):
        load_phase3_config(directory, RuntimeFixtureConfig)

    standalone = tmp_path / "standalone.yaml"
    standalone.write_text("schema_version: '1'\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="no project root"):
        load_phase3_config(standalone, RuntimeFixtureConfig)

    config = _write_phase3_project(tmp_path / "invalid", child="[not: valid")
    with pytest.raises(ConfigurationError, match="cannot read"):
        load_phase3_config(config, RuntimeFixtureConfig)

    config = _write_phase3_project(tmp_path / "list", child="- one\n- two\n")
    with pytest.raises(ConfigurationError, match="string-keyed mapping"):
        load_phase3_config(config, RuntimeFixtureConfig)

    config = _write_phase3_project(tmp_path / "cycle", child="extends: runtime.yaml\n")
    with pytest.raises(ConfigurationError, match="cycle detected"):
        load_phase3_config(config, RuntimeFixtureConfig)

    config = _write_phase3_project(tmp_path / "missing-parent", child="extends: absent.yaml\n")
    with pytest.raises(ConfigurationError, match="cannot resolve"):
        load_phase3_config(config, RuntimeFixtureConfig)


@pytest.mark.parametrize("extends", ["", 7])
def test_phase3_config_loader_rejects_empty_or_non_string_extends(
    tmp_path: Path,
    extends,
) -> None:
    rendered = yaml.safe_dump({"extends": extends})
    config = _write_phase3_project(tmp_path, child=rendered)
    with pytest.raises(ConfigurationError, match="one non-empty relative path"):
        load_phase3_config(config, RuntimeFixtureConfig)


def test_agent_input_bundle_preserves_one_complete_public_history() -> None:
    bundle = _bundle()
    assert bundle.history_prefix_sha256 == history_prefix_checksum(
        "user-1", ("item-a", "item-a", "item-b")
    )
    request = bundle.to_agent_run_request("run-1")
    assert request.user_history == ("item-a", "item-a", "item-b")
    assert request.candidate_ids == ("item-c", "item-d")
    assert bundle.bundle_checksum.startswith("sha256:")


def test_agent_input_bundle_fails_closed_on_identity_or_coverage_mismatch() -> None:
    payload = _bundle().model_dump(mode="python")
    payload["history_prefix_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(ValidationError, match="history_prefix_sha256 does not match"):
        AgentInputBundle.model_validate(payload)

    payload = _bundle().model_dump(mode="python")
    payload["bundle_checksum"] = f"sha256:{'f' * 64}"
    with pytest.raises(ValidationError, match="bundle_checksum does not match"):
        AgentInputBundle.model_validate(payload)

    payload = _bundle().model_dump(mode="python")
    payload["candidate_ids"] = ("item-c", "item-c")
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        AgentInputBundle.model_validate(payload)


def test_agent_input_bundle_requires_exact_artifact_refs() -> None:
    with pytest.raises(ValidationError, match="must be sha256"):
        build_agent_input_bundle(
            user_id="user-1",
            ordered_history_prefix=("item-a",),
            candidate_ids=("item-b",),
            cutoff_identity="cutoff-1",
            derived_dataset_ref=_ref("derived", "derived.json", "a").model_copy(
                update={"checksum": None}
            ),
            candidate_set_ref=_ref("derived", "candidates.json", "b"),
        )


def test_agent_input_bundle_loads_only_exact_canonical_bytes(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    bundle = _bundle()
    payload = canonical_json_bytes(bundle, pretty=True)
    target = root / "inputs" / "bundle.json"
    target.parent.mkdir()
    target.write_bytes(payload)
    registry = build_root_registry(
        {"inputs": (str(root), "read_only")},
        project_root=tmp_path,
    )
    resolver = FilesystemPathResolver(registry)
    ref = ResourceRef(
        store="inputs",
        key="inputs/bundle.json",
        version=bundle.bundle_checksum,
        checksum=f"sha256:{hashlib.sha256(payload).hexdigest()}",
    )
    assert load_agent_input_bundle(resolver, ref) == bundle

    noncanonical = canonical_json_bytes(bundle, pretty=False)
    target.write_bytes(noncanonical)
    changed_ref = ref.model_copy(
        update={"checksum": f"sha256:{hashlib.sha256(noncanonical).hexdigest()}"}
    )
    with pytest.raises(DatasetValidationError, match="canonical"):
        load_agent_input_bundle(resolver, changed_ref)


def test_phase3_runtime_config_fixes_real_zero_budget_selector_graph() -> None:
    config = Phase3RuntimeConfig.model_validate(_runtime_payload())
    assert config.agent.max_perception_actions == 0
    assert config.stop.ranking_margin_threshold is None
    assert config.components.initial_ranker == "sasrec"
    assert config.artifacts.agent_input_bundle_ref.store == "artifacts"


@pytest.mark.parametrize(
    "mutation, pattern",
    [
        (("agent", "max_perception_actions", 1), "require max_perception_actions=0"),
        (("stop", "ranking_margin_threshold", 0.1), "Input should be None"),
        (("components", "initial_ranker", "mock"), "sasrec"),
        (("artifacts", "agent_input_bundle_ref", None), "Input should be a valid dictionary"),
    ],
)
def test_phase3_runtime_config_rejects_positive_budget_or_foreign_runtime_values(
    mutation: tuple[str, str, object],
    pattern: str,
) -> None:
    payload = deepcopy(_runtime_payload())
    section, field, value = mutation
    nested = payload[section]
    assert isinstance(nested, dict)
    nested[field] = value
    with pytest.raises(ValidationError, match=pattern):
        Phase3RuntimeConfig.model_validate(payload)


def test_phase3_runtime_config_requires_exact_read_only_artifact_roots() -> None:
    payload = deepcopy(_runtime_payload())
    artifacts = payload["artifacts"]
    assert isinstance(artifacts, dict)
    bundle_ref = artifacts["agent_input_bundle_ref"]
    assert isinstance(bundle_ref, dict)
    bundle_ref["checksum"] = None
    with pytest.raises(ValidationError, match="must be sha256"):
        Phase3RuntimeConfig.model_validate(payload)

    payload = deepcopy(_runtime_payload())
    storage = payload["storage"]
    assert isinstance(storage, dict)
    roots = storage["roots"]
    assert isinstance(roots, dict)
    artifacts_root = roots["artifacts"]
    assert isinstance(artifacts_root, dict)
    artifacts_root["access"] = "write_new"
    with pytest.raises(ValidationError, match="declared read_only root"):
        Phase3RuntimeConfig.model_validate(payload)


def test_phase3_unavailable_guards_are_role_specific_and_fail_closed() -> None:
    calls = (
        (UnavailableInformationNeedEstimator(), lambda guard: guard.estimate(None)),
        (UnavailableSegmentValueModel(), lambda guard: guard.predict(None)),
        (UnavailableSegmentPerceiver(), lambda guard: guard.observe(None)),
        (UnavailableEvidenceUpdater(), lambda guard: guard.update(None, None)),
        (UnavailableObservationUpdater(), lambda guard: guard.update(None, None, 1)),
        (UnavailableScoreUpdater(), lambda guard: guard.update(None)),
    )
    expected_roles = (
        "information_need",
        "segment_value",
        "perceiver",
        "evidence_updater",
        "observation_updater",
        "score_updater",
    )
    assert tuple(guard.descriptor.role for guard, _ in calls) == expected_roles
    for guard, call in calls:
        assert guard.descriptor.version == "phase3-zero-budget-v1"
        with pytest.raises(ComponentExecutionError, match=guard.descriptor.role):
            call(guard)
