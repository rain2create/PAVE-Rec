"""Thin dispatcher for the independent Phase 3 artifact lifecycles."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import fields, is_dataclass
from typing import Any

from pydantic import BaseModel

from pave_rec.errors import ConfigurationError, DatasetValidationError, PaveRecError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one exact Phase 3 lifecycle")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("derive", "build the versioned sequence dataset"),
        ("semantics", "build pinned BGE-M3 item semantics"),
        ("train-ranker", "train the fixed SASRec baseline"),
        ("memory", "build Dynamic Hybrid Memory snapshots"),
        ("memory-audit", "audit one exact Dynamic Hybrid Memory artifact"),
        ("evaluate", "run full-catalog ranking evaluation"),
        ("run", "run the real zero-budget Cheap Path"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--config", required=True)
    replay = commands.add_parser("replay", help="validate one saved Phase 1/3 run")
    replay.add_argument("--run-dir", required=True)
    return parser


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=False)
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_plain(entry) for entry in value]
    if isinstance(value, dict):
        return {str(key): _plain(entry) for key, entry in value.items()}
    return value


def _lifecycle(command: str) -> Callable[[str], object]:
    if command == "derive":
        from pave_rec.phase3.derived import derive_sequences_from_config

        return derive_sequences_from_config
    if command == "semantics":
        from pave_rec.phase3.semantics import build_item_semantics_from_config

        return build_item_semantics_from_config
    if command == "train-ranker":
        from pave_rec.phase3.ranker import train_initial_ranker_from_config

        return train_initial_ranker_from_config
    if command == "memory":
        from pave_rec.phase3.memory import build_memory_from_config

        return build_memory_from_config
    if command == "memory-audit":
        from pave_rec.phase3.memory import audit_memory_from_config

        return audit_memory_from_config
    if command == "evaluate":
        from pave_rec.phase3.evaluation import evaluate_from_config

        return evaluate_from_config
    if command == "run":
        from pave_rec.phase3.runtime import run_phase3_from_config

        return run_phase3_from_config
    raise AssertionError(f"unknown parsed Phase 3 command: {command}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "replay":
            from pave_rec.agent.replay import replay_run

            result = replay_run(args.run_dir)
        else:
            result = _lifecycle(args.command)(args.config)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except (ConfigurationError, DatasetValidationError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except PaveRecError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    payload = _plain(result)
    if args.command in {"run", "replay"}:
        payload = {
            "run_id": payload["run_id"],
            "succeeded": payload["succeeded"],
            "stop_reason": payload["stop_decision"]["reason"],
            "attempted_perception_actions": payload["attempted_perception_actions"],
            "trace_record_count": payload["trace_record_count"],
            "candidate_count": len(payload["final_state"]["candidates"])
            if payload["final_state"] is not None
            else 0,
        }
    for key, value in payload.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
