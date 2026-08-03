from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from pave_rec.preprocessing.config import load_preprocessing_config
from pave_rec.preprocessing.models import ExecutionReport, PreprocessingResult
from pave_rec.preprocessing.runner import preprocess_from_config


def portable_tree(project: Path, result: PreprocessingResult) -> dict[str, bytes]:
    loaded = load_preprocessing_config(project / "configs/preprocessing/fixture.yaml")
    tree: dict[str, bytes] = {}
    for root_id in (
        loaded.config.output.features_root_id,
        loaded.config.output.processed_root_id,
    ):
        root = loaded.root_registry.require(root_id).path
        for path in sorted((root / "bundles" / result.data_version).rglob("*")):
            if path.is_file():
                tree[f"{root_id}/{path.relative_to(root).as_posix()}"] = path.read_bytes()
    release = loaded.root_registry.require(result.release_ref.store).path.joinpath(
        *result.release_ref.key.split("/")
    )
    tree[f"{result.release_ref.store}/{result.release_ref.key}"] = release.read_bytes()
    return tree


def expected_tree(expected_root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(expected_root).as_posix(): path.read_bytes()
        for path in sorted(expected_root.rglob("*"))
        if path.is_file()
    }


def parse_cli_result(stdout: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in stdout.splitlines())


def test_api_cli_equivalence_and_versioned_golden(
    preprocessing_project_factory: Callable[[str], Path], repo_root: Path
) -> None:
    api_project = preprocessing_project_factory("api-project")
    cli_project = preprocessing_project_factory("cli-project")
    api_result = preprocess_from_config(api_project / "configs/preprocessing/fixture.yaml")

    command = [
        sys.executable,
        "-m",
        "pave_rec.cli.preprocess",
        "--config",
        "configs/preprocessing/fixture.yaml",
    ]
    completed = subprocess.run(
        command,
        cwd=cli_project,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0 and completed.stderr == ""
    fields = parse_cli_result(completed.stdout)
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", fields["execution_id"])
    assert fields["outcome"] == "created"
    assert fields["data_version"] == api_result.data_version
    assert fields["release_ref"] == (
        f"{api_result.release_ref.store}:{api_result.release_ref.key}"
        f"@{api_result.release_ref.version}#{api_result.release_ref.checksum}"
    )
    cli_report = ExecutionReport.model_validate_json(Path(fields["execution_report"]).read_bytes())
    assert (cli_report.item_count, cli_report.behavior_event_count, cli_report.segment_count) == (
        api_result.item_count,
        api_result.behavior_event_count,
        api_result.segment_count,
    )
    assert cli_report.artifact_count == api_result.artifact_count

    api_tree = portable_tree(api_project, api_result)
    loaded_cli = load_preprocessing_config(cli_project / "configs/preprocessing/fixture.yaml")
    cli_release_path = loaded_cli.root_registry.require("processed").path / "releases"
    cli_release_file = next(cli_release_path.glob("p2-*.json"))
    assert cli_release_file.name == f"{api_result.data_version}.json"
    assert portable_tree(cli_project, api_result) == api_tree
    assert api_tree == expected_tree(repo_root / "tests/fixtures/preprocessing/v1/expected")

    reused = subprocess.run(
        command,
        cwd=cli_project,
        check=False,
        capture_output=True,
        text=True,
    )
    assert reused.returncode == 0 and parse_cli_result(reused.stdout)["outcome"] == "reused"


def test_nonbinding_limits_and_physical_roots_do_not_change_portable_bytes(
    preprocessing_project_factory: Callable[[str], Path],
) -> None:
    first = preprocessing_project_factory("identity-first")
    second = preprocessing_project_factory("identity-second")
    base = second / "configs/preprocessing/base.yaml"
    payload = base.read_text(encoding="utf-8")
    payload = payload.replace("max_items: 100", "max_items: 1000")
    payload = payload.replace("max_behavior_events: 1000", "max_behavior_events: 2000")
    base.write_text(payload, encoding="utf-8", newline="\n")

    first_result = preprocess_from_config(first / "configs/preprocessing/fixture.yaml")
    second_result = preprocess_from_config(second / "configs/preprocessing/fixture.yaml")
    assert first_result.data_version == second_result.data_version
    assert first_result.release_ref == second_result.release_ref
    assert portable_tree(first, first_result) == portable_tree(second, second_result)


def test_source_manifest_formatting_is_not_semantic(
    preprocessing_project_factory: Callable[[str], Path],
) -> None:
    canonical_project = preprocessing_project_factory("canonical-manifest")
    reformatted_project = preprocessing_project_factory("reformatted-manifest")
    manifest_path = (
        reformatted_project / "tests/fixtures/preprocessing/v1/source/source_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reformatted = (json.dumps(manifest, indent=4, ensure_ascii=False) + "\n").encode()
    manifest_path.write_bytes(reformatted)
    fixture_config = reformatted_project / "configs/preprocessing/fixture.yaml"
    config_payload = fixture_config.read_text(encoding="utf-8")
    new_checksum = f"sha256:{hashlib.sha256(reformatted).hexdigest()}"
    config_payload = re.sub(
        r"checksum: sha256:[0-9a-f]{64}", f"checksum: {new_checksum}", config_payload
    )
    fixture_config.write_text(config_payload, encoding="utf-8", newline="\n")

    canonical = preprocess_from_config(canonical_project / "configs/preprocessing/fixture.yaml")
    reformatted_result = preprocess_from_config(fixture_config)
    assert reformatted_result.data_version == canonical.data_version
    assert reformatted_result.release_ref == canonical.release_ref
    assert portable_tree(reformatted_project, reformatted_result) == portable_tree(
        canonical_project, canonical
    )
