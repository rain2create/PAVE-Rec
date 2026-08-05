"""Phase 3 full-catalog evaluation protocols."""

from .artifact import (
    EvaluationArtifactManifest,
    EvaluationArtifactPlan,
    EvaluationExecutionRecipe,
    EvaluationPublicationResult,
    FilesystemEvaluationArtifactPublisher,
    LoadedEvaluationArtifact,
    build_evaluation_artifact_plan,
    load_evaluation_artifact,
)
from .config import Phase3EvaluationConfig, load_phase3_evaluation_config
from .evaluator import (
    MostPopInitialRanker,
    RankingEvaluation,
    build_mostpop_ranker,
    evaluate_full_catalog,
)
from .lifecycle import EvaluationResult, evaluate_from_config
from .models import MetricAggregate, RankingEvaluationAggregate, TargetRankingOutcome

__all__ = [
    "EvaluationArtifactManifest",
    "EvaluationArtifactPlan",
    "EvaluationExecutionRecipe",
    "EvaluationPublicationResult",
    "EvaluationResult",
    "FilesystemEvaluationArtifactPublisher",
    "LoadedEvaluationArtifact",
    "MetricAggregate",
    "MostPopInitialRanker",
    "Phase3EvaluationConfig",
    "RankingEvaluation",
    "RankingEvaluationAggregate",
    "TargetRankingOutcome",
    "build_evaluation_artifact_plan",
    "build_mostpop_ranker",
    "evaluate_full_catalog",
    "evaluate_from_config",
    "load_evaluation_artifact",
    "load_phase3_evaluation_config",
]
