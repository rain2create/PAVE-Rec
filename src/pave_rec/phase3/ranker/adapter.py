"""Exact-checkpoint SASRec adapter for the unchanged InitialRanker protocol."""

from __future__ import annotations

import io

import numpy as np
import torch

from pave_rec.domain import (
    ComponentDescriptor,
    InitialRankedCandidate,
    InitialRankingOutput,
    ResourceRef,
)
from pave_rec.domain.base import require_non_empty, require_unique
from pave_rec.errors import ArtifactIntegrityError, ComponentExecutionError, ContractError
from pave_rec.phase3.derived import DerivedDatasetManifest, TrainVocabulary
from pave_rec.preprocessing.paths import FilesystemPathResolver

from .checkpoint import load_sasrec_checkpoint_manifest, load_sasrec_checkpoint_payloads
from .model import SasrecModel


def _device(value: str) -> torch.device:
    try:
        device = torch.device(value)
    except (RuntimeError, ValueError) as exc:
        raise ContractError("invalid explicit SASRec device") from exc
    if device.type == "cuda":
        if device.index is None:
            raise ContractError("SASRec CUDA device requires an explicit index")
        if not torch.cuda.is_available() or device.index >= torch.cuda.device_count():
            raise ContractError("configured SASRec CUDA device is unavailable")
    elif device.type != "cpu":
        raise ContractError("SASRec device must be cpu or cuda:<index>")
    return device


