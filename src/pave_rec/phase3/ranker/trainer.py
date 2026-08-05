"""Deterministic model-specific trainer for ``sasrec-pytorch-v1``."""

from __future__ import annotations

import hashlib
import io
import math
import os
import platform
from dataclasses import dataclass
from pathlib import Path

import torch

from pave_rec.domain import ResourceRef
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ArtifactIntegrityError, ComponentExecutionError, ContractError
from pave_rec.phase3.derived import DerivedDataset, TrainVocabulary, load_derived_dataset
from pave_rec.preprocessing.paths import FilesystemPathResolver
from pave_rec.runner import collect_git_metadata

from .checkpoint import (
    FilesystemSasrecCheckpointPublisher,
    build_sasrec_checkpoint_plan,
    load_sasrec_checkpoint_manifest,
    load_sasrec_checkpoint_payloads,
)
from .config import Phase3SasrecTrainingConfig, load_phase3_sasrec_training_config
from .model import SasrecModel
from .sampler import deterministic_uniform_negative, epoch_sample_order


@dataclass(frozen=True)
class SasrecTrainingResult:
    execution_id: str
    best_outcome: str
    last_outcome: str
    best_manifest_ref: ResourceRef
    last_manifest_ref: ResourceRef
    best_epoch: int
    completed_epoch: int
    best_validation_ndcg_at_10: float
    global_step: int


def _execution_id(config_path: Path, config: Phase3SasrecTrainingConfig) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "config_path": config_path.as_posix(),
                "derived_manifest_ref": config.derived_manifest_ref.model_dump(
                    mode="json", exclude_none=False
                ),
                "model": config.model.model_dump(mode="json", exclude_none=False),
                "training": config.training.model_dump(mode="json", exclude_none=False),
                "resume_checkpoint_ref": (
                    config.resume_checkpoint_ref.model_dump(mode="json", exclude_none=False)
                    if config.resume_checkpoint_ref is not None
                    else None
                ),
            },
            pretty=False,
        )
    ).hexdigest()[:16]
    return f"p3-train-{digest}"


def _explicit_device(value: str) -> torch.device:
    try:
        device = torch.device(value)
    except (RuntimeError, ValueError) as exc:
        raise ContractError("invalid explicit SASRec training device") from exc
    if device.type == "cuda":
        if device.index is None:
            raise ContractError("SASRec training CUDA device requires an explicit index")
        if not torch.cuda.is_available() or device.index >= torch.cuda.device_count():
            raise ContractError("configured SASRec training CUDA device is unavailable")
    elif device.type != "cpu":
        raise ContractError("SASRec training device must be cpu or cuda:<index>")
    return device


def _serialize_torch(value: object) -> bytes:
    buffer = io.BytesIO()
    torch.save(value, buffer)
    payload = buffer.getvalue()
    if not payload:
        raise ComponentExecutionError("Torch serialized an empty checkpoint payload")
    return payload


def _cpu_state_dict(model: SasrecModel) -> dict[str, torch.Tensor]:
    return {
        name: tensor.detach().to(device="cpu", dtype=tensor.dtype).clone()
        for name, tensor in model.state_dict().items()
    }


def _vocabulary_ref(derived_manifest) -> ResourceRef:
    matches = tuple(
        ref for ref in derived_manifest.payload_refs if ref.key.endswith("/vocabulary.json")
    )
    if len(matches) != 1:
        raise ArtifactIntegrityError("derived manifest requires exactly one vocabulary ref")
    return matches[0]


def _index_maps(vocabulary: TrainVocabulary) -> tuple[dict[str, int], tuple[str, ...]]:
    item_to_index = {entry.item_id: entry.model_index for entry in vocabulary.entries}
    index_to_item = tuple(entry.item_id for entry in vocabulary.entries)
    return item_to_index, index_to_item


def _left_padded_history(
    item_ids: tuple[str, ...],
    *,
    item_to_index: dict[str, int],
    max_length: int,
) -> tuple[int, ...]:
    try:
        known = tuple(item_to_index[item_id] for item_id in item_ids)
    except KeyError as exc:
        raise ArtifactIntegrityError("training history contains a non-train item") from exc
    if not known:
        raise ArtifactIntegrityError("training history must not be empty")
    used = known[-max_length:]
    return (0,) * (max_length - len(used)) + used


