"""Shared high-level lifecycle used identically by Python callers and the CLI."""

from __future__ import annotations

import secrets
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from .bootstrap import build_controller
from .config import load_config, validate_run_id, with_actual_run_id
from .domain import AgentRunRequest, AgentRunResult
from .domain.serialization import write_canonical_json
from .errors import ComponentExecutionError, RunInputError
from .fixture import load_fixture


@dataclass(frozen=True)
class GitMetadata:
    commit: str | None
    dirty: bool | None


_AUTO_GIT_METADATA: Final = object()


def generate_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(4)}"


def collect_git_metadata(project_root: Path) -> GitMetadata:
    try:
        commit_process = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
        status_process = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return GitMetadata(commit=None, dirty=None)
    commit = commit_process.stdout.strip() or None
    return GitMetadata(commit=commit, dirty=bool(status_process.stdout.strip()))


def _create_run_directory(output_root: Path, requested_run_id: str | None) -> tuple[str, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    if requested_run_id is not None:
        try:
            validate_run_id(requested_run_id)
        except ValueError as exc:
            raise RunInputError(str(exc)) from exc
        run_dir = output_root / requested_run_id
        try:
            run_dir.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise RunInputError(f"run directory already exists: {requested_run_id}") from exc
        return requested_run_id, run_dir
    for _ in range(100):
        run_id = generate_run_id()
        run_dir = output_root / run_id
        try:
            run_dir.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        return run_id, run_dir
    raise RunInputError("could not allocate a unique automatic run ID")


def run_from_config(
    config_path: str | Path,
    *,
    run_id: str | None = None,
    git_metadata: GitMetadata | object = _AUTO_GIT_METADATA,
) -> AgentRunResult:
    if git_metadata is not _AUTO_GIT_METADATA and not isinstance(git_metadata, GitMetadata):
        raise TypeError("git_metadata must be GitMetadata")
    loaded = load_config(config_path)
    config = loaded.config
    fixture_path = loaded.project_root / config.input.fixture_path
    fixture = load_fixture(fixture_path, expected_version=config.data_version)

    requested_run_id = run_id if run_id is not None else config.run.run_id
    if requested_run_id is not None:
        try:
            validate_run_id(requested_run_id)
        except ValueError as exc:
            raise RunInputError(str(exc)) from exc
    try:
        provisional_run_id = requested_run_id or "mock-v1-golden"
        AgentRunRequest(
            run_id=provisional_run_id,
            user_id=fixture.input.user_id,
            user_history=fixture.input.history,
            candidate_ids=fixture.input.candidate_ids,
        )
    except ValidationError as exc:
        raise RunInputError(f"invalid fixture run input: {exc}") from exc

    output_root = loaded.project_root / config.run.output_root
    actual_run_id, run_dir = _create_run_directory(output_root, requested_run_id)
    resolved_config = with_actual_run_id(config, actual_run_id)
    try:
        write_canonical_json(run_dir / "resolved_config.json", resolved_config)
    except OSError as exc:
        raise ComponentExecutionError(f"cannot write resolved_config.json: {exc}") from exc

    metadata = (
        collect_git_metadata(loaded.project_root)
        if git_metadata is _AUTO_GIT_METADATA
        else git_metadata
    )
    controller = build_controller(
        config=resolved_config,
        fixture=fixture,
        run_dir=run_dir,
        git_commit=metadata.commit,
        git_dirty=metadata.dirty,
    )
    request = AgentRunRequest(
        run_id=actual_run_id,
        user_id=fixture.input.user_id,
        user_history=fixture.input.history,
        candidate_ids=fixture.input.candidate_ids,
    )
    return controller.run(request)
