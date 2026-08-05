from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pave_rec.agent import replay as replay_module
from pave_rec.agent.replay import replay_run
from pave_rec.domain import AgentStepTrace
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ContractError
from pave_rec.phase3.runtime_config import PHASE3_RUNTIME_DESCRIPTOR_VALUES
from pave_rec.runner import GitMetadata, run_from_config


@pytest.fixture
def completed_run(synthetic_project: Path) -> Path:
    run_from_config(
        synthetic_project / "configs/mock.yaml",
        run_id="mock-v1-golden",
        git_metadata=GitMetadata(None, None),
    )
    return synthetic_project / "runs/mock-v1-golden"


def _copy_run(completed_run: Path, tmp_path: Path) -> Path:
    target = tmp_path / "copy/mock-v1-golden"
    shutil.copytree(completed_run, target)
    return target


def _read_trace(run_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (run_dir / "trace.jsonl").read_bytes().splitlines()]


def _write_trace(run_dir: Path, records: list[dict]) -> None:
    (run_dir / "trace.jsonl").write_bytes(
        b"".join(canonical_json_bytes(record, pretty=False) for record in records)
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_bytes())


def _write_json(path: Path, payload: dict) -> None:
    path.write_bytes(canonical_json_bytes(payload, pretty=True))


def _phase3_ref(marker: str) -> dict[str, str]:
    return {
        "store": "artifacts",
        "key": f"refs/{marker}.json",
        "version": f"version-{marker}",
        "checksum": f"sha256:{marker * 64}",
    }


