"""Canonical streaming JSONL trace writer bound to one exclusive run directory."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from pave_rec.domain import AgentRunResult, AgentStepTrace, ComponentDescriptor
from pave_rec.domain.serialization import canonical_json_bytes, write_canonical_json
from pave_rec.errors import ComponentExecutionError


class JsonlTraceWriter:
    descriptor = ComponentDescriptor(
        role="trace_writer", implementation="JsonlTraceWriter", version="phase1-v1"
    )

    def __init__(self, run_dir: Path) -> None:
        if not run_dir.is_dir():
            raise ComponentExecutionError("trace run directory does not exist")
        self._trace_path = run_dir / "trace.jsonl"
        self._result_path = run_dir / "result.json"
        self._handle: BinaryIO | None = None

    def _trace_handle(self) -> BinaryIO:
        if self._handle is None:
            try:
                self._handle = self._trace_path.open("xb")
            except OSError as exc:
                raise ComponentExecutionError(f"cannot create trace.jsonl: {exc}") from exc
        return self._handle

    def write_step(self, record: AgentStepTrace) -> None:
        try:
            handle = self._trace_handle()
            handle.write(canonical_json_bytes(record, pretty=False))
            handle.flush()
        except ComponentExecutionError:
            raise
        except OSError as exc:
            raise ComponentExecutionError(f"cannot write trace.jsonl: {exc}") from exc

    def write_result(self, result: AgentRunResult) -> None:
        try:
            write_canonical_json(self._result_path, result)
        except OSError as exc:
            raise ComponentExecutionError(f"cannot write result.json: {exc}") from exc
        finally:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
