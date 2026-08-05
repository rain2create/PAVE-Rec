"""Deterministic dynamic-hybrid memory replay and public-view projection."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

import numpy as np

from pave_rec.domain import (
    PreferenceAtomView,
    PreferenceMatchType,
    PreferenceMatchView,
    PreferenceState,
    ResourceRef,
    UserMemoryView,
)
from pave_rec.domain.serialization import canonical_json_bytes

MEMORY_RECIPE = "dynamic-hybrid-memory-v1"
RECENT_SHORT_COUNT = 5
MAX_PROJECTED_LONG = 20
MATCH_THRESHOLD = 0.70
EMA_ETA = 0.20
PROMOTION_DISTINCT_TIMES = 2
PERSISTENCE_SATURATION = 5
RECENCY_HALF_LIFE_DAYS = 7.0
INACTIVE_STRENGTH = 0.10
MILLISECONDS_PER_DAY = 86_400_000


def _unit(vector: tuple[float, ...]) -> tuple[float, ...]:
    if not vector or any(not math.isfinite(value) for value in vector):
        raise ValueError("memory vectors must be finite and non-empty")
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("memory vectors must have a positive finite norm")
    return tuple(value / norm for value in vector)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise ValueError("memory vectors must have one fixed dimension")
    # P3-06 fixes matching/matrix semantics to FP32. NumPy keeps the hot replay
    # path practical while making that precision boundary explicit.
    value = float(
        np.dot(
            np.asarray(left, dtype=np.float32),
            np.asarray(right, dtype=np.float32),
        )
    )
    return min(max(value, -1.0), 1.0)


def _clip_unit(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _stable_id(prefix: str, payload: object) -> str:
    return prefix + hashlib.sha256(canonical_json_bytes(payload, pretty=False)).hexdigest()


@dataclass(frozen=True)
class MemoryObservation:
    """One cutoff-safe positive_v1 event with its exact P3-05 semantics."""

    item_id: str
    prototype_id: str
    semantic_text: str
    embedding_ref: ResourceRef
    embedding_row_index: int
    interaction_index: int
    occurred_at_ms: int
    vector: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.item_id or not self.prototype_id or not self.semantic_text:
            raise ValueError("memory observation identities/text must not be empty")
        if self.embedding_row_index < 0 or self.interaction_index < 0 or self.occurred_at_ms < 0:
            raise ValueError("memory observation indexes/timestamp must be non-negative")
        normalized = _unit(self.vector)
        if any(
            not math.isclose(left, right, rel_tol=1e-5, abs_tol=1e-5)
            for left, right in zip(self.vector, normalized, strict=True)
        ):
            raise ValueError("memory observation vector must be L2-normalized")

    @property
    def event_identity(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "prototype_id": self.prototype_id,
            "interaction_index": self.interaction_index,
            "occurred_at_ms": self.occurred_at_ms,
        }


@dataclass
class _MutableTrack:
    atom_id: str
    centroid: tuple[float, ...]
    supports: list[MemoryObservation] = field(default_factory=list)

    @property
    def distinct_support_times(self) -> int:
        return len({entry.occurred_at_ms for entry in self.supports})

    def reinforce(self, observation: MemoryObservation) -> None:
        self.supports.append(observation)
        self.centroid = _unit(
            tuple(
                (1.0 - EMA_ETA) * old + EMA_ETA * new
                for old, new in zip(self.centroid, observation.vector, strict=True)
            )
        )


@dataclass(frozen=True)
class MemoryTrack:
    atom_id: str
    centroid: tuple[float, ...]
    supports: tuple[MemoryObservation, ...]
    medoid: MemoryObservation
    strength: float
    persistence: float
    inactive: bool

    @property
    def created_at_ms(self) -> int:
        return self.supports[0].occurred_at_ms

    @property
    def last_seen_at_ms(self) -> int:
        return self.supports[-1].occurred_at_ms

    @property
    def distinct_support_times(self) -> int:
        return len({entry.occurred_at_ms for entry in self.supports})


@dataclass(frozen=True)
class ProjectedShort:
    atom_id: str
    observation: MemoryObservation
    assigned_track_id: str
    strength: float
    persistence: float
    state: PreferenceState


@dataclass(frozen=True)
class MemoryMatch:
    long_atom_id: str | None
    short_atom_id: str | None
    similarity: float | None
    classification: PreferenceMatchType


@dataclass(frozen=True)
class BuiltMemorySnapshot:
    user_id: str
    cutoff_identity: str
    history_projection_checksum: str
    updated_at_ms: int | None
    active_long_tracks: tuple[MemoryTrack, ...]
    unprojected_long_tracks: tuple[MemoryTrack, ...]
    inactive_long_tracks: tuple[MemoryTrack, ...]
    pending_tracks: tuple[MemoryTrack, ...]
    short_atoms: tuple[ProjectedShort, ...]
    matches: tuple[MemoryMatch, ...]
    similarity_matrix: tuple[tuple[float, ...], ...]
    new_interest_drift: float | None
    drop_interest_drift: float | None
    global_drift: float | None
    promotion_count: int
    observed_count: int

    def to_view(
        self,
        *,
        memory_version: str,
        long_embedding_ref: ResourceRef | None,
        similarity_matrix_ref: ResourceRef | None,
        semantic_artifact_ref: ResourceRef,
        derived_artifact_ref: ResourceRef,
    ) -> UserMemoryView:
        if self.active_long_tracks and long_embedding_ref is None:
            raise ValueError("projected long atoms require an embedding shard reference")
        if bool(self.active_long_tracks and self.short_atoms) != bool(similarity_matrix_ref):
            raise ValueError("matrix ref presence must match non-empty long/short axes")
        long_states = {
            match.long_atom_id: (
                PreferenceState.STABLE
                if match.classification is PreferenceMatchType.STABLE
                else PreferenceState.FADING
            )
            for match in self.matches
            if match.long_atom_id is not None
        }
        long_atoms = tuple(
            PreferenceAtomView(
                atom_id=track.atom_id,
                text=track.medoid.semantic_text,
                state=long_states[track.atom_id],
                strength=track.strength,
                persistence=track.persistence,
                created_at_ms=track.created_at_ms,
                last_seen_at_ms=track.last_seen_at_ms,
                embedding_ref=long_embedding_ref,
                metadata={
                    "embedding_row_index": row_index,
                    "medoid_prototype_id": track.medoid.prototype_id,
                    "support_count": len(track.supports),
                },
            )
            for row_index, track in enumerate(self.active_long_tracks)
        )
        short_atoms = tuple(
            PreferenceAtomView(
                atom_id=short.atom_id,
                text=short.observation.semantic_text,
                state=short.state,
                strength=short.strength,
                persistence=short.persistence,
                created_at_ms=short.observation.occurred_at_ms,
                last_seen_at_ms=short.observation.occurred_at_ms,
                embedding_ref=short.observation.embedding_ref,
                metadata={
                    "embedding_row_index": short.observation.embedding_row_index,
                    "item_id": short.observation.item_id,
                    "prototype_id": short.observation.prototype_id,
                    "source_interaction_index": short.observation.interaction_index,
                },
            )
            for short in self.short_atoms
        )
        return UserMemoryView(
            long_term_atoms=long_atoms,
            short_term_atoms=short_atoms,
            preference_matches=tuple(
                PreferenceMatchView(
                    long_atom_id=match.long_atom_id,
                    short_atom_id=match.short_atom_id,
                    similarity=match.similarity,
                    classification=match.classification,
                )
                for match in self.matches
            ),
            global_drift=self.global_drift,
            new_interest_drift=self.new_interest_drift,
            drop_interest_drift=self.drop_interest_drift,
            semantic_profile=None,
            similarity_matrix_ref=similarity_matrix_ref,
            memory_version=memory_version,
            updated_at_ms=self.updated_at_ms,
            metadata={
                "cutoff_identity": self.cutoff_identity,
                "derived_artifact_ref": derived_artifact_ref.model_dump(
                    mode="json", exclude_none=False
                ),
                "history_projection_checksum": self.history_projection_checksum,
                "inactive_long_count": len(self.inactive_long_tracks),
                "observed_semantic_count": self.observed_count,
                "pending_count": len(self.pending_tracks),
                "recipe": MEMORY_RECIPE,
                "semantic_artifact_ref": semantic_artifact_ref.model_dump(
                    mode="json", exclude_none=False
                ),
                "similarity_matrix_shape": [
                    len(self.active_long_tracks),
                    len(self.short_atoms),
                ],
                "unprojected_long_count": len(self.unprojected_long_tracks),
            },
        )


def _best_track(
    vector: tuple[float, ...], tracks: list[_MutableTrack]
) -> tuple[_MutableTrack | None, float | None]:
    if not tracks:
        return None, None
    ranked = sorted(
        ((_cosine(track.centroid, vector), track.atom_id, track) for track in tracks),
        key=lambda entry: (-entry[0], entry[1]),
    )
    similarity, _, track = ranked[0]
    return track, similarity


def _freeze_track(track: _MutableTrack, reference_time_ms: int) -> MemoryTrack:
    if not track.supports:
        raise ValueError("memory track cannot be empty")
    support_count = len(track.supports)
    last_seen = track.supports[-1].occurred_at_ms
    age_days = max(reference_time_ms - last_seen, 0) / MILLISECONDS_PER_DAY
    strength = _clip_unit(
        (1.0 - math.exp(-support_count / 3.0)) * (2.0 ** (-age_days / RECENCY_HALF_LIFE_DAYS))
    )
    persistence = _clip_unit(track.distinct_support_times / PERSISTENCE_SATURATION)
    medoid = sorted(
        track.supports,
        key=lambda support: (
            -_cosine(track.centroid, support.vector),
            support.interaction_index,
            support.prototype_id,
        ),
    )[0]
    return MemoryTrack(
        atom_id=track.atom_id,
        centroid=track.centroid,
        supports=tuple(track.supports),
        medoid=medoid,
        strength=strength,
        persistence=persistence,
        inactive=strength < INACTIVE_STRENGTH,
    )


def _weighted_global(
    vectors: tuple[tuple[float, ...], ...], weights: tuple[float, ...]
) -> tuple[float, ...]:
    return _unit(
        tuple(
            math.fsum(
                weight * vector[index] for vector, weight in zip(vectors, weights, strict=True)
            )
            for index in range(len(vectors[0]))
        )
    )


def build_memory_snapshot(
    *,
    user_id: str,
    cutoff_identity: str,
    history_projection_checksum: str,
    observations: tuple[MemoryObservation, ...],
) -> BuiltMemorySnapshot:
    """Replay one exact semantic prefix into a deterministic immutable snapshot."""

    if not user_id or not cutoff_identity or not history_projection_checksum:
        raise ValueError("memory snapshot identity fields must not be empty")
    indexes = tuple(entry.interaction_index for entry in observations)
    if indexes != tuple(sorted(indexes)) or len(indexes) != len(set(indexes)):
        raise ValueError("memory observations require unique chronological interaction indexes")
    timestamps = tuple(entry.occurred_at_ms for entry in observations)
    if timestamps != tuple(sorted(timestamps)):
        raise ValueError("memory observation timestamps must be chronological")
    dimensions = {len(entry.vector) for entry in observations}
    if len(dimensions) > 1:
        raise ValueError("memory observations require one embedding dimension")

    long_tracks: list[_MutableTrack] = []
    pending_tracks: list[_MutableTrack] = []
    assignment_by_index: dict[int, str] = {}
    promotion_count = 0
    for observation in observations:
        matched, similarity = _best_track(observation.vector, long_tracks)
        if matched is not None and similarity is not None and similarity >= MATCH_THRESHOLD:
            matched.reinforce(observation)
            assignment_by_index[observation.interaction_index] = matched.atom_id
            continue
        matched, similarity = _best_track(observation.vector, pending_tracks)
        if matched is None or similarity is None or similarity < MATCH_THRESHOLD:
            atom_id = _stable_id(
                "p3long-",
                {
                    "recipe": MEMORY_RECIPE,
                    "user_id": user_id,
                    "seed_event": observation.event_identity,
                },
            )
            matched = _MutableTrack(atom_id, observation.vector, [observation])
            pending_tracks.append(matched)
        else:
            matched.reinforce(observation)
        assignment_by_index[observation.interaction_index] = matched.atom_id
        if matched.distinct_support_times >= PROMOTION_DISTINCT_TIMES:
            pending_tracks.remove(matched)
            long_tracks.append(matched)
            promotion_count += 1

    reference_time = observations[-1].occurred_at_ms if observations else 0
    frozen_long = tuple(_freeze_track(track, reference_time) for track in long_tracks)
    frozen_pending = tuple(_freeze_track(track, reference_time) for track in pending_tracks)
    active_eligible = tuple(
        sorted(
            (track for track in frozen_long if not track.inactive),
            key=lambda track: (
                -track.strength,
                -track.persistence,
                -track.last_seen_at_ms,
                track.atom_id,
            ),
        )
    )
    active = active_eligible[:MAX_PROJECTED_LONG]
    unprojected = active_eligible[MAX_PROJECTED_LONG:]
    inactive = tuple(
        sorted((track for track in frozen_long if track.inactive), key=lambda x: x.atom_id)
    )
    recent = tuple(reversed(observations[-RECENT_SHORT_COUNT:]))
    support_times_by_track = {
        track.atom_id: track.distinct_support_times for track in (*frozen_long, *frozen_pending)
    }
    short_ids = {
        observation.interaction_index: _stable_id(
            "p3short-",
            {
                "recipe": MEMORY_RECIPE,
                "side": "short",
                "user_id": user_id,
                "event": observation.event_identity,
            },
        )
        for observation in recent
    }
    matrix = tuple(
        tuple(_cosine(track.centroid, observation.vector) for observation in recent)
        for track in active
    )
    stable_long_ids: set[str] = set()
    matches: list[MemoryMatch] = []
    short_states: dict[int, PreferenceState] = {}
    for column, observation in enumerate(recent):
        short_id = short_ids[observation.interaction_index]
        if active:
            best_row = sorted(
                range(len(active)),
                key=lambda row: (-matrix[row][column], active[row].atom_id),
            )[0]
            best_similarity = matrix[best_row][column]
            if best_similarity >= MATCH_THRESHOLD:
                long_id = active[best_row].atom_id
                stable_long_ids.add(long_id)
                short_states[observation.interaction_index] = PreferenceState.STABLE
                matches.append(
                    MemoryMatch(
                        long_atom_id=long_id,
                        short_atom_id=short_id,
                        similarity=best_similarity,
                        classification=PreferenceMatchType.STABLE,
                    )
                )
                continue
            diagnostic = best_similarity
        else:
            diagnostic = None
        short_states[observation.interaction_index] = PreferenceState.EMERGING
        matches.append(
            MemoryMatch(
                long_atom_id=None,
                short_atom_id=short_id,
                similarity=diagnostic,
                classification=PreferenceMatchType.EMERGING,
            )
        )
    for row, track in enumerate(active):
        if track.atom_id not in stable_long_ids:
            diagnostic = max(matrix[row]) if recent else None
            matches.append(
                MemoryMatch(
                    long_atom_id=track.atom_id,
                    short_atom_id=None,
                    similarity=diagnostic,
                    classification=PreferenceMatchType.FADING,
                )
            )

    shorts = tuple(
        ProjectedShort(
            atom_id=short_ids[observation.interaction_index],
            observation=observation,
            assigned_track_id=assignment_by_index[observation.interaction_index],
            strength=2.0 ** (-age_index / 2.0),
            persistence=_clip_unit(
                support_times_by_track[assignment_by_index[observation.interaction_index]]
                / PERSISTENCE_SATURATION
            ),
            state=short_states[observation.interaction_index],
        )
        for age_index, observation in enumerate(recent)
    )

    if not active and not shorts:
        new_drift = drop_drift = global_drift = None
    elif not active:
        new_drift, drop_drift, global_drift = 1.0, None, None
    elif not shorts:
        new_drift, drop_drift, global_drift = None, 1.0, None
    else:
        short_total = math.fsum(short.strength for short in shorts)
        long_total = math.fsum(track.strength for track in active)
        beta = tuple(short.strength / short_total for short in shorts)
        alpha = tuple(track.strength / long_total for track in active)
        new_drift = _clip_unit(
            math.fsum(
                beta[column]
                * (1.0 - _clip_unit(max(matrix[row][column] for row in range(len(active)))))
                for column in range(len(shorts))
            )
        )
        drop_drift = _clip_unit(
            math.fsum(
                alpha[row] * (1.0 - _clip_unit(max(matrix[row]))) for row in range(len(active))
            )
        )
        long_global = _weighted_global(tuple(track.centroid for track in active), alpha)
        short_global = _weighted_global(tuple(short.observation.vector for short in shorts), beta)
        global_drift = _clip_unit(1.0 - _clip_unit(_cosine(long_global, short_global)))

    return BuiltMemorySnapshot(
        user_id=user_id,
        cutoff_identity=cutoff_identity,
        history_projection_checksum=history_projection_checksum,
        updated_at_ms=observations[-1].occurred_at_ms if observations else None,
        active_long_tracks=active,
        unprojected_long_tracks=unprojected,
        inactive_long_tracks=inactive,
        pending_tracks=frozen_pending,
        short_atoms=shorts,
        matches=tuple(matches),
        similarity_matrix=matrix,
        new_interest_drift=new_drift,
        drop_interest_drift=drop_drift,
        global_drift=global_drift,
        promotion_count=promotion_count,
        observed_count=len(observations),
    )