def _validation_ndcg_at_10(
    *,
    model: SasrecModel,
    dataset: DerivedDataset,
    item_to_index: dict[str, int],
    index_to_item: tuple[str, ...],
    device: torch.device,
    user_batch_size: int,
) -> float:
    warm = tuple(
        split.validation_target
        for split in dataset.user_splits
        if split.validation_target.in_train_vocabulary
    )
    if not warm:
        raise ArtifactIntegrityError("warm validation subset must not be empty")
    lexical_items = sorted(index_to_item)
    lexical_position = {item_id: position for position, item_id in enumerate(lexical_items)}
    lexical_tensor = torch.tensor(
        tuple(lexical_position[item_id] for item_id in index_to_item),
        dtype=torch.long,
        device=device,
    )
    values: list[float] = []
    was_training = model.training
    model.eval()
    try:
        with torch.inference_mode():
            for start in range(0, len(warm), user_batch_size):
                batch = warm[start : start + user_batch_size]
                histories = torch.tensor(
                    tuple(
                        _left_padded_history(
                            tuple(event.item_id for event in target.history),
                            item_to_index=item_to_index,
                            max_length=model.config.max_history_length,
                        )
                        for target in batch
                    ),
                    dtype=torch.long,
                    device=device,
                )
                features = model.encode(histories)
                scores = features @ model.item_embedding.weight[1:].transpose(0, 1)
                target_indices = torch.tensor(
                    tuple(item_to_index[target.target.item_id] for target in batch),
                    dtype=torch.long,
                    device=device,
                )
                for row, target in enumerate(batch):
                    target_index = int(target_indices[row].item())
                    seen = {
                        item_to_index[event.item_id]
                        for event in target.history
                        if event.item_id in item_to_index
                    }
                    seen.discard(target_index)
                    if seen:
                        seen_tensor = torch.tensor(
                            tuple(sorted(index - 1 for index in seen)),
                            dtype=torch.long,
                            device=device,
                        )
                        scores[row, seen_tensor] = -torch.inf
                    target_score = scores[row, target_index - 1]
                    greater = scores[row] > target_score
                    tied_before = scores[row].eq(target_score) & lexical_tensor.lt(
                        lexical_position[target.target.item_id]
                    )
                    rank = 1 + int(greater.sum().item()) + int(tied_before.sum().item())
                    values.append(1.0 / math.log2(rank + 1) if rank <= 10 else 0.0)
    finally:
        model.train(was_training)
    return float(sum(values) / len(values))


def _operational_provenance(
    *,
    project_root: Path,
    device: torch.device,
    config: Phase3SasrecTrainingConfig,
) -> dict[str, object]:
    git = collect_git_metadata(project_root)
    device_name = (
        torch.cuda.get_device_name(device)
        if device.type == "cuda"
        else platform.processor() or "cpu"
    )
    return {
        "python_version": platform.python_version(),
        "torch_version": str(torch.__version__),
        "cuda_runtime_version": torch.version.cuda,
        "device": str(device),
        "device_name": device_name,
        "git_commit": git.commit,
        "git_dirty": git.dirty,
        "loader_workers": config.operational.loader_workers,
        "candidate_chunk_size": config.operational.candidate_chunk_size,
        "evaluation_user_batch_size": config.operational.evaluation_user_batch_size,
        "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
    }


