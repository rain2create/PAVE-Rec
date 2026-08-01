from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pave_rec.agent.replay import replay_run
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ContractError
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
