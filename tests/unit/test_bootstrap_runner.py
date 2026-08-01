from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from pave_rec.bootstrap import _collect_descriptors, build_controller
from pave_rec.config import load_config, with_actual_run_id
from pave_rec.domain import ComponentDescriptor
from pave_rec.errors import (
    ComponentExecutionError,
    ContractError,
    FixtureValidationError,
    RunInputError,
)
from pave_rec.fixture import load_fixture
from pave_rec.runner import (
    GitMetadata,
    _create_run_directory,
    collect_git_metadata,
    run_from_config,
)


def test_bootstrap_preconditions_and_descriptor_validation(
    tmp_path: Path, synthetic_project: Path, mock_fixture
) -> None:
    config = load_config(synthetic_project / "configs/mock.yaml").config
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(ContractError, match="actual run ID"):
        build_controller(config=config, fixture=mock_fixture, run_dir=run_dir)

    resolved = with_actual_run_id(config, "mock-v1-golden")
    wrong_fixture = mock_fixture.model_copy(update={"fixture_version": "wrong"})
    with pytest.raises(ContractError, match="versions"):
        build_controller(config=resolved, fixture=wrong_fixture, run_dir=run_dir)

    controller = build_controller(config=resolved, fixture=mock_fixture, run_dir=run_dir)
    components = controller._components
    bad_role = replace(
        components,
        user_memory=SimpleNamespace(
            descriptor=ComponentDescriptor(
                role="wrong", implementation="MockUserMemory", version="mock-v1"
            )
        ),
    )
    with pytest.raises(ContractError, match="role mismatch"):
        _collect_descriptors(bad_role)
    bad_implementation = replace(
        components,
        user_memory=SimpleNamespace(
            descriptor=ComponentDescriptor(
                role="user_memory", implementation="Wrong", version="mock-v1"
            )
        ),
    )
    with pytest.raises(ContractError, match="unexpected"):
        _collect_descriptors(bad_implementation)


def test_runner_id_allocation_edge_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "runs"
    with pytest.raises(RunInputError):
        _create_run_directory(output, "INVALID")
    explicit = "mock-v1-golden"
    run_id, run_dir = _create_run_directory(output, explicit)
    assert run_id == explicit and run_dir.is_dir()
    with pytest.raises(RunInputError, match="already exists"):
        _create_run_directory(output, explicit)

    collision = "20260801T000000Z-aaaaaaaa"
    (output / collision).mkdir()
    generated = iter((collision, "20260801T000000Z-bbbbbbbb"))
    monkeypatch.setattr("pave_rec.runner.generate_run_id", lambda: next(generated))
    run_id, _ = _create_run_directory(output, None)
    assert run_id.endswith("bbbbbbbb")

    monkeypatch.setattr("pave_rec.runner.generate_run_id", lambda: collision)
    with pytest.raises(RunInputError, match="unique"):
        _create_run_directory(output, None)


def test_runner_rejects_bad_metadata_and_run_id(synthetic_project: Path) -> None:
    config = synthetic_project / "configs/mock.yaml"
    with pytest.raises(RunInputError):
        run_from_config(config, run_id="INVALID", git_metadata=GitMetadata(None, None))
    with pytest.raises(TypeError, match="GitMetadata"):
        run_from_config(config, run_id="mock-v1-golden", git_metadata=object())


def test_git_metadata_success_and_fixture_io_errors(tmp_path: Path, repo_root: Path) -> None:
    metadata = collect_git_metadata(repo_root)
    assert metadata.commit is not None
    assert isinstance(metadata.dirty, bool)
    with pytest.raises(FixtureValidationError, match="cannot read"):
        load_fixture(tmp_path / "missing.json", expected_version="mock-v1")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    with pytest.raises(FixtureValidationError, match="invalid"):
        load_fixture(invalid, expected_version="mock-v1")


def test_runner_wraps_resolved_config_write_failure(
    synthetic_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_write(path, value):
        raise OSError("disk full")

    monkeypatch.setattr("pave_rec.runner.write_canonical_json", fail_write)
    with pytest.raises(ComponentExecutionError, match="resolved_config"):
        run_from_config(
            synthetic_project / "configs/mock.yaml",
            run_id="mock-v1-golden",
            git_metadata=GitMetadata(None, None),
        )
