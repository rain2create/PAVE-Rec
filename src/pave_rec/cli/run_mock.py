"""Thin command-line entry point for the deterministic Phase 1 runner."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pave_rec.errors import (
    ConfigurationError,
    FixtureValidationError,
    PaveRecError,
    RunInputError,
)
from pave_rec.runner import run_from_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the deterministic PAVE-Rec mock loop")
    parser.add_argument("--config", required=True, help="Path to a Phase 1 YAML config")
    parser.add_argument("--run-id", default=None, help="Optional explicit run ID")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_from_config(args.config, run_id=args.run_id)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except (ConfigurationError, FixtureValidationError, RunInputError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except PaveRecError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not result.succeeded:
        reason = result.stop_decision.reason.value
        print(f"run failed: {reason}", file=sys.stderr)
        return 1

    print(f"run_id: {result.run_id}")
    print(f"output_directory: {result.metadata['output_directory']}")
    print(f"stop_reason: {result.stop_decision.reason.value}")
    print("final_ranking:")
    for candidate in result.final_state.candidates:
        print(f"  {candidate.current_rank}. {candidate.item_id} score={candidate.current_score}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
