"""Explicit offline-preparation helper for the exact BGE-M3 model snapshot."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ArtifactIntegrityError, ArtifactPublicationError

from .models import BgeM3SnapshotManifest, ModelSnapshotFile

BGE_M3_MODEL_ID = "BAAI/bge-m3"
BGE_M3_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
BGE_M3_RUNTIME_FILES = (
    "1_Pooling/*",
    "colbert_linear.pt",
    "config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "pytorch_model.bin",
    "sentence_bert_config.json",
    "sentencepiece.bpe.model",
    "sparse_linear.pt",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
BGE_M3_RUNTIME_INVENTORY = frozenset(
    {
        "1_Pooling/config.json",
        "colbert_linear.pt",
        "config.json",
        "config_sentence_transformers.json",
        "modules.json",
        "pytorch_model.bin",
        "sentence_bert_config.json",
        "sentencepiece.bpe.model",
        "sparse_linear.pt",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    }
)


@dataclass(frozen=True)
class ModelFetchResult:
    outcome: str
    model_directory_key: str
    manifest_filename: str
    manifest_checksum: str
    file_count: int


def _streaming_file_digest(path: Path) -> tuple[int, str]:
    """Return the stable size/SHA-256 pair without loading model weights into RAM."""

    digest = hashlib.sha256()
    size_bytes = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                size_bytes += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise ArtifactIntegrityError("cannot hash downloaded BGE-M3 snapshot") from exc
    return size_bytes, f"sha256:{digest.hexdigest()}"


def _snapshot_manifest(snapshot_root: Path) -> BgeM3SnapshotManifest:
    files = []
    for path in sorted(
        (path for path in snapshot_root.rglob("*") if path.is_file()),
        key=lambda value: value.relative_to(snapshot_root).as_posix(),
    ):
        size_bytes, checksum = _streaming_file_digest(path)
        files.append(
            ModelSnapshotFile(
                relative_path=path.relative_to(snapshot_root).as_posix(),
                size_bytes=size_bytes,
                checksum=checksum,
            )
        )
    return BgeM3SnapshotManifest(
        schema_version="bge-m3-model-snapshot-v1",
        model_id=BGE_M3_MODEL_ID,
        revision=BGE_M3_REVISION,
        files=tuple(files),
    )


def fetch_bge_m3_snapshot(
    *,
    cache_root: str | Path,
    manifest_root: str | Path,
) -> ModelFetchResult:
    """Download only the pinned inference files, then publish their exact inventory."""

    cache = Path(cache_root).resolve(strict=True)
    manifests = Path(manifest_root).resolve(strict=True)
    candidate = cache / "models--BAAI--bge-m3" / "snapshots" / BGE_M3_REVISION
    local_inventory = (
        {path.relative_to(candidate).as_posix() for path in candidate.rglob("*") if path.is_file()}
        if candidate.is_dir()
        else set()
    )
    if local_inventory == BGE_M3_RUNTIME_INVENTORY:
        downloaded = candidate.resolve(strict=True)
    else:
        # The Hub's optional Xet transport has produced non-resumable CAS decode failures on
        # Windows. Plain HTTP still verifies the pinned revision and resumes its cache.
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise ArtifactPublicationError(
                "huggingface_hub is required for explicit model fetch"
            ) from exc
        try:
            downloaded = Path(
                snapshot_download(
                    repo_id=BGE_M3_MODEL_ID,
                    revision=BGE_M3_REVISION,
                    cache_dir=cache,
                    allow_patterns=list(BGE_M3_RUNTIME_FILES),
                )
            ).resolve(strict=True)
        except Exception as exc:
            raise ArtifactPublicationError("cannot fetch exact BGE-M3 snapshot") from exc
    try:
        directory_key = downloaded.relative_to(cache).as_posix()
    except ValueError as exc:
        raise ArtifactIntegrityError("downloaded BGE-M3 snapshot escaped cache root") from exc
    if downloaded.name != BGE_M3_REVISION:
        raise ArtifactIntegrityError("BGE-M3 snapshot resolver returned a different revision")
    manifest = _snapshot_manifest(downloaded)
    payload = canonical_json_bytes(manifest, pretty=True)
    checksum = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    filename = f"bge-m3-{BGE_M3_REVISION}-snapshot.json"
    destination = manifests / filename
    if destination.exists():
        try:
            actual = destination.read_bytes()
        except OSError as exc:
            raise ArtifactIntegrityError("cannot verify existing BGE-M3 snapshot manifest") from exc
        if actual != payload:
            raise ArtifactIntegrityError("existing BGE-M3 snapshot manifest conflicts")
        outcome = "reused"
    else:
        try:
            with destination.open("xb") as handle:
                handle.write(payload)
                handle.flush()
        except OSError as exc:
            raise ArtifactPublicationError("cannot publish BGE-M3 snapshot manifest") from exc
        outcome = "created"
    return ModelFetchResult(
        outcome=outcome,
        model_directory_key=directory_key,
        manifest_filename=filename,
        manifest_checksum=checksum,
        file_count=len(manifest.files),
    )
