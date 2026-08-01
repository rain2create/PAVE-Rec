from __future__ import annotations

from types import SimpleNamespace

import pytest

from pave_rec.cli import run_mock
from pave_rec.domain import StopReason
from pave_rec.errors import ComponentExecutionError, ConfigurationError


def test_cli_main_success(synthetic_project, capsys: pytest.CaptureFixture[str]) -> None:
    code = run_mock.main(
        [
            "--config",
            str(synthetic_project / "configs/mock.yaml"),
            "--run-id",
            "20260801T000000Z-abcdef12",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "final_ranking:" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (ConfigurationError("bad config"), 2),
        (ComponentExecutionError("bad component"), 1),
        (KeyboardInterrupt(), 130),
    ],
)
def test_cli_main_exception_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: BaseException,
    expected_code: int,
) -> None:
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(run_mock, "run_from_config", fail)
    assert run_mock.main(["--config", "config.yaml"]) == expected_code
    assert capsys.readouterr().err


def test_cli_main_failed_result(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = SimpleNamespace(
        succeeded=False,
        stop_decision=SimpleNamespace(reason=StopReason.COMPONENT_FAILURE),
    )
    monkeypatch.setattr(run_mock, "run_from_config", lambda *args, **kwargs: result)
    assert run_mock.main(["--config", "config.yaml"]) == 1
    assert "component_failure" in capsys.readouterr().err
