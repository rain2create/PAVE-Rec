from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from pave_rec.agent.replay import replay_run
from pave_rec.errors import ComponentExecutionError, FixtureValidationError, RunInputError
from pave_rec.runner import GitMetadata, collect_git_metadata, run_from_config


def test_canonical_golden_run_and_replay(synthetic_project: Path, repo_root: Path) -> None:
    result = run_from_config(
        synthetic_project / "configs/mock.yaml",
        run_id="mock-v1-golden",
        git_metadata=GitMetadata(None, None),
    )
    run_dir = synthetic_project / "runs/mock-v1-golden"
    expected_dir = repo_root / "tests/fixtures/mock/v1/expected"
    for name in ("resolved_config.json", "trace.jsonl", "result.json"):
        assert (run_dir / name).read_bytes() == (expected_dir / name).read_bytes()
    assert replay_run(run_dir) == result


def test_explicit_collision_does_not_overwrite(synthetic_project: Path) -> None:
    config = synthetic_project / "configs/mock.yaml"
    run_from_config(config, run_id="mock-v1-golden", git_metadata=GitMetadata(None, None))
    result_path = synthetic_project / "runs/mock-v1-golden/result.json"
    original = result_path.read_bytes()
    with pytest.raises(RunInputError, match="already exists"):
        run_from_config(config, run_id="mock-v1-golden", git_metadata=GitMetadata(None, None))
    assert result_path.read_bytes() == original


def test_auto_run_id_and_git_fallback(synthetic_project: Path) -> None:
    result = run_from_config(
        synthetic_project / "configs/mock.yaml", git_metadata=GitMetadata(None, None)
    )
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", result.run_id)
    assert (synthetic_project / "runs" / result.run_id / "result.json").is_file()
    assert collect_git_metadata(synthetic_project) == GitMetadata(None, None)


def test_validation_precedes_artifact_creation(synthetic_project: Path) -> None:
    fixture_path = synthetic_project / "tests/fixtures/mock/v1/scenario.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture["fixture_version"] = "wrong"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8", newline="\n")
    with pytest.raises(FixtureValidationError):
        run_from_config(
            synthetic_project / "configs/mock.yaml",
            run_id="mock-v1-golden",
            git_metadata=GitMetadata(None, None),
        )
    assert not (synthetic_project / "runs").exists()


def test_bootstrap_failure_leaves_only_resolved_config(
    synthetic_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_bootstrap(**kwargs):
        raise ComponentExecutionError("configured bootstrap failure")

    monkeypatch.setattr("pave_rec.runner.build_controller", fail_bootstrap)
    with pytest.raises(ComponentExecutionError):
        run_from_config(
            synthetic_project / "configs/mock.yaml",
            run_id="mock-v1-golden",
            git_metadata=GitMetadata(None, None),
        )
    run_dir = synthetic_project / "runs/mock-v1-golden"
    assert tuple(path.name for path in run_dir.iterdir()) == ("resolved_config.json",)


def test_cli_success_and_collision_exit_codes(synthetic_project: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "pave_rec.cli.run_mock",
        "--config",
        "configs/mock.yaml",
        "--run-id",
        "mock-v1-golden",
    ]
    success = subprocess.run(
        command,
        cwd=synthetic_project,
        check=False,
        capture_output=True,
        text=True,
    )
    assert success.returncode == 0
    assert "stop_reason: budget_exhausted" in success.stdout
    assert "item_b score=0.87" in success.stdout
    assert success.stderr == ""

    collision = subprocess.run(
        command,
        cwd=synthetic_project,
        check=False,
        capture_output=True,
        text=True,
    )
    assert collision.returncode == 2
    assert "already exists" in collision.stderr
    assert collision.stdout == ""
