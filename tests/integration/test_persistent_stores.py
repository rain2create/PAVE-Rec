from __future__ import annotations

from pathlib import Path

import pytest

from pave_rec.domain import ResourceRef
from pave_rec.errors import ArtifactIntegrityError, ContractError, ResourceResolutionError
from pave_rec.fixture import MockFixture
from pave_rec.preprocessing.artifacts import build_release_plan
from pave_rec.preprocessing.components import build_preprocessing_components
from pave_rec.preprocessing.config import load_preprocessing_config
from pave_rec.preprocessing.identity import build_data_identity, data_version
from pave_rec.preprocessing.publisher import FilesystemReleasePublisher
from pave_rec.preprocessing.source import load_source_dataset
from pave_rec.stores.filesystem import FilesystemItemFeatureStore, FilesystemSegmentStore
from pave_rec.stores.loaders import ItemFeatureRecordLoader, SegmentProxyRecordLoader
from pave_rec.stores.release import ReleaseLoader
from pave_rec.stores.resolver import FilesystemResourceResolver


def publish_and_load(project: Path):
    loaded_config = load_preprocessing_config(project / "configs/preprocessing/fixture.yaml")
    source = load_source_dataset(loaded_config)
    components = build_preprocessing_components(loaded_config.config)
    identity = build_data_identity(
        source=source,
        config=loaded_config.config,
        component_descriptors=components.descriptors,
    )
    version = data_version(identity)
    plan = build_release_plan(
        version=version,
        identity=identity,
        source=source,
        config=loaded_config.config,
        components=components,
    )
    FilesystemReleasePublisher(loaded_config.root_registry).publish(
        plan, execution_id="persistent-store-test"
    )
    release = ReleaseLoader(loaded_config.root_registry).load(plan.release_ref)
    return loaded_config, plan, release


def local_path(loaded_config, ref: ResourceRef) -> Path:
    return loaded_config.root_registry.require(ref.store).path.joinpath(*ref.key.split("/"))


def test_exact_release_constructs_shared_immutable_data_plane(
    preprocessing_project: Path,
) -> None:
    _, plan, release = publish_and_load(preprocessing_project)
    resolver = FilesystemResourceResolver(release)
    item_store = FilesystemItemFeatureStore(release)
    segment_store = FilesystemSegmentStore(release)
    assert resolver.loaded_release is item_store.loaded_release is segment_store.loaded_release
    assert release.data_version == plan.data_version
    requested = ("item_c", "item_a")
    assert tuple(entry.item_id for entry in item_store.load_refs(requested)) == requested
    assert tuple(entry.item_id for entry in segment_store.load_catalog(requested)) == requested
    with pytest.raises(ContractError, match="unknown"):
        item_store.load_refs(("missing",))
    with pytest.raises(ContractError, match="unknown"):
        segment_store.load_catalog(("missing",))


def test_typed_feature_and_proxy_loaders_validate_lazy_payloads(
    preprocessing_project: Path,
) -> None:
    _, _, release = publish_and_load(preprocessing_project)
    resolver = FilesystemResourceResolver(release)
    item_ref = release.item_feature_index.entries[0]
    assert item_ref.feature_ref is not None
    item = ItemFeatureRecordLoader(resolver).load(
        item_ref.feature_ref, expected_item_id=item_ref.item_id
    )
    catalog = release.segment_store_index.catalogs[0]
    proxy_ref = catalog.segment_proxy_refs[0]
    proxy = SegmentProxyRecordLoader(resolver).load(
        proxy_ref.feature_ref,
        expected_item_id=proxy_ref.item_id,
        expected_segment_id=proxy_ref.segment_id,
    )
    assert item.item_id == "item_a"
    assert (proxy.item_id, proxy.segment_id) == ("item_a", "segment_1")
    assert resolver.resolve_verified_path(proxy_ref.feature_ref).is_file()

    with pytest.raises(ArtifactIntegrityError, match="record identity"):
        ItemFeatureRecordLoader(resolver).load(item_ref.feature_ref, expected_item_id="wrong-item")
    with pytest.raises(ArtifactIntegrityError, match="record identity"):
        SegmentProxyRecordLoader(resolver).load(
            proxy_ref.feature_ref,
            expected_item_id="item_a",
            expected_segment_id="wrong-segment",
        )


def test_feature_corruption_is_lazy_and_never_downgrades_to_missing(
    preprocessing_project: Path,
) -> None:
    loaded_config, plan, release = publish_and_load(preprocessing_project)
    feature_ref = release.item_feature_index.entries[0].feature_ref
    assert feature_ref is not None
    local_path(loaded_config, feature_ref).write_bytes(b"corrupt")
    reloaded = ReleaseLoader(loaded_config.root_registry).load(plan.release_ref)
    with pytest.raises(ResourceResolutionError, match="size|checksum"):
        FilesystemResourceResolver(reloaded).read_verified_bytes(feature_ref)


def test_resolver_rejects_ref_outside_loaded_inventory(preprocessing_project: Path) -> None:
    _, _, release = publish_and_load(preprocessing_project)
    resolver = FilesystemResourceResolver(release)
    unlisted = ResourceRef(
        store="source",
        key="source_manifest.json",
        version="preprocessing-v1",
        checksum=release.release_ref.checksum,
    )
    with pytest.raises(ResourceResolutionError, match="outside loaded release"):
        resolver.read_verified_bytes(unlisted)


def test_release_loader_rejects_non_exact_ref(preprocessing_project: Path) -> None:
    loaded_config, plan, _ = publish_and_load(preprocessing_project)
    with pytest.raises(ArtifactIntegrityError, match="key/version"):
        ReleaseLoader(loaded_config.root_registry).load(
            plan.release_ref.model_copy(update={"key": "releases/latest.json"})
        )


def test_persistent_store_identity_order_matches_phase1_fixture(
    preprocessing_project: Path, mock_fixture: MockFixture
) -> None:
    _, _, release = publish_and_load(preprocessing_project)
    persistent = FilesystemSegmentStore(release).load_catalog(mock_fixture.input.candidate_ids)
    expected_identities = tuple(
        (segment.item_id, segment.segment_id)
        for catalog in mock_fixture.segment_catalog
        for segment in catalog.segments
    )
    actual_identities = tuple(
        (segment.item_id, segment.segment_id)
        for catalog in persistent
        for segment in catalog.segments
    )
    assert actual_identities == expected_identities
