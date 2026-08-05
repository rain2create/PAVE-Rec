"""Tsinghua ShortVideo sampled-release source adapter."""

from .adapter import (
    AdaptedTsinghuaSource,
    adapt_tsinghua_snapshot,
    classify_tsinghua_interaction,
)
from .config import (
    TsinghuaSourceAdapterConfig,
    load_tsinghua_source_adapter_config,
)
from .lifecycle import TsinghuaSourceAdapterResult, adapt_tsinghua_from_config
from .models import (
    POSITIVE_RECIPE,
    TSINGHUA_ADAPTER_VERSION,
    TSINGHUA_SNAPSHOT_SCHEMA,
    SnapshotArtifactIdentity,
    TsinghuaAdapterAudit,
    TsinghuaSnapshotIdentity,
)
from .source_bundle import (
    FilesystemTsinghuaSourcePublisher,
    SourceBundlePublicationResult,
    TsinghuaSourceBundlePlan,
    build_tsinghua_source_bundle,
)

__all__ = [
    "POSITIVE_RECIPE",
    "TSINGHUA_ADAPTER_VERSION",
    "TSINGHUA_SNAPSHOT_SCHEMA",
    "AdaptedTsinghuaSource",
    "FilesystemTsinghuaSourcePublisher",
    "SourceBundlePublicationResult",
    "SnapshotArtifactIdentity",
    "TsinghuaAdapterAudit",
    "TsinghuaSourceAdapterConfig",
    "TsinghuaSourceAdapterResult",
    "TsinghuaSnapshotIdentity",
    "TsinghuaSourceBundlePlan",
    "adapt_tsinghua_snapshot",
    "adapt_tsinghua_from_config",
    "classify_tsinghua_interaction",
    "build_tsinghua_source_bundle",
    "load_tsinghua_source_adapter_config",
]