def _convert_zero_budget_run_to_phase3(run_dir: Path) -> None:
    run_id = run_dir.name
    data_version = f"p2-{'a' * 64}"
    artifacts = {
        "p2_release_ref": _phase3_ref("1"),
        "derived_dataset_ref": _phase3_ref("2"),
        "item_semantics_ref": _phase3_ref("3"),
        "sasrec_checkpoint_ref": _phase3_ref("4"),
        "memory_snapshot_ref": _phase3_ref("5"),
        "agent_input_bundle_ref": _phase3_ref("6"),
    }
    resolved = {
        "schema_version": "1",
        "kind": "phase3-runtime",
        "seed": 7,
        "data_version": data_version,
        "device": "cpu",
        "storage": {
            "roots": {
                "artifacts": {"path": "artifacts", "access": "read_only"},
                "runs": {"path": "runs", "access": "write_new"},
            }
        },
        "run": {"output_root_id": "runs", "run_id": run_id},
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
    _write_json(run_dir / "resolved_config.json", resolved)
    result = _read_json(run_dir / "result.json")
    result["data_version"] = data_version
    for descriptor in result["component_descriptors"]:
        implementation, version = PHASE3_RUNTIME_DESCRIPTOR_VALUES[descriptor["role"]]
        descriptor["implementation"] = implementation
        descriptor["version"] = version
    result["metadata"] = {
        "artifact_graph": artifacts,
        "output_directory": f"runs/{run_id}",
        "runtime_kind": "phase3-runtime",
    }
    _write_json(run_dir / "result.json", result)


def test_replay_rejects_missing_and_noncanonical_artifacts(
    completed_run: Path, tmp_path: Path
) -> None:
    copied = _copy_run(completed_run, tmp_path)
    (copied / "result.json").unlink()
    with pytest.raises(ContractError, match="missing"):
        replay_run(copied)

    copied = tmp_path / "second/mock-v1-golden"
    shutil.copytree(completed_run, copied)
    result_path = copied / "result.json"
    result_path.write_bytes(result_path.read_bytes() + b"\n")
    with pytest.raises(ContractError, match="canonical"):
        replay_run(copied)


def test_replay_dispatches_phase3_runtime_and_binds_artifact_graph(
    synthetic_project: Path,
) -> None:
    config = synthetic_project / "configs/phase3-replay.yaml"
    config.write_text(
        "extends: mock.yaml\nagent:\n  max_perception_actions: 0\n",
        encoding="utf-8",
        newline="\n",
    )
    run_id = "20260804T150000Z-1234abcd"
    result = run_from_config(
        config,
        run_id=run_id,
        git_metadata=GitMetadata(None, None),
    )
    assert result.stop_decision.reason.value == "budget_exhausted"
    run_dir = synthetic_project / "runs" / run_id
    _convert_zero_budget_run_to_phase3(run_dir)

    replayed = replay_run(run_dir)
    assert replayed.run_id == run_id
    assert replayed.metadata["runtime_kind"] == "phase3-runtime"

    result_payload = _read_json(run_dir / "result.json")
    result_payload["metadata"]["artifact_graph"]["memory_snapshot_ref"] = _phase3_ref("7")
    _write_json(run_dir / "result.json", result_payload)
    with pytest.raises(ContractError, match="artifact graph"):
        replay_run(run_dir)


def test_replay_rejects_wrong_selection(completed_run: Path, tmp_path: Path) -> None:
    copied = _copy_run(completed_run, tmp_path)
    trace_path = copied / "trace.jsonl"
    lines = trace_path.read_bytes().splitlines()
    first = json.loads(lines[0])
    first["selected_segment"] = {
        "end_ms": 10000,
        "item_id": "item_a",
        "media_ref": {
            "checksum": None,
            "key": "item_a/segment_1",
            "store": "mock_media",
            "version": "mock-v1",
        },
        "metadata": {},
        "segment_id": "segment_1",
        "start_ms": 0,
    }
    first["selected_segment_value"] = first["segment_values"][0]
    first["perception_result"]["item_id"] = "item_a"
    first["perception_result"]["segment_id"] = "segment_1"
    first["perception_result"]["evidence"]["item_id"] = "item_a"
    first["perception_result"]["evidence"]["segment_id"] = "segment_1"
    lines[0] = canonical_json_bytes(first, pretty=False).rstrip(b"\n")
    trace_path.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(ContractError, match="argmax"):
        replay_run(copied)


def test_replay_rejects_run_identity_mismatch(completed_run: Path, tmp_path: Path) -> None:
    copied = tmp_path / "wrong-directory-name"
    shutil.copytree(completed_run, copied)
    with pytest.raises(ContractError, match="run IDs"):
        replay_run(copied)


def test_replay_rejects_artifact_metadata_mismatches(completed_run: Path, tmp_path: Path) -> None:
    def wrong_seed(run_dir: Path) -> None:
        path = run_dir / "result.json"
        payload = _read_json(path)
        payload["seed"] = 8
        _write_json(path, payload)

    def wrong_descriptors(run_dir: Path) -> None:
        path = run_dir / "result.json"
        payload = _read_json(path)
        payload["component_descriptors"].reverse()
        _write_json(path, payload)

    def wrong_count(run_dir: Path) -> None:
        path = run_dir / "result.json"
        payload = _read_json(path)
        payload["trace_record_count"] = 4
        _write_json(path, payload)

    def absolute_output(run_dir: Path) -> None:
        path = run_dir / "resolved_config.json"
        payload = _read_json(path)
        payload["run"]["output_root"] = "/absolute"
        _write_json(path, payload)

    for index, mutation in enumerate((wrong_seed, wrong_descriptors, wrong_count, absolute_output)):
        copied = tmp_path / str(index) / "mock-v1-golden"
        shutil.copytree(completed_run, copied)
        mutation(copied)
        with pytest.raises(ContractError):
            replay_run(copied)


def test_replay_rejects_trace_format_and_schema(completed_run: Path, tmp_path: Path) -> None:
    cases: list[bytes] = []
    original = (completed_run / "trace.jsonl").read_bytes()
    cases.append(b"")
    cases.append(original.replace(b"\n", b"\r\n", 1))
    cases.append(b"not-json\n")
    records = _read_trace(completed_run)
    cases.append((json.dumps(records[0], ensure_ascii=False) + "\n").encode())
    records[0]["action_consumed"] = "yes"
    cases.append(canonical_json_bytes(records[0], pretty=False))
    for index, content in enumerate(cases):
        copied = tmp_path / str(index) / "mock-v1-golden"
        shutil.copytree(completed_run, copied)
        (copied / "trace.jsonl").write_bytes(content)
        with pytest.raises(ContractError):
            replay_run(copied)


def test_replay_rejects_chain_and_transition_tampering(completed_run: Path, tmp_path: Path) -> None:
    def wrong_index(records: list[dict]) -> None:
        records[0]["decision_index"] = 4

    def repeated_before(records: list[dict]) -> None:
        records[1]["state_before"] = records[0]["state_after"]

    def stateless_completed(records: list[dict]) -> None:
        records[0]["state_before"] = None

    def no_action_transition(records: list[dict]) -> None:
        records[0]["action_consumed"] = False

    def wrong_step(records: list[dict]) -> None:
        state = records[0]["state_after"]
        state["step"] = 2
        state["remaining_perception_actions"] = 0
        for candidate in state["candidates"]:
            for observation in candidate["segment_observations"]:
                if observation["last_attempt_step"] == 1:
                    observation["last_attempt_step"] = 2

    def changed_budget(records: list[dict]) -> None:
        state = records[0]["state_after"]
        state["max_perception_actions"] = 3
        state["remaining_perception_actions"] = 2

    def missing_result(records: list[dict]) -> None:
        records[0]["perception_result"] = None

    def missing_selected_segment(records: list[dict]) -> None:
        records[0]["selected_segment"] = None

    def invalid_completed_shape(records: list[dict]) -> None:
        records[0]["information_need"] = None

    def terminal_too_early(records: list[dict]) -> None:
        records[0]["stop_decision"] = {
            "details": {
                "component_role": "controller",
                "error_type": "ContractError",
                "message": "tampered",
            },
            "reason": "component_failure",
            "stop": True,
        }

    mutations = (
        wrong_index,
        repeated_before,
        stateless_completed,
        no_action_transition,
        wrong_step,
        changed_budget,
        missing_result,
        missing_selected_segment,
        invalid_completed_shape,
        terminal_too_early,
    )
    for index, mutation in enumerate(mutations):
        copied = tmp_path / str(index) / "mock-v1-golden"
        shutil.copytree(completed_run, copied)
        records = _read_trace(copied)
        mutation(records)
        _write_trace(copied, records)
        with pytest.raises(ContractError):
            replay_run(copied)


def test_replay_rejects_terminal_semantic_tampering(completed_run: Path, tmp_path: Path) -> None:
    def set_terminal(run_dir: Path, reason: str, details: dict, *, failed: bool = False) -> None:
        records = _read_trace(run_dir)
        records[-1]["stop_decision"] = {"stop": True, "reason": reason, "details": details}
        if reason == "safety_limit_reached":
            records[-1]["action_consumed"] = True
        _write_trace(run_dir, records)
        result_path = run_dir / "result.json"
        result = _read_json(result_path)
        result["stop_decision"] = records[-1]["stop_decision"]
        result["succeeded"] = not failed
        if reason == "safety_limit_reached":
            result["attempted_perception_actions"] = 3
        _write_json(result_path, result)

    cases = (
        (
            "ranking_sufficiently_certain",
            {"ranking_margin_threshold": 0.1, "top1_top2_margin": 0.09},
            False,
        ),
        ("no_unobserved_segments", {"unobserved_segment_count": 0}, False),
        (
            "max_segment_value_too_low",
            {
                "item_id": "item_a",
                "segment_id": "segment_1",
                "max_segment_value": 0.1,
                "min_segment_value": 0.15,
            },
            False,
        ),
        (
            "safety_limit_reached",
            {"decision_loop_entries": 4, "max_decision_loop_entries": 3},
            True,
        ),
    )
    for index, (reason, details, failed) in enumerate(cases):
        copied = tmp_path / str(index) / "mock-v1-golden"
        shutil.copytree(completed_run, copied)
        set_terminal(copied, reason, details, failed=failed)
        with pytest.raises(ContractError):
            replay_run(copied)


def test_replay_rejects_result_chain_accounting_tampering(
    completed_run: Path, tmp_path: Path
) -> None:
    def wrong_final_state(run_dir: Path) -> None:
        result_path = run_dir / "result.json"
        result = _read_json(result_path)
        result["final_state"] = _read_trace(run_dir)[0]["state_before"]
        _write_json(result_path, result)

    def wrong_stop_details(run_dir: Path) -> None:
        result_path = run_dir / "result.json"
        result = _read_json(result_path)
        result["stop_decision"]["details"]["step"] = 999
        _write_json(result_path, result)

    def wrong_attempt_count(run_dir: Path) -> None:
        result_path = run_dir / "result.json"
        result = _read_json(result_path)
        result["attempted_perception_actions"] = 1
        _write_json(result_path, result)

    def no_terminal_record(run_dir: Path) -> None:
        records = _read_trace(run_dir)[:2]
        _write_trace(run_dir, records)
        result_path = run_dir / "result.json"
        result = _read_json(result_path)
        result["trace_record_count"] = 2
        result["final_state"] = records[-1]["state_after"]
        _write_json(result_path, result)

    for index, mutation in enumerate(
        (wrong_final_state, wrong_stop_details, wrong_attempt_count, no_terminal_record)
    ):
        copied = tmp_path / str(index) / "mock-v1-golden"
        shutil.copytree(completed_run, copied)
        mutation(copied)
        with pytest.raises(ContractError):
            replay_run(copied)


def test_replay_accepts_certainty_low_value_and_no_segment_runs(
    synthetic_project: Path,
) -> None:
    cases = (
        (
            "certainty.yaml",
            "extends: mock.yaml\nstop:\n  ranking_margin_threshold: 0.01\n",
            "20260801T000000Z-00000001",
        ),
        (
            "low.yaml",
            "extends: mock.yaml\nstop:\n  ranking_margin_threshold: null\n"
            "  min_segment_value: 1.0\n",
            "20260801T000000Z-00000002",
        ),
    )
    for filename, content, run_id in cases:
        config_path = synthetic_project / "configs" / filename
        config_path.write_text(content, encoding="utf-8", newline="\n")
        result = run_from_config(
            config_path,
            run_id=run_id,
            git_metadata=GitMetadata(None, None),
        )
        assert replay_run(synthetic_project / "runs" / run_id) == result

    fixture_path = synthetic_project / "tests/fixtures/mock/v1/scenario.json"
    empty_fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    for catalog in empty_fixture["segment_catalog"]:
        catalog["segments"] = []
        catalog["segment_proxy_refs"] = []
    empty_fixture["segment_values"] = []
    empty_fixture["perception_results"] = []
    empty_fixture["score_deltas"] = []
    empty_path = fixture_path.with_name("empty.json")
    empty_path.write_text(json.dumps(empty_fixture), encoding="utf-8", newline="\n")
    config_path = synthetic_project / "configs/empty.yaml"
    config_path.write_text(
        "extends: mock.yaml\ninput:\n  fixture_path: tests/fixtures/mock/v1/empty.json\n",
        encoding="utf-8",
        newline="\n",
    )
    run_id = "20260801T000000Z-00000003"
    result = run_from_config(
        config_path,
        run_id=run_id,
        git_metadata=GitMetadata(None, None),
    )
    assert replay_run(synthetic_project / "runs" / run_id) == result


@pytest.mark.parametrize("reason", ["component_failure", "safety_limit_reached"])
def test_replay_accepts_declared_failure_terminal_records(
    completed_run: Path, tmp_path: Path, reason: str
) -> None:
    copied = _copy_run(completed_run, tmp_path)
    records = _read_trace(copied)
    if reason == "component_failure":
        details = {
            "component_role": "controller",
            "error_type": "ContractError",
            "message": "recorded failure",
        }
    else:
        details = {"decision_loop_entries": 4, "max_decision_loop_entries": 3}
    records[-1]["stop_decision"] = {"stop": True, "reason": reason, "details": details}
    _write_trace(copied, records)
    result_path = copied / "result.json"
    result = _read_json(result_path)
    result["succeeded"] = False
    result["stop_decision"] = records[-1]["stop_decision"]
    _write_json(result_path, result)
    assert replay_run(copied).stop_decision.reason.value == reason


def test_replay_rejects_descriptor_and_terminal_detail_mismatch(
    completed_run: Path, tmp_path: Path
) -> None:
    copied = _copy_run(completed_run, tmp_path)
    result_path = copied / "result.json"
    result = _read_json(result_path)
    result["component_descriptors"][0]["implementation"] = "WrongImplementation"
    _write_json(result_path, result)
    with pytest.raises(ContractError, match="descriptor"):
        replay_run(copied)

    copied = tmp_path / "details/mock-v1-golden"
    shutil.copytree(completed_run, copied)
    records = _read_trace(copied)
    records[-1]["stop_decision"]["details"]["max_perception_actions"] = 999
    _write_trace(copied, records)
    result_path = copied / "result.json"
    result = _read_json(result_path)
    result["stop_decision"] = records[-1]["stop_decision"]
    _write_json(result_path, result)
    with pytest.raises(ContractError, match="details"):
        replay_run(copied)


def test_replay_config_and_relative_path_helpers_fail_closed() -> None:
    for payload, pattern in (
        (b"not-json", "invalid replay artifact schema"),
        (b"[]", "must contain a JSON object"),
        (b'{"kind":"future-runtime"}', "unsupported replay config kind"),
        (b"{}", "invalid replay artifact schema"),
    ):
        with pytest.raises(ContractError, match=pattern):
            replay_module._load_resolved_config(payload)
    replay_module._validate_relative_path("runs/one", "path")
    for value in ("", ".", "../escape", "/absolute"):
        with pytest.raises(ContractError, match="project-relative"):
            replay_module._validate_relative_path(value, "path")


def test_replay_transition_and_segment_value_helpers_reject_drift(
    completed_run: Path,
) -> None:
    records = tuple(
        AgentStepTrace.model_validate_json(canonical_json_bytes(payload, pretty=False))
        for payload in _read_trace(completed_run)
    )
    record = records[0]
    before = record.state_before
    after = record.state_after
    assert before is not None and after is not None and record.perception_result is not None

    with pytest.raises(ContractError, match="missing candidate"):
        replay_module._candidate(before, "missing")
    changed_coverage = record.model_copy(
        update={"state_after": after.model_copy(update={"candidates": after.candidates[:-1]})}
    )
    with pytest.raises(ContractError, match="candidate coverage"):
        replay_module._validate_transition(before, changed_coverage)
    with pytest.raises(ContractError, match="requires a PerceptionResult"):
        replay_module._validate_transition(
            before,
            record.model_copy(update={"perception_result": None}),
        )
    missing_observation = record.model_copy(
        update={
            "perception_result": record.perception_result.model_copy(
                update={"segment_id": "missing"}
            )
        }
    )
    with pytest.raises(ContractError, match="does not match PerceptionResult"):
        replay_module._validate_transition(before, missing_observation)

    result = record.perception_result
    candidate = next(entry for entry in after.candidates if entry.item_id == result.item_id)
    observations = tuple(
        observation.model_copy(update={"last_attempt_step": 99})
        if observation.segment_id == result.segment_id
        else observation
        for observation in candidate.segment_observations
    )
    changed_candidate = candidate.model_copy(update={"segment_observations": observations})
    changed_after = after.model_copy(
        update={
            "candidates": tuple(
                changed_candidate if entry.item_id == candidate.item_id else entry
                for entry in after.candidates
            )
        }
    )
    with pytest.raises(ContractError, match="last_attempt_step"):
        replay_module._validate_transition(
            before,
            record.model_copy(update={"state_after": changed_after}),
        )
    no_evidence_result = result.model_copy(update={"evidence": None})
    with pytest.raises(ContractError, match="did not publish its Evidence"):
        replay_module._validate_transition(
            before,
            record.model_copy(update={"perception_result": no_evidence_result}),
        )
    empty_evidence = candidate.evidence.model_copy(update={"evidence": ()})
    changed_candidate = candidate.model_copy(update={"evidence": empty_evidence})
    changed_after = after.model_copy(
        update={
            "candidates": tuple(
                changed_candidate if entry.item_id == candidate.item_id else entry
                for entry in after.candidates
            )
        }
    )
    with pytest.raises(ContractError, match="absent from post-state"):
        replay_module._validate_transition(
            before,
            record.model_copy(update={"state_after": changed_after}),
        )

    with pytest.raises(ContractError, match="coverage/order"):
        replay_module._validate_value_payload(
            before,
            record.model_copy(update={"segment_values": record.segment_values[:-1]}),
        )
    observed_state = before.model_copy(
        update={
            "candidates": tuple(
                candidate.model_copy(update={"unobserved_segment_ids": ()})
                for candidate in before.candidates
            )
        }
    )
    with pytest.raises(ContractError, match="cannot be empty"):
        replay_module._validate_value_payload(
            observed_state,
            record.model_copy(update={"segment_values": ()}),
        )
    with pytest.raises(ContractError, match="deterministic argmax"):
        replay_module._validate_value_payload(
            before,
            record.model_copy(update={"selected_segment_value": record.segment_values[0]}),
        )
    with pytest.raises(ContractError, match="requires selected SegmentMeta"):
        replay_module._validate_value_payload(
            before,
            record.model_copy(update={"selected_segment": None}),
        )
