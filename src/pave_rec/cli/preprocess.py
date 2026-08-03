"""Thin Phase 2 preprocessing command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pave_rec.errors import ConfigurationError, DatasetValidationError, PaveRecError
from pave_rec.preprocessing.runner import preprocess_from_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic Phase 2 preprocessing")
    parser.add_argument("--config", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = preprocess_from_config(args.config)
    except (ConfigurationError, DatasetValidationError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except PaveRecError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    ref = result.release_ref
    print(f"execution_id={result.execution_id}")
    print(f"outcome={result.outcome}")
    print(f"data_version={result.data_version}")
    print(f"release_ref={ref.store}:{ref.key}@{ref.version}#{ref.checksum}")
    print(f"execution_report={result.execution_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
