"""Embedding-provider contract, deterministic fixture, and pinned local BGE-M3 adapter."""

from __future__ import annotations

import hashlib
import importlib.metadata
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ArtifactIntegrityError, ComponentExecutionError, ConfigurationError

from .models import EMBEDDING_RECIPE, BgeM3SnapshotManifest


@dataclass(frozen=True)
class EmbeddingResult:
    vector: tuple[float, ...]
    token_count: int
    was_truncated: bool

    def __post_init__(self) -> None:
        if len(self.vector) != 1024:
            raise ValueError("semantic embedding dimension must be 1024")
        if self.token_count < 0:
            raise ValueError("semantic token count must be non-negative")
        if any(not math.isfinite(value) for value in self.vector):
            raise ValueError("semantic embedding must be finite")
        norm = math.sqrt(math.fsum(value * value for value in self.vector))
        if not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
            raise ValueError("semantic embedding must be explicitly L2-normalized")


class EmbeddingProvider(Protocol):
    @property
    def recipe(self) -> str: ...

    @property
    def snapshot_checksum(self) -> str: ...

    def encode(self, texts: tuple[str, ...]) -> tuple[EmbeddingResult, ...]: ...


def normalize_embedding(
    vector,
    *,
    token_count: int,
    was_truncated: bool,
) -> EmbeddingResult:
    values = tuple(float(value) for value in vector)
    if len(values) != 1024 or any(not math.isfinite(value) for value in values):
        raise ComponentExecutionError("embedding provider returned invalid dense output")
    norm = math.sqrt(math.fsum(value * value for value in values))
    if not math.isfinite(norm) or norm <= 0:
        raise ComponentExecutionError("embedding provider returned a zero/non-finite vector")
    normalized = tuple(value / norm for value in values)
    return EmbeddingResult(
        vector=normalized,
        token_count=token_count,
        was_truncated=was_truncated,
    )


class FixtureEmbeddingProvider:
    """Explicit text-keyed CPU provider; never registered by real config."""

    recipe = EMBEDDING_RECIPE

    def __init__(self, vectors: Mapping[str, tuple[float, ...]]) -> None:
        self._vectors = dict(vectors)
        self._snapshot_checksum = (
            "sha256:"
            + hashlib.sha256(
                canonical_json_bytes(
                    {text: list(vector) for text, vector in sorted(self._vectors.items())},
                    pretty=False,
                )
            ).hexdigest()
        )

    @property
    def snapshot_checksum(self) -> str:
        return self._snapshot_checksum

    def encode(self, texts: tuple[str, ...]) -> tuple[EmbeddingResult, ...]:
        try:
            return tuple(
                normalize_embedding(
                    self._vectors[text],
                    token_count=len(text),
                    was_truncated=False,
                )
                for text in texts
            )
        except KeyError as exc:
            raise ComponentExecutionError(
                "fixture provider received unknown semantic text"
            ) from exc


def verify_model_snapshot(root: Path, manifest: BgeM3SnapshotManifest) -> None:
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise ArtifactIntegrityError("cannot resolve local BGE-M3 snapshot") from exc
    expected = {entry.relative_path for entry in manifest.files}
    try:
        actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    except OSError as exc:
        raise ArtifactIntegrityError("cannot inventory local BGE-M3 snapshot") from exc
    if actual != expected:
        raise ArtifactIntegrityError("local BGE-M3 snapshot inventory mismatch")
    for entry in manifest.files:
        path = root.joinpath(*entry.relative_path.split("/"))
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(resolved_root)
            size_bytes = resolved.stat().st_size
            digest = hashlib.sha256()
            with resolved.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
        except ValueError as exc:
            raise ArtifactIntegrityError(
                f"BGE-M3 snapshot file escaped its root: {entry.relative_path}"
            ) from exc
        except OSError as exc:
            raise ArtifactIntegrityError(
                f"cannot read BGE-M3 snapshot file: {entry.relative_path}"
            ) from exc
        if size_bytes != entry.size_bytes:
            raise ArtifactIntegrityError(f"BGE-M3 snapshot size mismatch: {entry.relative_path}")
        checksum = f"sha256:{digest.hexdigest()}"
        if checksum != entry.checksum:
            raise ArtifactIntegrityError(
                f"BGE-M3 snapshot checksum mismatch: {entry.relative_path}"
            )


class BgeM3EmbeddingProvider:
    recipe = EMBEDDING_RECIPE

    def __init__(
        self,
        *,
        snapshot_root: Path,
        snapshot_manifest: BgeM3SnapshotManifest,
        snapshot_checksum: str,
        device: str,
        batch_size: int,
    ) -> None:
        if batch_size <= 0:
            raise ConfigurationError("BGE-M3 batch size must be positive")
        verify_model_snapshot(snapshot_root, snapshot_manifest)
        try:
            installed = importlib.metadata.version("FlagEmbedding")
        except importlib.metadata.PackageNotFoundError as exc:
            raise ConfigurationError("FlagEmbedding 1.4.0 is required for BGE-M3") from exc
        if installed != "1.4.0":
            raise ConfigurationError("FlagEmbedding version must be exactly 1.4.0")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(
                str(snapshot_root),
                use_fp16=False,
                device=device,
            )
        except Exception as exc:
            raise ConfigurationError("cannot initialize pinned local BGE-M3 provider") from exc
        self._batch_size = batch_size
        self._snapshot_checksum = snapshot_checksum

    @property
    def snapshot_checksum(self) -> str:
        return self._snapshot_checksum

    def encode(self, texts: tuple[str, ...]) -> tuple[EmbeddingResult, ...]:
        if not texts:
            return ()
        try:
            token_counts = tuple(
                len(
                    self._model.tokenizer(
                        text,
                        add_special_tokens=True,
                        truncation=False,
                    )["input_ids"]
                )
                for text in texts
            )
            output = self._model.encode(
                list(texts),
                batch_size=self._batch_size,
                max_length=1024,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            vectors = output["dense_vecs"]
        except Exception as exc:
            raise ComponentExecutionError("pinned BGE-M3 dense encoding failed") from exc
        if len(vectors) != len(texts):
            raise ComponentExecutionError("BGE-M3 output coverage mismatch")
        return tuple(
            normalize_embedding(
                vector,
                token_count=token_count,
                was_truncated=token_count > 1024,
            )
            for vector, token_count in zip(vectors, token_counts, strict=True)
        )
