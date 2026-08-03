from __future__ import annotations

from pathlib import Path

import pytest

from pave_rec.cli import preprocess as cli
from pave_rec.domain import ResourceRef
from pave_rec.errors import (
    ArtifactPublicationError,
    ConfigurationError,
    DatasetValidationError,
)
from pave_rec.preprocessing.models import PreprocessingResult


def result() -> PreprocessingResult:
    return PreprocessingResult(
        execution_id="20260803T000000Z-00000000",
        outcome="created",
        data_version=f"p2-{'a' * 64}",
        release_ref=ResourceRef(
            store="processed",
            key=f"releases/p2-{'a' * 64}.json",
            version=f"p2-{'a' * 64}",
            checksum=f"sha256:{'b' * 64}",
        ),
        execution_report_path=Path("runs/preprocessing/report.json"),
        item_count=3,
        behavior_event_count=6,
        segment_count=6,
        artifact_count=12,
    )


def test_cli_success_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(cli, "preprocess_from_config", lambda path: result())
    assert cli.main(["--config", "fixture.yaml"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [
        "execution_id=20260803T000000Z-00000000",
        "outcome=created",
        f"data_version=p2-{'a' * 64}",
        f"release_ref=processed:releases/p2-{'a' * 64}.json@p2-{'a' * 64}#sha256:{'b' * 64}",
        f"execution_report={Path('runs/preprocessing/report.json')}",
    ]


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (ConfigurationError("bad config"), 2),
        (DatasetValidationError("bad dataset"), 2),
        (ArtifactPublicationError("bad publish"), 1),
    ],
)
def test_cli_declared_failure_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    error: Exception,
    expected_code: int,
) -> None:
    def fail(path):
        raise error

    monkeypatch.setattr(cli, "preprocess_from_config", fail)
    assert cli.main(["--config", "fixture.yaml"]) == expected_code
    captured = capsys.readouterr()
    assert captured.out == ""
    assert type(error).__name__ in captured.err


def test_cli_interrupt_and_unexpected_error_semantics(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def interrupt(path):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "preprocess_from_config", interrupt)
    assert cli.main(["--config", "fixture.yaml"]) == 130
    assert capsys.readouterr().err == "interrupted\n"

    def unexpected(path):
        raise RuntimeError("programming error")

    monkeypatch.setattr(cli, "preprocess_from_config", unexpected)
    with pytest.raises(RuntimeError, match="programming error"):
        cli.main(["--config", "fixture.yaml"])


def test_public_package_exports_are_lazy_and_available() -> None:
    from pave_rec.preprocessing import (
        LoadedPreprocessingConfig,
        Phase2PreprocessingConfig,
        PreprocessingResult,
        load_preprocessing_config,
        preprocess_from_config,
    )
    from pave_rec.stores import (
        FilesystemItemFeatureStore,
        FilesystemResourceResolver,
        FilesystemSegmentStore,
        LoadedRelease,
        ReleaseLoader,
        ResourceResolver,
    )

    assert all(
        value is not None
        for value in (
            LoadedPreprocessingConfig,
            Phase2PreprocessingConfig,
            PreprocessingResult,
            load_preprocessing_config,
            preprocess_from_config,
            FilesystemItemFeatureStore,
            FilesystemResourceResolver,
            FilesystemSegmentStore,
            LoadedRelease,
            ReleaseLoader,
            ResourceResolver,
        )
    )