def _restore_resume(
    *,
    resolver: FilesystemPathResolver,
    config: Phase3SasrecTrainingConfig,
    model: SasrecModel,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> tuple[int, int, int, int, float, int, ResourceRef, float]:
    assert config.resume_checkpoint_ref is not None
    manifest = load_sasrec_checkpoint_manifest(resolver, config.resume_checkpoint_ref)
    if manifest.checkpoint_kind != "last":
        raise ArtifactIntegrityError("resume requires an exact last checkpoint")
    if (
        manifest.derived_manifest_ref != config.derived_manifest_ref
        or manifest.model_recipe != config.model
        or manifest.training_recipe != config.training
        or manifest.selected_best_manifest_ref is None
    ):
        raise ArtifactIntegrityError("resume checkpoint is incompatible with training config")
    payloads = load_sasrec_checkpoint_payloads(
        resolver,
        config.resume_checkpoint_ref,
        manifest,
    )
    try:
        model_state = torch.load(
            io.BytesIO(payloads["model_state"]), map_location="cpu", weights_only=True
        )
        optimizer_state = torch.load(
            io.BytesIO(payloads["optimizer_state"]), map_location="cpu", weights_only=True
        )
        trainer_state = torch.load(
            io.BytesIO(payloads["trainer_state"]), map_location="cpu", weights_only=True
        )
        model.load_state_dict(model_state, strict=True)
        optimizer.load_state_dict(optimizer_state)
        for state in optimizer.state.values():
            for key, value in state.items():
                if isinstance(value, torch.Tensor):
                    state[key] = value.to(device)
        required = {
            "completed_epoch",
            "global_step",
            "best_epoch",
            "best_global_step",
            "best_metric",
            "stale_epochs",
            "last_metric",
            "cpu_rng_state",
            "cuda_rng_states",
        }
        if not isinstance(trainer_state, dict) or set(trainer_state) != required:
            raise ValueError("trainer state inventory mismatch")
        torch.set_rng_state(trainer_state["cpu_rng_state"])
        if device.type == "cuda":
            cuda_states = trainer_state["cuda_rng_states"]
            if not isinstance(cuda_states, list) or len(cuda_states) != torch.cuda.device_count():
                raise ValueError("CUDA RNG state inventory mismatch")
            torch.cuda.set_rng_state_all(cuda_states)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        raise ArtifactIntegrityError("cannot restore compatible SASRec resume state") from exc
    return (
        int(trainer_state["completed_epoch"]),
        int(trainer_state["global_step"]),
        int(trainer_state["best_epoch"]),
        int(trainer_state["best_global_step"]),
        float(trainer_state["best_metric"]),
        int(trainer_state["stale_epochs"]),
        manifest.selected_best_manifest_ref,
        float(trainer_state["last_metric"]),
    )


def train_initial_ranker_from_config(
    config_path: str | Path,
    *,
    execution_id: str | None = None,
) -> SasrecTrainingResult:
    loaded = load_phase3_sasrec_training_config(config_path)
    config = loaded.config
    actual_execution_id = execution_id or _execution_id(
        loaded.config_path.relative_to(loaded.project_root),
        config,
    )
    if config.operational.device.startswith("cuda:"):
        deterministic_workspace = os.environ.get("CUBLAS_WORKSPACE_CONFIG")
        if deterministic_workspace is None:
            if torch.cuda.is_initialized():
                raise ContractError("CUDA was initialized before deterministic cuBLAS preflight")
            os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
        elif deterministic_workspace not in {":4096:8", ":16:8"}:
            raise ContractError("CUBLAS_WORKSPACE_CONFIG is incompatible with determinism")
    device = _explicit_device(config.operational.device)
    resolver = FilesystemPathResolver(loaded.root_registry)
    derived_manifest, dataset = load_derived_dataset(resolver, config.derived_manifest_ref)
    vocabulary = dataset.vocabulary
    vocabulary_ref = _vocabulary_ref(derived_manifest)
    item_to_index, index_to_item = _index_maps(vocabulary)
    user_train_indices = {
        split.user_id: frozenset(item_to_index[event.item_id] for event in split.train_events)
        for split in dataset.user_splits
    }
    torch.manual_seed(config.training.training_seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(config.training.training_seed)
    torch.use_deterministic_algorithms(True)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
    model = SasrecModel(vocabulary_size=len(vocabulary.entries), config=config.model).to(device)
    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=config.training.learning_rate,
        betas=(config.training.beta1, config.training.beta2),
        eps=config.training.epsilon,
        weight_decay=config.training.weight_decay,
    )
    completed_epoch = 0
    global_step = 0
    best_epoch = 0
    best_global_step = 0
    best_metric = -1.0
    stale_epochs = 0
    last_metric = 0.0
    selected_best_ref: ResourceRef | None = None
    if config.resume_checkpoint_ref is not None:
        (
            completed_epoch,
            global_step,
            best_epoch,
            best_global_step,
            best_metric,
            stale_epochs,
            selected_best_ref,
            last_metric,
        ) = _restore_resume(
            resolver=resolver,
            config=config,
            model=model,
            optimizer=optimizer,
            device=device,
        )
    best_state: dict[str, torch.Tensor] | None = None
    sample_ids = tuple(sample.sample_id for sample in dataset.training_samples)
    if not sample_ids:
        raise ArtifactIntegrityError("SASRec training dataset must contain logical samples")
    for epoch in range(completed_epoch + 1, config.training.max_epochs + 1):
        model.train()
        order = epoch_sample_order(
            sample_ids,
            training_seed=config.training.training_seed,
            epoch=epoch,
        )
        for start in range(0, len(order), config.training.batch_size):
            samples = tuple(
                dataset.training_samples[index]
                for index in order[start : start + config.training.batch_size]
            )
            histories = tuple(
                _left_padded_history(
                    tuple(event.item_id for event in sample.history),
                    item_to_index=item_to_index,
                    max_length=config.model.max_history_length,
                )
                for sample in samples
            )
            positives = tuple(item_to_index[sample.target.item_id] for sample in samples)
            negatives = tuple(
                deterministic_uniform_negative(
                    vocabulary_size=len(vocabulary.entries),
                    excluded_model_indices=user_train_indices[sample.user_id],
                    training_seed=config.training.training_seed,
                    epoch=epoch,
                    sample_id=sample.sample_id,
                )
                for sample in samples
            )
            history_tensor = torch.tensor(histories, dtype=torch.long, device=device)
            positive_tensor = torch.tensor(positives, dtype=torch.long, device=device)
            negative_tensor = torch.tensor(negatives, dtype=torch.long, device=device)
            optimizer.zero_grad(set_to_none=True)
            loss = model.sampled_binary_loss(
                history_tensor,
                positive_tensor,
                negative_tensor,
            )
            if not torch.isfinite(loss):
                raise ComponentExecutionError("SASRec training produced a non-finite loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                model.parameters(),
                config.training.gradient_clip_global_norm,
                error_if_nonfinite=True,
            )
            optimizer.step()
            model.zero_pad_embedding()
            global_step += 1
        last_metric = _validation_ndcg_at_10(
            model=model,
            dataset=dataset,
            item_to_index=item_to_index,
            index_to_item=index_to_item,
            device=device,
            user_batch_size=config.operational.evaluation_user_batch_size,
        )
        completed_epoch = epoch
        if last_metric > best_metric:
            best_metric = last_metric
            best_epoch = epoch
            best_global_step = global_step
            best_state = _cpu_state_dict(model)
            stale_epochs = 0
        else:
            stale_epochs += 1
        if stale_epochs >= config.training.patience:
            break
    if best_epoch <= 0 or best_metric < 0:
        raise ComponentExecutionError("SASRec training did not produce a selectable checkpoint")
    provenance = _operational_provenance(
        project_root=loaded.project_root,
        device=device,
        config=config,
    )
    publisher = FilesystemSasrecCheckpointPublisher(loaded.root_registry)
    if best_state is not None:
        best_plan = build_sasrec_checkpoint_plan(
            output_root_id=config.output_root_id,
            checkpoint_kind="best",
            model_config=config.model,
            training_recipe=config.training,
            source_data_version=derived_manifest.source_data_version,
            source_release_ref=derived_manifest.source_release_ref,
            derived_manifest_ref=config.derived_manifest_ref,
            derived_manifest=derived_manifest,
            vocabulary_ref=vocabulary_ref,
            vocabulary=vocabulary,
            selected_best_manifest_ref=None,
            epoch=best_epoch,
            global_step=best_global_step,
            best_epoch=best_epoch,
            validation_ndcg_at_10=best_metric,
            best_validation_ndcg_at_10=best_metric,
            model_state=_serialize_torch(best_state),
            optimizer_state=None,
            trainer_state=None,
            operational_provenance=provenance,
        )
        best_publication = publisher.publish(
            best_plan,
            execution_id=f"{actual_execution_id}-best",
        )
        selected_best_ref = best_publication.manifest_ref
        best_outcome = best_publication.outcome
    else:
        if selected_best_ref is None:
            raise ArtifactIntegrityError("resume lost its selected best checkpoint ref")
        best_outcome = "reused"
    trainer_state = {
        "completed_epoch": completed_epoch,
        "global_step": global_step,
        "best_epoch": best_epoch,
        "best_global_step": best_global_step,
        "best_metric": best_metric,
        "stale_epochs": stale_epochs,
        "last_metric": last_metric,
        "cpu_rng_state": torch.get_rng_state(),
        "cuda_rng_states": torch.cuda.get_rng_state_all() if device.type == "cuda" else [],
    }
    last_plan = build_sasrec_checkpoint_plan(
        output_root_id=config.output_root_id,
        checkpoint_kind="last",
        model_config=config.model,
        training_recipe=config.training,
        source_data_version=derived_manifest.source_data_version,
        source_release_ref=derived_manifest.source_release_ref,
        derived_manifest_ref=config.derived_manifest_ref,
        derived_manifest=derived_manifest,
        vocabulary_ref=vocabulary_ref,
        vocabulary=vocabulary,
        selected_best_manifest_ref=selected_best_ref,
        epoch=completed_epoch,
        global_step=global_step,
        best_epoch=best_epoch,
        validation_ndcg_at_10=last_metric,
        best_validation_ndcg_at_10=best_metric,
        model_state=_serialize_torch(_cpu_state_dict(model)),
        optimizer_state=_serialize_torch(optimizer.state_dict()),
        trainer_state=_serialize_torch(trainer_state),
        operational_provenance=provenance,
    )
    last_publication = publisher.publish(
        last_plan,
        execution_id=f"{actual_execution_id}-last",
    )
    assert selected_best_ref is not None
    return SasrecTrainingResult(
        execution_id=actual_execution_id,
        best_outcome=best_outcome,
        last_outcome=last_publication.outcome,
        best_manifest_ref=selected_best_ref,
        last_manifest_ref=last_publication.manifest_ref,
        best_epoch=best_epoch,
        completed_epoch=completed_epoch,
        best_validation_ndcg_at_10=best_metric,
        global_step=global_step,
    )
