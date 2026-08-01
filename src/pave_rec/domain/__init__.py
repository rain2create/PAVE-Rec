"""Stable public domain objects for PAVE-Rec."""

from .decisions import (
    CandidateSegmentRef,
    InformationNeed,
    SegmentValue,
    SegmentValueInput,
    StopDecision,
)
from .enums import ObservationStatus, PreferenceMatchType, PreferenceState, StopReason
from .evidence import (
    Evidence,
    EvidenceState,
    ItemEvidenceState,
    ItemObservationState,
    ObservationState,
    SegmentObservationState,
)
from .interface_types import (
    AgentRunRequest,
    CandidateScore,
    ComponentDescriptor,
    ItemFeatureRef,
    ItemSegmentCatalog,
    PerceptionRequest,
    PerceptionResult,
    RecommendationStateBuildRequest,
    ScoreUpdateRequest,
)
from .memory import PreferenceAtomView, PreferenceMatchView, UserMemoryView
from .ranking import InitialRankedCandidate, InitialRankingOutput
from .refs import ResourceRef
from .segments import SegmentMeta, SegmentProxyRef
from .state import CandidateState, RankingUncertainty, RecommendationState
from .trace import AgentRunResult, AgentStepTrace

__all__ = [
    "AgentRunRequest",
    "AgentRunResult",
    "AgentStepTrace",
    "CandidateScore",
    "CandidateSegmentRef",
    "CandidateState",
    "ComponentDescriptor",
    "Evidence",
    "EvidenceState",
    "InformationNeed",
    "InitialRankedCandidate",
    "InitialRankingOutput",
    "ItemEvidenceState",
    "ItemFeatureRef",
    "ItemObservationState",
    "ItemSegmentCatalog",
    "ObservationState",
    "ObservationStatus",
    "PerceptionRequest",
    "PerceptionResult",
    "PreferenceAtomView",
    "PreferenceMatchType",
    "PreferenceMatchView",
    "PreferenceState",
    "RankingUncertainty",
    "RecommendationState",
    "RecommendationStateBuildRequest",
    "ResourceRef",
    "ScoreUpdateRequest",
    "SegmentMeta",
    "SegmentObservationState",
    "SegmentProxyRef",
    "SegmentValue",
    "SegmentValueInput",
    "StopDecision",
    "StopReason",
    "UserMemoryView",
]