class SasrecInitialRanker:
    descriptor = ComponentDescriptor(
        role="initial_ranker",
        implementation="SASRecInitialRanker",
        version="sasrec-pytorch-v1",
    )

    def __init__(
        self,
        *,
        model: SasrecModel,
        vocabulary: TrainVocabulary,
        checkpoint_id: str,
        device: str,
        candidate_chunk_size: int,
    ) -> None:
        if candidate_chunk_size <= 0:
            raise ContractError("candidate_chunk_size must be positive")
        self._device = _device(device)
        self._model = model.to(self._device)
        self._model.eval()
        self._item_ids = tuple(entry.item_id for entry in vocabulary.entries)
        self._model_indices = tuple(entry.model_index for entry in vocabulary.entries)
        self._vocabulary = {entry.item_id: entry.model_index for entry in vocabulary.entries}
        self._item_positions = {
            item_id: position for position, item_id in enumerate(self._item_ids)
        }
        lexical_order = sorted(range(len(self._item_ids)), key=self._item_ids.__getitem__)
        self._lexical_ranks = np.empty(len(self._item_ids), dtype=np.int64)
        self._lexical_ranks[lexical_order] = np.arange(len(self._item_ids), dtype=np.int64)
        self._checkpoint_id = require_non_empty(checkpoint_id, "checkpoint_id")
        self._candidate_chunk_size = candidate_chunk_size

    def _score_tensor(
        self,
        user_id: str,
        sequence: tuple[str, ...],
        candidate_ids: tuple[str, ...],
    ) -> tuple[torch.Tensor, dict[str, object]]:
        require_non_empty(user_id, "user_id")
        if not candidate_ids:
            raise ContractError("candidate_ids must not be empty")
        try:
            require_unique(candidate_ids, "candidate_ids")
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
        unknown_candidates = tuple(
            item_id for item_id in candidate_ids if item_id not in self._vocabulary
        )
        if unknown_candidates:
            raise ContractError("candidate_ids contain OOV or special items")
        known_history = tuple(
            self._vocabulary[item_id] for item_id in sequence if item_id in self._vocabulary
        )
        if not known_history:
            raise ContractError("SASRec history contains no known train-vocabulary item")
        used_history = known_history[-self._model.config.max_history_length :]
        padded_history = (self._model.config.pad_index,) * (
            self._model.config.max_history_length - len(used_history)
        ) + used_history
        try:
            with torch.inference_mode():
                history_tensor = torch.tensor(
                    (padded_history,),
                    dtype=torch.long,
                    device=self._device,
                )
                feature = self._model.encode(history_tensor)
                score_chunks = []
                for start in range(0, len(candidate_ids), self._candidate_chunk_size):
                    chunk = candidate_ids[start : start + self._candidate_chunk_size]
                    indices = torch.tensor(
                        tuple(self._vocabulary[item_id] for item_id in chunk),
                        dtype=torch.long,
                        device=self._device,
                    )
                    logits = self._model.score_items(feature, indices).squeeze(0)
                    if not bool(torch.isfinite(logits).all().item()):
                        raise ComponentExecutionError("SASRec produced a non-finite score")
                    score_chunks.append(logits)
        except ComponentExecutionError:
            raise
        except (RuntimeError, ValueError) as exc:
            raise ComponentExecutionError("SASRec candidate scoring failed") from exc
        return torch.cat(score_chunks), {
            "ranker_type": "sasrec",
            "ranker_version": "sasrec-pytorch-v1",
            "checkpoint_id": self._checkpoint_id,
            "score_representation": "raw_dot_product_logit",
            "score_calibrated": False,
            "history_input_count": len(sequence),
            "history_oov_dropped_count": len(sequence) - len(known_history),
            "history_known_count": len(known_history),
            "history_used_count": len(used_history),
        }

    def score(
        self,
        user_id: str,
        sequence: tuple[str, ...],
        candidate_ids: tuple[str, ...],
    ) -> InitialRankingOutput:
        score_tensor, metadata = self._score_tensor(user_id, sequence, candidate_ids)
        numeric_scores = tuple(float(value) for value in score_tensor.detach().cpu().tolist())
        scores = dict(zip(candidate_ids, numeric_scores, strict=True))
        ordered = sorted(candidate_ids, key=lambda item_id: (-scores[item_id], item_id))
        return InitialRankingOutput(
            candidates=tuple(
                InitialRankedCandidate(
                    item_id=item_id,
                    score=scores[item_id],
                    rank=rank,
                )
                for rank, item_id in enumerate(ordered, start=1)
            ),
            user_sequence_feature_ref=None,
            metadata=metadata,
        )

    def rank_target(
        self,
        user_id: str,
        sequence: tuple[str, ...],
        candidate_ids: tuple[str, ...],
        target_item_id: str,
    ) -> tuple[int, tuple[str, ...]]:
        try:
            target_index = candidate_ids.index(target_item_id)
        except ValueError as exc:
            raise ContractError("SASRec target is outside the candidate set") from exc
        scores, _ = self._score_tensor(user_id, sequence, candidate_ids)
        target_score = scores[target_index]
        higher_count = int(torch.count_nonzero(scores > target_score).item())
        tied_indices = (
            torch.nonzero(scores == target_score, as_tuple=False).flatten().cpu().tolist()
        )
        lexical_tie_count = sum(candidate_ids[index] < target_item_id for index in tied_indices)
        target_rank = higher_count + lexical_tie_count + 1

        top_count = min(100, len(candidate_ids))
        threshold = torch.min(torch.topk(scores, top_count, sorted=False).values)
        selected_indices = (
            torch.nonzero(scores >= threshold, as_tuple=False).flatten().cpu().tolist()
        )
        selected_scores = scores[selected_indices].detach().cpu().tolist()
        ordered_top = sorted(
            zip(selected_indices, selected_scores, strict=True),
            key=lambda entry: (-float(entry[1]), candidate_ids[entry[0]]),
        )[:top_count]
        return target_rank, tuple(candidate_ids[index] for index, _ in ordered_top)

    def rank_targets(
        self,
        requests: tuple[tuple[str, tuple[str, ...], tuple[str, ...], str], ...],
        *,
        user_batch_size: int,
    ) -> tuple[tuple[int, tuple[str, ...]], ...]:
        if user_batch_size <= 0:
            raise ContractError("SASRec evaluation batch size must be positive")
        if not requests:
            return ()
        results = []
        vocabulary_size = len(self._item_ids)
        for start in range(0, len(requests), user_batch_size):
            batch = requests[start : start + user_batch_size]
            padded_histories = []
            excluded_positions = []
            target_positions = []
            candidate_counts = []
            for user_id, sequence, candidate_ids, target_item_id in batch:
                require_non_empty(user_id, "user_id")
                if not candidate_ids:
                    raise ContractError("candidate_ids must not be empty")
                try:
                    require_unique(candidate_ids, "candidate_ids")
                except ValueError as exc:
                    raise ContractError(str(exc)) from exc
                candidate_set = set(candidate_ids)
                if any(item_id not in self._vocabulary for item_id in candidate_set):
                    raise ContractError("candidate_ids contain OOV or special items")
                if target_item_id not in candidate_set:
                    raise ContractError("SASRec target is outside the candidate set")
                known_history = tuple(
                    self._vocabulary[item_id] for item_id in sequence if item_id in self._vocabulary
                )
                if not known_history:
                    raise ContractError("SASRec history contains no known train-vocabulary item")
                used_history = known_history[-self._model.config.max_history_length :]
                padded_histories.append(
                    (self._model.config.pad_index,)
                    * (self._model.config.max_history_length - len(used_history))
                    + used_history
                )
                excluded_ids = {
                    item_id
                    for item_id in sequence
                    if item_id in self._vocabulary and item_id != target_item_id
                }
                if len(candidate_set) != vocabulary_size - len(excluded_ids) or any(
                    item_id in candidate_set for item_id in excluded_ids
                ):
                    raise ContractError("SASRec evaluation candidates violate the seen-item mask")
                excluded_positions.append(
                    tuple(self._item_positions[item_id] for item_id in excluded_ids)
                )
                target_positions.append(self._item_positions[target_item_id])
                candidate_counts.append(len(candidate_set))
            try:
                with torch.inference_mode():
                    history_tensor = torch.tensor(
                        padded_histories,
                        dtype=torch.long,
                        device=self._device,
                    )
                    features = self._model.encode(history_tensor)
                    score_chunks = []
                    for item_start in range(0, vocabulary_size, self._candidate_chunk_size):
                        item_indices = torch.tensor(
                            self._model_indices[
                                item_start : item_start + self._candidate_chunk_size
                            ],
                            dtype=torch.long,
                            device=self._device,
                        )
                        score_chunks.append(self._model.score_items(features, item_indices))
                    scores = torch.cat(score_chunks, dim=1)
                    if not bool(torch.isfinite(scores).all().item()):
                        raise ComponentExecutionError("SASRec produced a non-finite score")
                    for row_index, positions in enumerate(excluded_positions):
                        if positions:
                            scores[row_index, list(positions)] = -torch.inf
                    score_matrix = scores.cpu().numpy()
            except ComponentExecutionError:
                raise
            except (RuntimeError, ValueError) as exc:
                raise ComponentExecutionError("SASRec batched evaluation failed") from exc

            for row, target_position, candidate_count in zip(
                score_matrix,
                target_positions,
                candidate_counts,
                strict=True,
            ):
                target_score = row[target_position]
                target_rank = (
                    int(np.count_nonzero(row > target_score))
                    + int(
                        np.count_nonzero(
                            (row == target_score)
                            & (self._lexical_ranks < self._lexical_ranks[target_position])
                        )
                    )
                    + 1
                )
                top_count = min(100, candidate_count)
                threshold = np.partition(row, len(row) - top_count)[len(row) - top_count]
                above = np.flatnonzero(row > threshold)
                tied = np.flatnonzero(row == threshold)
                remaining = top_count - len(above)
                tied = tied[np.argsort(self._lexical_ranks[tied], kind="stable")][:remaining]
                selected = np.concatenate((above, tied))
                order = np.lexsort((self._lexical_ranks[selected], -row[selected]))
                top_100 = tuple(self._item_ids[int(index)] for index in selected[order])
                results.append((target_rank, top_100))
        return tuple(results)


