"""Versioned Phase 3 item-semantic prototypes and embedding artifacts."""

from .artifact import (
    FilesystemItemSemanticPublisher,
    ItemSemanticArtifactPlan,
    LoadedItemSemantics,
    SemanticPublicationResult,
    build_item_semantic_artifact_plan,
    load_item_semantics,
    load_prototype_embedding,
)
from .config import (
    BgeM3ProviderConfig,
    Phase3ItemSemanticsConfig,
    SemanticOperationalConfig,
    load_phase3_item_semantics_config,
)
from .fetch import ModelFetchResult, fetch_bge_m3_snapshot
from .lifecycle import ItemSemanticsResult, build_item_semantics_from_config
from .models import (
    EMBEDDING_RECIPE,
    SEMANTIC_BUILDER_VERSION,
    SEMANTIC_TEXT_RECIPE,
    BgeM3SnapshotManifest,
    EmbeddingIndexEntry,
    ItemSemanticArtifactManifest,
    ItemSemanticPrototype,
    ModelSnapshotFile,
)
from .provider import (
    BgeM3EmbeddingProvider,
    EmbeddingProvider,
    EmbeddingResult,
    FixtureEmbeddingProvider,
    normalize_embedding,
    verify_model_snapshot,
)
from .text import SemanticTextSpec, build_semantic_text

__all__ = [
    "EMBEDDING_RECIPE",
    "SEMANTIC_BUILDER_VERSION",
    "SEMANTIC_TEXT_RECIPE",
    "BgeM3EmbeddingProvider",
    "BgeM3ProviderConfig",
    "BgeM3SnapshotManifest",
    "EmbeddingIndexEntry",
    "EmbeddingProvider",
    "EmbeddingResult",
    "FilesystemItemSemanticPublisher",
    "FixtureEmbeddingProvider",
    "ItemSemanticArtifactManifest",
    "ItemSemanticArtifactPlan",
    "ItemSemanticPrototype",
    "ItemSemanticsResult",
    "LoadedItemSemantics",
    "ModelSnapshotFile",
    "ModelFetchResult",
    "Phase3ItemSemanticsConfig",
    "SemanticOperationalConfig",
    "SemanticPublicationResult",
    "SemanticTextSpec",
    "build_item_semantic_artifact_plan",
    "build_item_semantics_from_config",
    "build_semantic_text",
    "fetch_bge_m3_snapshot",
    "load_item_semantics",
    "load_phase3_item_semantics_config",
    "load_prototype_embedding",
    "normalize_embedding",
    "verify_model_snapshot",
]
