from __future__ import annotations

from pathlib import Path

import pytest

from pave_rec.agent.trace_writer import JsonlTraceWriter
from pave_rec.domain import AgentRunResult, AgentStepTrace
from pave_rec.errors import ComponentExecutionError


class _BrokenHandle:
    def write(self, data: bytes) -> None:
        raise OSError("broken handle")

    def flush(self) -> None:  # pragma: no cover - write always fails first
        pass

    def close(self) -> None:
        pass


def _artifacts(repo_root: Path) -> tuple[AgentStepTrace, AgentRunResult]:
    expected = repo_root / "tests/fixtures/mock/v1/expected"
    trace = AgentStepTrace.model_validate_json(
        (expected / "trace.jsonl").read_bytes().splitlines()[0]
    )
    result = AgentRunResult.model_validate_json((expected / "result.json").read_bytes())
    return trace, result


def test_trace_writer_rejects_bad_directory_and_collision(tmp_path: Path, repo_root: Path) -> None:
    with pytest.raises(ComponentExecutionError, match="does not exist"):
        JsonlTraceWriter(tmp_path / "missing")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_bytes(b"existing")
    writer = JsonlTraceWriter(run_dir)
    trace, _ = _artifacts(repo_root)
    with pytest.raises(ComponentExecutionError, match="create"):
        writer.write_step(trace)


def test_trace_writer_wraps_step_and_result_io_errors(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace, result = _artifacts(repo_root)
    run_dir = tmp_path / "step"
    run_dir.mkdir()
    writer = JsonlTraceWriter(run_dir)
    writer._handle = _BrokenHandle()
    with pytest.raises(ComponentExecutionError, match="write trace"):
        writer.write_step(trace)

    run_dir = tmp_path / "result"
    run_dir.mkdir()
    writer = JsonlTraceWriter(run_dir)
    writer._handle = _BrokenHandle()

    def fail_write(path, value):
        raise OSError("disk full")

    monkeypatch.setattr("pave_rec.agent.trace_writer.write_canonical_json", fail_write)
    with pytest.raises(ComponentExecutionError, match="result"):
        writer.write_result(result)
    assert writer._handle is None
