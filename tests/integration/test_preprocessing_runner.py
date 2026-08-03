from __future__ import annotations

import re
from pathlib import Path

import pytest

from pave_rec.errors import ArtifactPublicationError, ConfigurationError
from pave_rec.preprocessing.config import load_preprocessing_config
from pave_rec.preprocessing.models import ExecutionReport
from pave_rec.preprocessing.runner import (
    _allocate_execution_directory,
    _safe_message,
    generate_execution_id,
    preprocess_from_config,
)
from pave_rec.stores.release import ReleaseLoader


def load_report(path: Path) -> ExecutionReport:
    return ExecutionReport.model_validate_json(path.read_bytes())


def test_runner_creates_then_reuses_exact_release(preprocessing_project: Path) -> None:
    config = preprocessing_project / "configs/preprocessing/fixture.yaml"
    created = preprocess_from_config(config)
    reused = preprocess_from_config(config)

    assert created.outcome == "created"
    assert reused.outcome == "reused"
    assert created.data_version == reused.data_version
    assert created.release_ref == reused.release_ref
    assert (created.item_count, created.behavior_event_count, created.segment_count) == (3, 6, 6)
    assert created.artifact_count == reused.artifact_count == 12
    assert created.execution_id != reused.execution_id

    for result in (created, reused):
        report = load_report(result.execution_report_path)
        assert report.status == "succeeded"
        assert report.outcome == result.outcome
        assert report.data_version == result.data_version
        assert report.release_ref == result.release_ref
        assert report.error_code is report.error_message is None
        assert len(report.roots) == 3
        assert len(report.component_descriptors) == 4

    loaded = load_preprocessing_config(config)
    release = ReleaseLoader(loaded.root_registry).load(created.release_ref)
    assert release.data_version == created.data_version


def test_declared_failure_records_known_plan_state(
    preprocessing_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_publish(self, plan, *, execution_id):
        raise ArtifactPublicationError(f"cannot publish /private/secret/{execution_id}")

    monkeypatch.setattr(
        "pave_rec.preprocessing.runner.FilesystemReleasePublisher.publish", fail_publish
    )
    config = preprocessing_project / "configs/preprocessing/fixture.yaml"
    with pytest.raises(ArtifactPublicationError, match="cannot publish"):
        preprocess_from_config(config)

    reports = tuple((preprocessing_project / "runs/preprocessing").glob("*/execution_report.json"))
    assert len(reports) == 1
    report = load_report(reports[0])
    assert report.status == "failed"
    assert report.outcome is None and report.release_ref is None
    assert report.data_version is not None
    assert (report.item_count, report.behavior_event_count, report.segment_count) == (3, 6, 6)
    assert report.artifact_count == 12
    assert len(report.staging_locations) == 2
    assert report.error_code == "ArtifactPublicationError"
    assert "<path>" in report.error_message
    assert "/private/secret" not in report.error_message


def test_config_failure_precedes_execution_directory(preprocessing_project: Path) -> None:
    with pytest.raises(ConfigurationError):
        preprocess_from_config(preprocessing_project / "configs/preprocessing/missing.yaml")
    assert not (preprocessing_project / "runs/preprocessing").exists()


def test_failed_report_write_does_not_hide_original_error(
    preprocessing_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_publish(self, plan, *, execution_id):
        raise ArtifactPublicationError("original publication failure")

    def fail_report(path, value):
        raise OSError("report filesystem failure")

    monkeypatch.setattr(
        "pave_rec.preprocessing.runner.FilesystemReleasePublisher.publish", fail_publish
    )
    monkeypatch.setattr("pave_rec.preprocessing.runner.write_canonical_json", fail_report)
    with pytest.raises(ArtifactPublicationError, match="original publication failure"):
        preprocess_from_config(preprocessing_project / "configs/preprocessing/fixture.yaml")


def test_success_report_failure_preserves_complete_release(
    preprocessing_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = preprocessing_project / "configs/preprocessing/fixture.yaml"
    original_write = __import__(
        "pave_rec.preprocessing.runner", fromlist=["write_canonical_json"]
    ).write_canonical_json

    def fail_report(path, value):
        if path.name == "execution_report.json":
            raise OSError("report filesystem failure")
        original_write(path, value)

    with monkeypatch.context() as context:
        context.setattr("pave_rec.preprocessing.runner.write_canonical_json", fail_report)
        with pytest.raises(ArtifactPublicationError, match="release is complete"):
            preprocess_from_config(config)

    recovered = preprocess_from_config(config)
    assert recovered.outcome == "reused"
    assert load_report(recovered.execution_report_path).status == "succeeded"


def test_execution_identity_and_allocation_collision(
    preprocessing_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", generate_execution_id())
    execution_root = preprocessing_project / "runs/preprocessing"
    collision_id = "20260803T000000Z-00000000"
    (execution_root / collision_id).mkdir(parents=True)
    monkeypatch.setattr("pave_rec.preprocessing.runner.generate_execution_id", lambda: collision_id)
    with pytest.raises(ArtifactPublicationError, match="unique"):
        _allocate_execution_directory(preprocessing_project)


def test_safe_error_message_is_bounded_and_nonempty() -> None:
    assert _safe_message(ArtifactPublicationError("")) == "ArtifactPublicationError"
    assert len(_safe_message(ArtifactPublicationError("x" * 1000))) == 500