def load_sasrec_initial_ranker(
    *,
    resolver: FilesystemPathResolver,
    manifest_ref: ResourceRef,
    expected_derived_manifest_ref: ResourceRef,
    derived_manifest: DerivedDatasetManifest,
    vocabulary: TrainVocabulary,
    device: str,
    candidate_chunk_size: int,
) -> SasrecInitialRanker:
    manifest = load_sasrec_checkpoint_manifest(resolver, manifest_ref)
    if manifest.checkpoint_kind != "best":
        raise ArtifactIntegrityError("Agent/evaluation requires an exact best checkpoint")
    if (
        manifest.derived_manifest_ref != expected_derived_manifest_ref
        or manifest.source_data_version != derived_manifest.source_data_version
        or manifest.source_release_ref != derived_manifest.source_release_ref
    ):
        raise ArtifactIntegrityError("SASRec checkpoint derived/source identity mismatch")
    vocabulary_ref = next(
        (ref for ref in derived_manifest.payload_refs if ref.key.endswith("/vocabulary.json")),
        None,
    )
    if (
        vocabulary_ref is None
        or manifest.vocabulary_ref != vocabulary_ref
        or manifest.vocabulary_item_count != len(vocabulary.entries)
        or manifest.vocabulary_pad_index != vocabulary.pad_index
    ):
        raise ArtifactIntegrityError("SASRec checkpoint vocabulary identity mismatch")
    payloads = load_sasrec_checkpoint_payloads(resolver, manifest_ref, manifest)
    try:
        state = torch.load(
            io.BytesIO(payloads["model_state"]),
            map_location="cpu",
            weights_only=True,
        )
        if not isinstance(state, dict) or not all(isinstance(key, str) for key in state):
            raise ArtifactIntegrityError("SASRec model state must be a tensor state dictionary")
        model = SasrecModel(
            vocabulary_size=len(vocabulary.entries),
            config=manifest.model_recipe,
        )
        model.load_state_dict(state, strict=True)
        model.zero_pad_embedding()
    except ArtifactIntegrityError:
        raise
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        raise ArtifactIntegrityError("cannot load compatible SASRec model state") from exc
    return SasrecInitialRanker(
        model=model,
        vocabulary=vocabulary,
        checkpoint_id=manifest.checkpoint_id,
        device=device,
        candidate_chunk_size=candidate_chunk_size,
    )
