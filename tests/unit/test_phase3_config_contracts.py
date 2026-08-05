from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from pave_rec.phase3.config import Phase3StorageConfig, Phase3StorageRootConfig
from pave_rec.phase3.derived import Phase3DerivedSequencesConfig
from pave_rec.phase3.evaluation import Phase3EvaluationConfig
from pave_rec.phase3.memory import Phase3MemoryAuditConfig, Phase3MemoryConfig
from pave_rec.phase3.ranker import Phase3SasrecTrainingConfig
from pave_rec.phase3.semantics import Phase3ItemSemanticsConfig


def _payload(repo_root: Path, name: str) -> dict:
    loaded = yaml.safe_load((repo_root / "configs/phase3" / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _reject(model, value, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        model.model_validate(value)


@pytest.mark.parametrize(
    "name, model",
    [
        ("derived.yaml", Phase3DerivedSequencesConfig),
        ("semantic.yaml", Phase3ItemSemanticsConfig),
        ("sasrec_train.yaml", Phase3SasrecTrainingConfig),
        ("memory.yaml", Phase3MemoryConfig),
        ("memory_audit.yaml", Phase3MemoryAuditConfig),
        ("evaluate_mostpop_test.yaml", Phase3EvaluationConfig),
        ("evaluate_sasrec_test.yaml", Phase3EvaluationConfig),
    ],
)
def test_committed_phase3_configs_satisfy_their_exact_contracts(
    repo_root: Path,
    name: str,
    model,
) -> None:
    assert model.model_validate(_payload(repo_root, name)).kind.startswith("phase3-")


def test_shared_phase3_storage_contracts_fail_closed() -> None:
    _reject(Phase3StorageRootConfig, {"path": "", "access": "read_only"}, "non-empty")
    _reject(Phase3StorageConfig, {"roots": {}}, "must not be empty")
    _reject(
        Phase3StorageConfig,
        {"roots": {"bad/root": {"path": "data", "access": "read_only"}}},
        "root ID",
    )


def test_derived_config_rejects_source_and_output_identity_drift(repo_root: Path) -> None:
    base = _payload(repo_root, "derived.yaml")
    invalid = deepcopy(base)
    invalid["source_release_ref"]["key"] = "releases/wrong.json"
    _reject(Phase3DerivedSequencesConfig, invalid, "key/version mismatch")
    invalid = deepcopy(base)
    invalid["source_release_ref"]["checksum"] = "sha256:bad"
    _reject(Phase3DerivedSequencesConfig, invalid, "invalid source_release_ref")
    invalid = deepcopy(base)
    invalid["storage"]["roots"]["processed"]["access"] = "write_new"
    _reject(Phase3DerivedSequencesConfig, invalid, "declared read_only")
    invalid = deepcopy(base)
    invalid["storage"]["roots"]["derived"]["access"] = "read_only"
    _reject(Phase3DerivedSequencesConfig, invalid, "declared write_new")


def test_evaluation_config_rejects_method_device_size_and_root_drift(repo_root: Path) -> None:
    base = _payload(repo_root, "evaluate_mostpop_test.yaml")
    _reject(
        Phase3EvaluationConfig,
        {**base, "checkpoint_ref": base["derived_artifact_ref"]},
        "requires one exact checkpoint",
    )
    _reject(Phase3EvaluationConfig, {**base, "device": "gpu"}, "cpu or cuda")
    _reject(Phase3EvaluationConfig, {**base, "candidate_chunk_size": 0}, "must be positive")
    invalid = deepcopy(base)
    invalid["storage"]["roots"]["derived"]["access"] = "write_new"
    _reject(Phase3EvaluationConfig, invalid, "declared read_only")
    invalid = deepcopy(base)
    invalid["storage"]["roots"]["evaluations"]["access"] = "read_only"
    _reject(Phase3EvaluationConfig, invalid, "declared write_new")


def test_semantic_config_rejects_provider_operational_and_root_drift(repo_root: Path) -> None:
    base = _payload(repo_root, "semantic.yaml")
    invalid = deepcopy(base)
    invalid["provider"]["snapshot_manifest_ref"]["version"] = "0" * 40
    _reject(Phase3ItemSemanticsConfig, invalid, "must equal the pinned model revision")
    invalid = deepcopy(base)
    invalid["provider"]["snapshot_manifest_ref"]["key"] = "wrong.json"
    _reject(Phase3ItemSemanticsConfig, invalid, "key/revision mismatch")
    invalid = deepcopy(base)
    invalid["provider"]["model_directory_key"] = "../escape"
    _reject(Phase3ItemSemanticsConfig, invalid, "dot path segment")
    invalid = deepcopy(base)
    invalid["operational"]["device"] = "cuda"
    _reject(Phase3ItemSemanticsConfig, invalid, "semantic device")
    invalid = deepcopy(base)
    invalid["operational"]["batch_size"] = 0
    _reject(Phase3ItemSemanticsConfig, invalid, "must be positive")
    invalid = deepcopy(base)
    invalid["storage"]["roots"]["model_cache"]["access"] = "write_new"
    _reject(Phase3ItemSemanticsConfig, invalid, "declared read_only")
    invalid = deepcopy(base)
    invalid["storage"]["roots"]["semantics"]["access"] = "read_only"
    _reject(Phase3ItemSemanticsConfig, invalid, "declared write_new")


def test_memory_and_audit_configs_reject_ref_and_root_drift(repo_root: Path) -> None:
    base = _payload(repo_root, "memory.yaml")
    invalid = deepcopy(base)
    invalid["source_release_ref"]["key"] = "releases/wrong.json"
    _reject(Phase3MemoryConfig, invalid, "key/version mismatch")
    invalid = deepcopy(base)
    invalid["semantic_artifact_ref"]["checksum"] = "bad"
    _reject(Phase3MemoryConfig, invalid, "must be sha256")
    invalid = deepcopy(base)
    invalid["storage"]["roots"]["semantics"]["access"] = "write_new"
    _reject(Phase3MemoryConfig, invalid, "declared read_only")
    invalid = deepcopy(base)
    invalid["storage"]["roots"]["memory"]["access"] = "read_only"
    _reject(Phase3MemoryConfig, invalid, "declared write_new")

    audit = _payload(repo_root, "memory_audit.yaml")
    invalid = deepcopy(audit)
    invalid["memory_artifact_ref"]["checksum"] = "bad"
    _reject(Phase3MemoryAuditConfig, invalid, "must be sha256")
    invalid = deepcopy(audit)
    invalid["storage"]["roots"]["memory"]["access"] = "write_new"
    _reject(Phase3MemoryAuditConfig, invalid, "declared read_only")
    invalid = deepcopy(audit)
    invalid["storage"]["roots"]["memory_audits"]["access"] = "read_only"
    _reject(Phase3MemoryAuditConfig, invalid, "declared write_new")


def test_sasrec_config_rejects_operational_refs_and_roots(repo_root: Path) -> None:
    base = _payload(repo_root, "sasrec_train.yaml")
    invalid = deepcopy(base)
    invalid["operational"]["device"] = "cuda"
    _reject(Phase3SasrecTrainingConfig, invalid, "device must be")
    invalid = deepcopy(base)
    invalid["operational"]["loader_workers"] = -1
    _reject(Phase3SasrecTrainingConfig, invalid, "must be non-negative")
    invalid = deepcopy(base)
    invalid["operational"]["candidate_chunk_size"] = 0
    _reject(Phase3SasrecTrainingConfig, invalid, "must be positive")
    invalid = deepcopy(base)
    invalid["derived_manifest_ref"]["key"] = "wrong.json"
    _reject(Phase3SasrecTrainingConfig, invalid, "key/version mismatch")
    invalid = deepcopy(base)
    invalid["storage"]["roots"]["derived"]["access"] = "write_new"
    _reject(Phase3SasrecTrainingConfig, invalid, "declared read_only")
    invalid = deepcopy(base)
    invalid["storage"]["roots"]["checkpoints"]["access"] = "read_only"
    _reject(Phase3SasrecTrainingConfig, invalid, "declared write_new")

    with_resume = deepcopy(base)
    checkpoint = _payload(repo_root, "evaluate_sasrec_test.yaml")["checkpoint_ref"]
    checkpoint["store"] = "resume"
    with_resume["storage"]["roots"]["resume"] = {
        "path": "artifacts/checkpoints",
        "access": "read_only",
    }
    with_resume["resume_checkpoint_ref"] = checkpoint
    assert Phase3SasrecTrainingConfig.model_validate(with_resume).resume_checkpoint_ref is not None
    invalid = deepcopy(with_resume)
    invalid["storage"]["roots"]["resume"]["access"] = "write_new"
    _reject(Phase3SasrecTrainingConfig, invalid, "declared read_only")
