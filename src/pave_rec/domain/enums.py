"""Stable enum values used across Phase 1 components and artifacts."""

from enum import Enum


class PreferenceState(str, Enum):
    STABLE = "stable"
    EMERGING = "emerging"
    FADING = "fading"
    INACTIVE = "inactive"


class PreferenceMatchType(str, Enum):
    STABLE = "stable"
    EMERGING = "emerging"
    FADING = "fading"


class ObservationStatus(str, Enum):
    UNOBSERVED = "unobserved"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StopReason(str, Enum):
    BUDGET_EXHAUSTED = "budget_exhausted"
    RANKING_SUFFICIENTLY_CERTAIN = "ranking_sufficiently_certain"
    NO_UNOBSERVED_SEGMENTS = "no_unobserved_segments"
    MAX_SEGMENT_VALUE_TOO_LOW = "max_segment_value_too_low"
    COMPONENT_FAILURE = "component_failure"
    SAFETY_LIMIT_REACHED = "safety_limit_reached"
