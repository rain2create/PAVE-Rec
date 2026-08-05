from __future__ import annotations

import hashlib

import pytest

from pave_rec.domain import PreferenceMatchType, PreferenceState, ResourceRef
from pave_rec.phase3.memory import MemoryObservation, build_memory_snapshot


def _checksum(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _ref(label: str) -> ResourceRef:
    return ResourceRef(
        store="semantics",
        key=f"vectors/{label}.f32",
        version="p3vec-" + hashlib.sha256(label.encode()).hexdigest(),
        checksum=_checksum(label),
    )


def _observation(
    index: int,
    vector: tuple[float, float],
    *,
    timestamp: int | None = None,
    label: str | None = None,
) -> MemoryObservation:
    name = label or f"item-{index}"
    return MemoryObservation(
        item_id=name,
        prototype_id=f"proto-{name}",
        semantic_text=f"semantic {name}",
        embedding_ref=_ref(name),
        embedding_row_index=index,
        interaction_index=index,
        occurred_at_ms=index if timestamp is None else timestamp,
        vector=vector,
    )


def _build(observations: tuple[MemoryObservation, ...]):
    return build_memory_snapshot(
        user_id="user-1",
        cutoff_identity="cutoff-1",
        history_projection_checksum=_checksum("history"),
        observations=observations,
    )


def test_empty_semantic_prefix_produces_legal_empty_projection() -> None:
    snapshot = _build(())
    assert snapshot.active_long_tracks == ()
    assert snapshot.short_atoms == ()
    assert snapshot.matches == ()
    assert snapshot.new_interest_drift is None
    assert snapshot.drop_interest_drift is None
    assert snapshot.global_drift is None


def test_replay_promotes_matches_and_projects_stable_emerging_fading() -> None:
    a = (1.0, 0.0)
    b = (0.0, 1.0)
    c = (-1.0, 0.0)
    observations = (
        _observation(0, a),
        _observation(1, a),
        _observation(2, b),
        _observation(3, b),
        _observation(4, a),
        _observation(5, a),
        _observation(6, a),
        _observation(7, a),
        _observation(8, c),
    )
    snapshot = _build(observations)

    assert snapshot.promotion_count == 2
    assert len(snapshot.active_long_tracks) == 2
    assert [short.observation.interaction_index for short in snapshot.short_atoms] == [
        8,
        7,
        6,
        5,
        4,
    ]
    classes = [match.classification for match in snapshot.matches]
    assert classes.count(PreferenceMatchType.STABLE) == 4
    assert classes.count(PreferenceMatchType.EMERGING) == 1
    assert classes.count(PreferenceMatchType.FADING) == 1
    assert snapshot.new_interest_drift is not None
    assert snapshot.drop_interest_drift is not None
    assert snapshot.global_drift is not None
    assert all(
        0.0 <= value <= 1.0
        for value in (
            snapshot.new_interest_drift,
            snapshot.drop_interest_drift,
            snapshot.global_drift,
        )
    )


def test_same_timestamp_support_does_not_promote() -> None:
    snapshot = _build(
        (
            _observation(0, (1.0, 0.0), timestamp=100),
            _observation(1, (1.0, 0.0), timestamp=100),
        )
    )
    assert snapshot.promotion_count == 0
    assert snapshot.active_long_tracks == ()
    assert len(snapshot.pending_tracks) == 1
    assert snapshot.pending_tracks[0].distinct_support_times == 1
    assert snapshot.new_interest_drift == 1.0
    assert all(short.state is PreferenceState.EMERGING for short in snapshot.short_atoms)


def test_inactive_track_remains_matchable_and_reactivates() -> None:
    day = 86_400_000
    prefix = (
        _observation(0, (1.0, 0.0), timestamp=0),
        _observation(1, (1.0, 0.0), timestamp=day),
        _observation(2, (0.0, 1.0), timestamp=100 * day),
        _observation(3, (0.0, 1.0), timestamp=101 * day),
    )
    before = _build(prefix)
    assert len(before.inactive_long_tracks) == 1
    inactive_id = before.inactive_long_tracks[0].atom_id

    after = _build((*prefix, _observation(4, (1.0, 0.0), timestamp=102 * day)))
    assert inactive_id in {track.atom_id for track in after.active_long_tracks}


def test_public_view_contains_exact_embedding_and_matrix_locations() -> None:
    snapshot = _build(
        (
            _observation(0, (1.0, 0.0)),
            _observation(1, (1.0, 0.0)),
        )
    )
    long_ref = ResourceRef(
        store="memory",
        key="bundles/version/long.f32",
        version="p3memoryartifact-" + "1" * 64,
        checksum="sha256:" + "2" * 64,
    )
    matrix_ref = ResourceRef(
        store="memory",
        key="bundles/version/matrix.f32",
        version="p3memoryartifact-" + "1" * 64,
        checksum="sha256:" + "3" * 64,
    )
    source_ref = ResourceRef(
        store="derived",
        key="bundles/source/manifest.json",
        version="source",
        checksum="sha256:" + "4" * 64,
    )
    view = snapshot.to_view(
        memory_version="p3memory-" + "5" * 64,
        long_embedding_ref=long_ref,
        similarity_matrix_ref=matrix_ref,
        semantic_artifact_ref=source_ref,
        derived_artifact_ref=source_ref,
    )
    assert view.semantic_profile is None
    assert view.similarity_matrix_ref == matrix_ref
    assert view.long_term_atoms[0].embedding_ref == long_ref
    assert view.long_term_atoms[0].metadata["embedding_row_index"] == 0
    assert view.preference_matches[0].classification is PreferenceMatchType.STABLE


def test_invalid_order_and_non_unit_vectors_fail_closed() -> None:
    with pytest.raises(ValueError, match="L2-normalized"):
        _observation(0, (2.0, 0.0))
    with pytest.raises(ValueError, match="chronological"):
        _build(
            (
                _observation(1, (1.0, 0.0)),
                _observation(0, (1.0, 0.0)),
            )
        )


def test_projection_caps_long_axis_without_losing_internal_tracks() -> None:
    observations = []
    for basis in range(21):
        vector = tuple(1.0 if index == basis else 0.0 for index in range(21))
        observations.extend(
            (
                MemoryObservation(
                    item_id=f"item-{basis}-a",
                    prototype_id=f"proto-{basis}-a",
                    semantic_text=f"semantic {basis}",
                    embedding_ref=_ref(f"basis-{basis}"),
                    embedding_row_index=basis,
                    interaction_index=basis * 2,
                    occurred_at_ms=basis * 2,
                    vector=vector,
                ),
                MemoryObservation(
                    item_id=f"item-{basis}-b",
                    prototype_id=f"proto-{basis}-b",
                    semantic_text=f"semantic {basis}",
                    embedding_ref=_ref(f"basis-{basis}"),
                    embedding_row_index=basis,
                    interaction_index=basis * 2 + 1,
                    occurred_at_ms=basis * 2 + 1,
                    vector=vector,
                ),
            )
        )
    snapshot = _build(tuple(observations))
    assert len(snapshot.active_long_tracks) == 20
    assert len(snapshot.unprojected_long_tracks) == 1
    assert len(snapshot.inactive_long_tracks) == 0


def test_fp32_cosine_roundoff_is_clipped_to_public_similarity_range() -> None:
    value = 1.0 / (1024**0.5)
    vector = tuple(value for _ in range(1024))
    snapshot = _build(
        (
            MemoryObservation(
                item_id="roundoff-a",
                prototype_id="roundoff-a",
                semantic_text="roundoff",
                embedding_ref=_ref("roundoff"),
                embedding_row_index=0,
                interaction_index=0,
                occurred_at_ms=0,
                vector=vector,
            ),
            MemoryObservation(
                item_id="roundoff-b",
                prototype_id="roundoff-b",
                semantic_text="roundoff",
                embedding_ref=_ref("roundoff"),
                embedding_row_index=0,
                interaction_index=1,
                occurred_at_ms=1,
                vector=vector,
            ),
        )
    )
    assert snapshot.matches[0].similarity is not None
    assert snapshot.matches[0].similarity <= 1.0
