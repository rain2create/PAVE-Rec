from __future__ import annotations

from dataclasses import dataclass

import pytest

from pave_rec.cli import phase3 as phase3_cli
from pave_rec.domain import ResourceRef
from pave_rec.errors import ConfigurationError, ContractError, DatasetValidationError


@dataclass(frozen=True)
class _Result:
    outcome: str
    refs: tuple[ResourceRef, ...]
    metadata: dict[str, object]


def test_phase3_cli_serializes_lifecycle_results(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _Result(
        outcome="created",
        refs=(
            ResourceRef(
                store="artifacts",
                key="bundle/manifest.json",
                version="v1",
                checksum=f"sha256:{'a' * 64}",
            ),
        ),
        metadata={"count": 1, "enabled": True},
    )
    monkeypatch.setattr(phase3_cli, "_lifecycle", lambda command: lambda path: result)
    assert phase3_cli.main(["derive", "--config", "fixture.yaml"]) == 0
    output = capsys.readouterr().out
    assert "outcome=created" in output
    assert "refs=[{" in output
    assert "metadata={'count': 1, 'enabled': True}" in output


@pytest.mark.parametrize(
    "error, expected_code, expected_label",
    [
        (ConfigurationError("bad config"), 2, "ConfigurationError"),
        (DatasetValidationError("bad dataset"), 2, "DatasetValidationError"),
        (ContractError("bad contract"), 1, "ContractError"),
        (KeyboardInterrupt(), 130, "interrupted"),
    ],
)
def test_phase3_cli_maps_failures_to_stable_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    expected_code: int,
    expected_label: str,
) -> None:
    def fail(_):
        raise error

    monkeypatch.setattr(phase3_cli, "_lifecycle", lambda command: fail)
    assert phase3_cli.main(["memory", "--config", "fixture.yaml"]) == expected_code
    assert expected_label in capsys.readouterr().err


def test_phase3_cli_summarizes_stopped_run_without_final_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = {
        "run_id": "run-1",
        "succeeded": False,
        "stop_decision": {"reason": "initialization_failed"},
        "attempted_perception_actions": 0,
        "trace_record_count": 0,
        "final_state": None,
    }
    monkeypatch.setattr(phase3_cli, "_lifecycle", lambda command: lambda path: result)
    assert phase3_cli.main(["run", "--config", "fixture.yaml"]) == 0
    output = capsys.readouterr().out
    assert "candidate_count=0" in output
    assert "succeeded=False" in output
