from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from pave_rec.config import (
    Phase1Config,
    load_config,
    validate_run_id,
    with_actual_run_id,
)
from pave_rec.errors import ConfigurationError, RunInputError
from pave_rec.runner import generate_run_id


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def test_config_inheritance_and_normalization(synthetic_project: Path) -> None:
    experiment = synthetic_project / "configs/experiments/zero.yaml"
    _write(
        experiment,
        "extends: ../mock.yaml\nagent:\n  max_perception_actions: 0\nstop:\n"
        "  ranking_margin_threshold: null\n",
    )
    loaded = load_config(experiment)
    assert loaded.project_root == synthetic_project.resolve()
    assert loaded.config.agent.max_perception_actions == 0
    assert loaded.config.stop.ranking_margin_threshold is None
    assert loaded.config.stop.min_segment_value == 0.15
    assert loaded.config.input.fixture_path == "tests/fixtures/mock/v1/scenario.json"
    assert "extends" not in loaded.config.model_dump(mode="json")


@pytest.mark.parametrize(
    ("relative", "content", "message"),
    [
        ("configs/bad.yaml", "- item\n", "mapping"),
        ("configs/bad.yaml", "extends: ''\n", "extends"),
        ("configs/bad.yaml", "extends: C:/outside.yaml\n", "relative"),
        ("outside.yaml", "schema_version: '1'\n", "project root"),
    ],
)
def test_invalid_config_files(
    tmp_path: Path, synthetic_project: Path, relative: str, content: str, message: str
) -> None:
    base = synthetic_project if relative.startswith("configs") else tmp_path
    path = base / relative
    _write(path, content)
    with pytest.raises(ConfigurationError, match=message):
        load_config(path)


def test_config_cycle_is_rejected(synthetic_project: Path) -> None:
    first = synthetic_project / "configs/first.yaml"
    second = synthetic_project / "configs/second.yaml"
    _write(first, "extends: second.yaml\n")
    _write(second, "extends: first.yaml\n")
    with pytest.raises(ConfigurationError, match="cycle"):
        load_config(first)


@pytest.mark.parametrize(
    "override",
    [
        "unknown: true\n",
        "components:\n  perceiver: arbitrary\n",
        "seed: -1\n",
        "agent:\n  max_perception_actions: -1\n",
        "stop:\n  ranking_margin_threshold: -0.1\n",
        "run:\n  output_root: C:/outside\n",
        "input:\n  fixture_path: ../../outside.json\n",
    ],
)
def test_strict_config_and_path_validation(synthetic_project: Path, override: str) -> None:
    path = synthetic_project / "configs/bad.yaml"
    _write(path, f"extends: mock.yaml\n{override}")
    with pytest.raises(ConfigurationError):
        load_config(path)


def test_missing_extended_config_and_non_file(synthetic_project: Path) -> None:
    missing = synthetic_project / "configs/missing-parent.yaml"
    _write(missing, "extends: absent.yaml\n")
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_config(missing)
    with pytest.raises(ConfigurationError, match="not a file"):
        load_config(synthetic_project / "configs")


def test_run_id_validation_and_frozen_update(synthetic_project: Path) -> None:
    config = load_config(synthetic_project / "configs/mock.yaml").config
    resolved = with_actual_run_id(config, "mock-v1-golden")
    assert resolved.run.run_id == "mock-v1-golden"
    assert config.run.run_id is None
    generated = generate_run_id()
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", generated)
    assert validate_run_id(generated) == generated
    with pytest.raises((RunInputError, ValueError)):
        with_actual_run_id(config, "BAD")


def test_config_model_rejects_non_strict_values(synthetic_project: Path) -> None:
    payload = load_config(synthetic_project / "configs/mock.yaml").config.model_dump(mode="python")
    payload["seed"] = "7"
    with pytest.raises(ValidationError):
        Phase1Config.model_validate(payload)


def test_symlink_escape_is_rejected_when_supported(tmp_path: Path, synthetic_project: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "scenario.json").write_text("{}", encoding="utf-8")
    link = synthetic_project / "linked-outside"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable on this platform: {exc}")
    config = synthetic_project / "configs/symlink.yaml"
    _write(
        config,
        "extends: mock.yaml\ninput:\n  fixture_path: linked-outside/scenario.json\n",
    )
    with pytest.raises(ConfigurationError, match="escapes"):
        load_config(config)
