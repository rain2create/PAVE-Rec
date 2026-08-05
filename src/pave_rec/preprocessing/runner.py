"""Single high-level Phase 2 preprocessing lifecycle shared by Python and CLI."""

from __future__ import annotations

import importlib.metadata
import platform as platform_module
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pydantic
import yaml

from pave_rec.domain.serialization import write_canonical_json
from pave_rec.errors import ArtifactPublicationError, PaveRecError
from pave_rec.runner import collect_git_metadata

from .artifacts import ReleasePublicationPlan, build_release_plan
from .components import PreprocessingComponents, build_preprocessing_components
from .config import LoadedPreprocessingConfig, load_preprocessing_config
from .identity import build_data_identity, data_version
from .models import (
    ExecutionReport,
    ExecutionRootRecord,
    PreprocessingResult,
)
from .publisher import FilesystemReleasePublisher, publication_staging_key
from .source import LoadedSourceDataset, load_source_dataset


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_execution_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(4)}"


def _safe_message(error: PaveRecError) -> str:
    message = " ".join(str(error).split()) or type(error).__name__
    message = re.sub(r"[A-Za-z]:[\\/][^\s]+", "<path>", message)
    message = re.sub(r"(?<!\w)/(?:[^/\s]+/)+[^\s]+", "<path>", message)
    return message[:500]


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _root_records(loaded: LoadedPreprocessingConfig) -> tuple[ExecutionRootRecord, ...]:
    return tuple(
        ExecutionRootRecord(
            root_id=root_id,
            configured_path=root.configured_path,
            resolved_path=str(root.path),
            access=root.access,
        )
        for root_id, root in sorted(loaded.root_registry.roots.items())
    )


def _staging_locations(
    loaded: LoadedPreprocessingConfig, version: str | None, execution_id: str
) -> tuple[str, ...]:
    if version is None:
        return ()
    return tuple(
        str(
            root.path.joinpath(
                *publication_staging_key(root.root_id, version, execution_id).split("/")
            )
        )
        for root in sorted(
            (
                loaded.root_registry.require(loaded.config.output.features_root_id),
                loaded.root_registry.require(loaded.config.output.processed_root_id),
            ),
            key=lambda value: value.root_id,
        )
    )


@dataclass(frozen=True)
class ExecutionState:
    source: LoadedSourceDataset | None = None
    data_version: str | None = None
    plan: ReleasePublicationPlan | None = None


class PreprocessingCoordinator:
    def __init__(
        self,
        loaded: LoadedPreprocessingConfig,
        components: PreprocessingComponents,
        *,
        publisher: FilesystemReleasePublisher | None = None,
    ) -> None:
        self._loaded = loaded
        self._components = components
        self._publisher = publisher or FilesystemReleasePublisher(loaded.root_registry)
        self._state = ExecutionState()

    @property
    def state(self) -> ExecutionState:
        return self._state

    def execute(self, *, execution_id: str) -> tuple[PreprocessingResult, ExecutionState]:
        source = load_source_dataset(self._loaded)
        self._state = ExecutionState(source=source)
        identity = build_data_identity(
            source=source,
            config=self._loaded.config,
            component_descriptors=self._components.descriptors,
        )
        version = data_version(identity)
        self._state = ExecutionState(source=source, data_version=version)
        plan = build_release_plan(
            version=version,
            identity=identity,
            source=source,
            config=self._loaded.config,
            components=self._components,
        )
        self._state = ExecutionState(source=source, data_version=version, plan=plan)
        publication = self._publisher.publish(plan, execution_id=execution_id)
        result = PreprocessingResult(
            execution_id=execution_id,
            outcome=publication.outcome,
            data_version=version,
            release_ref=plan.release_ref,
            execution_report_path=Path(),
            item_count=len(source.items),
            behavior_event_count=len(source.behavior_events),
            segment_count=len(source.segment_definitions),
            artifact_count=plan.artifact_count,
        )
        return result, self._state


def _allocate_execution_directory(project_root: Path) -> tuple[str, Path]:
    root = project_root / "runs" / "preprocessing"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ArtifactPublicationError("cannot create preprocessing execution root") from exc
    for _ in range(100):
        execution_id = generate_execution_id()
        directory = root / execution_id
        try:
            directory.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        except OSError as exc:
            raise ArtifactPublicationError(
                "cannot create preprocessing execution directory"
            ) from exc
        return execution_id, directory
    raise ArtifactPublicationError("could not allocate a unique preprocessing execution ID")


def _report(
    *,
    loaded: LoadedPreprocessingConfig,
    components: PreprocessingComponents,
    execution_id: str,
    started_at: str,
    status: str,
    result: PreprocessingResult | None,
    state: ExecutionState,
    error: PaveRecError | None,
) -> ExecutionReport:
    git = collect_git_metadata(loaded.project_root)
    version = result.data_version if result is not None else state.data_version
    source = state.source
    plan = state.plan
    return ExecutionReport(
        schema_version="execution-report-v1",
        execution_id=execution_id,
        status=status,
        outcome=result.outcome if result is not None else None,
        data_version=version,
        release_ref=result.release_ref if result is not None else None,
        started_at_utc=started_at,
        completed_at_utc=_utc_now(),
        config_path=str(loaded.config_path),
        roots=_root_records(loaded),
        component_descriptors=components.descriptors,
        git_commit=git.commit,
        git_dirty=git.dirty,
        python_version=platform_module.python_version(),
        pave_rec_version=_package_version("pave-rec"),
        pydantic_version=pydantic.__version__,
        pyyaml_version=yaml.__version__,
        platform=platform_module.platform(),
        item_count=len(source.items) if source is not None else None,
        behavior_event_count=len(source.behavior_events) if source is not None else None,
        segment_count=len(source.segment_definitions) if source is not None else None,
        artifact_count=plan.artifact_count if plan is not None else None,
        staging_locations=_staging_locations(loaded, version, execution_id),
        error_code=type(error).__name__ if error is not None else None,
        error_message=_safe_message(error) if error is not None else None,
    )


def preprocess_from_config(config_path: str | Path) -> PreprocessingResult:
    loaded = load_preprocessing_config(config_path)
    components = build_preprocessing_components(loaded.config)
    execution_id, execution_dir = _allocate_execution_directory(loaded.project_root)
    report_path = execution_dir / "execution_report.json"
    started_at = _utc_now()
    state = ExecutionState()
    coordinator = PreprocessingCoordinator(loaded, components)
    try:
        result, state = coordinator.execute(execution_id=execution_id)
    except PaveRecError as error:
        state = coordinator.state
        failed_report = _report(
            loaded=loaded,
            components=components,
            execution_id=execution_id,
            started_at=started_at,
            status="failed",
            result=None,
            state=state,
            error=error,
        )
        try:
            write_canonical_json(report_path, failed_report)
        except OSError:
            pass
        raise
    final_result = PreprocessingResult(
        **{
            **result.__dict__,
            "execution_report_path": report_path,
        }
    )
    success_report = _report(
        loaded=loaded,
        components=components,
        execution_id=execution_id,
        started_at=started_at,
        status="succeeded",
        result=final_result,
        state=state,
        error=None,
    )
    try:
        write_canonical_json(report_path, success_report)
    except OSError as exc:
        raise ArtifactPublicationError(
            "release is complete but terminal execution report could not be written"
        ) from exc
    return final_result
