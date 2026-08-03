from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from pave_rec.errors import ArtifactIntegrityError, ArtifactPublicationError
from pave_rec.preprocessing.artifacts import ReleasePublicationPlan, build_release_plan
from pave_rec.preprocessing.components import build_preprocessing_components
from pave_rec.preprocessing.config import load_preprocessing_config
from pave_rec.preprocessing.identity import build_data_identity, data_version
from pave_rec.preprocessing.publisher import FilesystemReleasePublisher
from pave_rec.preprocessing.source import load_source_dataset


def make_plan(project: Path):
    loaded = load_preprocessing_config(project / "configs/preprocessing/fixture.yaml")
    source = load_source_dataset(loaded)
    components = build_preprocessing_components(loaded.config)
    identity = build_data_identity(
        source=source,
        config=loaded.config,
        component_descriptors=components.descriptors,
    )
    version = data_version(identity)
    plan = build_release_plan(
        version=version,
        identity=identity,
        source=source,
        config=loaded.config,
        components=components,
    )
    return loaded, source, plan


def published_path(loaded, ref) -> Path:
    return loaded.root_registry.require(ref.store).path.joinpath(*ref.key.split("/"))


def test_release_plan_has_expected_fixture_graph(preprocessing_project: Path) -> None:
    _, source, plan = make_plan(preprocessing_project)
    assert plan.artifact_count == 12
    assert [(root.root_id, len(root.artifacts)) for root in plan.roots] == [
        ("features", 9),
        ("processed", 3),
    ]
    assert plan.release_ref.version == plan.data_version
    assert plan.release_manifest.identity.source_manifest == source.manifest
    assert tuple(ref.store for ref in plan.release_manifest.root_bundle_manifest_refs) == (
        "features",
        "processed",
    )


def test_publisher_creates_then_verifies_reuse(preprocessing_project: Path) -> None:
    loaded, _, plan = make_plan(preprocessing_project)
    publisher = FilesystemReleasePublisher(loaded.root_registry)
    created = publisher.publish(plan, execution_id="execution-created")
    reused = publisher.publish(plan, execution_id="execution-reused")
    assert (created.outcome, reused.outcome) == ("created", "reused")
    assert published_path(loaded, plan.release_ref).read_bytes() == plan.release_payload
    for root in plan.roots:
        for ref, payload in root.files:
            assert published_path(loaded, ref).read_bytes() == payload


def test_existing_corruption_fails_without_overwrite(preprocessing_project: Path) -> None:
    loaded, _, plan = make_plan(preprocessing_project)
    publisher = FilesystemReleasePublisher(loaded.root_registry)
    publisher.publish(plan, execution_id="execution-created")
    artifact = plan.roots[0].artifacts[0]
    path = published_path(loaded, artifact.entry.resource_ref)
    path.write_bytes(b"corrupt")
    with pytest.raises(ArtifactIntegrityError, match="mismatch"):
        publisher.publish(plan, execution_id="execution-corrupt")
    assert path.read_bytes() == b"corrupt"


def test_release_publish_failure_leaves_only_undiscoverable_orphans(
    preprocessing_project: Path,
) -> None:
    loaded, _, plan = make_plan(preprocessing_project)

    def fail(boundary: str) -> None:
        if boundary == "before_release_publish":
            raise OSError("injected release failure")

    publisher = FilesystemReleasePublisher(loaded.root_registry, fault_injector=fail)
    with pytest.raises(ArtifactPublicationError, match="exclusively"):
        publisher.publish(plan, execution_id="execution-failed")
    assert not published_path(loaded, plan.release_ref).exists()
    assert all(published_path(loaded, root.manifest_ref).exists() for root in plan.roots)
    recovered = FilesystemReleasePublisher(loaded.root_registry).publish(
        plan, execution_id="execution-recovered"
    )
    assert recovered.outcome == "created"


def test_root_rename_failure_does_not_publish_release(preprocessing_project: Path) -> None:
    loaded, _, plan = make_plan(preprocessing_project)

    def fail(boundary: str) -> None:
        if boundary.startswith("before_root_rename"):
            raise OSError("injected root failure")

    with pytest.raises(ArtifactPublicationError, match="root bundle"):
        FilesystemReleasePublisher(loaded.root_registry, fault_injector=fail).publish(
            plan, execution_id="execution-failed"
        )
    assert not published_path(loaded, plan.release_ref).exists()
    staging = loaded.root_registry.require(plan.roots[0].root_id).path / "staging"
    assert staging.exists()


def test_same_identity_with_different_bytes_is_integrity_failure(
    preprocessing_project: Path,
) -> None:
    loaded, _, plan = make_plan(preprocessing_project)
    FilesystemReleasePublisher(loaded.root_registry).publish(plan, execution_id="execution-created")
    altered = ReleasePublicationPlan(
        data_version=plan.data_version,
        identity=plan.identity,
        roots=plan.roots,
        release_manifest=plan.release_manifest,
        release_ref=plan.release_ref,
        release_payload=plan.release_payload + b" ",
    )
    with pytest.raises(ArtifactIntegrityError, match="mismatch"):
        FilesystemReleasePublisher(loaded.root_registry).publish(
            altered, execution_id="execution-altered"
        )


def test_real_two_invocation_race_has_one_creator(preprocessing_project: Path) -> None:
    loaded, _, plan = make_plan(preprocessing_project)
    final_publish_barrier = Barrier(2)

    def synchronize(boundary: str) -> None:
        if boundary == "before_release_publish":
            final_publish_barrier.wait(timeout=5)

    def invoke(execution_id: str) -> str:
        publisher = FilesystemReleasePublisher(loaded.root_registry, fault_injector=synchronize)
        return publisher.publish(plan, execution_id=execution_id).outcome

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(invoke, ("execution-race-a", "execution-race-b")))
    assert sorted(outcomes) == ["created", "reused"]
    assert published_path(loaded, plan.release_ref).read_bytes() == plan.release_payload


def test_staging_verification_detects_tampering(preprocessing_project: Path) -> None:
    loaded, _, plan = make_plan(preprocessing_project)
    execution_id = "execution-tampered-stage"

    def tamper(boundary: str) -> None:
        if boundary == "after_stage_write:features":
            stage = (
                loaded.root_registry.require("features").path
                / "staging"
                / plan.data_version
                / execution_id
            )
            target = next(path for path in stage.rglob("*.json") if path.is_file())
            target.write_bytes(b"tampered")

    publisher = FilesystemReleasePublisher(loaded.root_registry, fault_injector=tamper)
    with pytest.raises(ArtifactIntegrityError, match="mismatch"):
        publisher.publish(plan, execution_id=execution_id)
    assert not published_path(loaded, plan.release_ref).exists()


def test_staging_io_failure_is_publication_error(preprocessing_project: Path) -> None:
    loaded, _, plan = make_plan(preprocessing_project)

    def fail(boundary: str) -> None:
        if boundary.startswith("after_stage_write"):
            raise OSError("injected staging I/O failure")

    publisher = FilesystemReleasePublisher(loaded.root_registry, fault_injector=fail)
    with pytest.raises(ArtifactPublicationError, match="stage"):
        publisher.publish(plan, execution_id="execution-stage-io")
    assert not published_path(loaded, plan.release_ref).exists()
