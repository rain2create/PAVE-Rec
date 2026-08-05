"""No-overwrite multi-root filesystem publication for deterministic releases."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pave_rec.errors import ArtifactIntegrityError, ArtifactPublicationError, PaveRecError

from .artifacts import ReleasePublicationPlan, RootPublication
from .paths import FilesystemPathResolver, RootRegistry

FaultInjector = Callable[[str], None]


def publication_staging_key(root_id: str, data_version: str, execution_id: str) -> str:
    """Return an undiscoverable operational staging key.

    Windows without long-path support cannot materialize the portable bundle keys
    below the historical ``staging/<data_version>/<execution_id>`` prefix once the
    full SHA-256 identities are included.  The staging location is invocation-local
    and excluded from artifact identity, so Windows uses a deterministic opaque token
    while published bundle keys remain byte-for-byte unchanged.
    """

    if os.name != "nt":
        return f"staging/{data_version}/{execution_id}"
    identity = "\0".join((root_id, data_version, execution_id)).encode("utf-8")
    # This is an operational namespace key, not an artifact identity.  A
    # 128-bit prefix keeps legacy Windows paths below MAX_PATH while retaining
    # ample collision resistance; mkdir(exist_ok=False) also fails closed if a
    # collision ever occurs.
    token = hashlib.sha256(identity).hexdigest()[:32]
    return f"staging/{token}"


@dataclass(frozen=True)
class PublicationResult:
    outcome: str


class FilesystemReleasePublisher:
    def __init__(
        self,
        registry: RootRegistry,
        *,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self._registry = registry
        self._resolver = FilesystemPathResolver(registry)
        self._fault_injector = fault_injector

    def _inject(self, boundary: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(boundary)

    def _expected_path(self, root_id: str, key: str) -> Path:
        return self._resolver.resolve_new_path(root_id, key)

    def _verify_file(self, path: Path, expected: bytes, *, label: str) -> None:
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise ArtifactIntegrityError(f"cannot verify published artifact: {label}") from exc
        if actual != expected:
            raise ArtifactIntegrityError(f"published artifact mismatch: {label}")

    def _verify_root(self, root: RootPublication) -> None:
        for ref, payload in root.files:
            self._verify_file(
                self._expected_path(ref.store, ref.key),
                payload,
                label=f"{ref.store}/{ref.key}",
            )

    def _verify_complete_release(self, plan: ReleasePublicationPlan) -> None:
        self._verify_file(
            self._expected_path(plan.release_ref.store, plan.release_ref.key),
            plan.release_payload,
            label=f"{plan.release_ref.store}/{plan.release_ref.key}",
        )
        for root in plan.roots:
            self._verify_root(root)

    def _write_stage(self, root: RootPublication, *, execution_id: str) -> Path:
        bundle_prefix = f"bundles/{root.manifest.data_version}/"
        stage_key = publication_staging_key(root.root_id, root.manifest.data_version, execution_id)
        stage = self._expected_path(root.root_id, stage_key)
        try:
            stage.mkdir(parents=True, exist_ok=False)
            for ref, payload in root.files:
                if not ref.key.startswith(bundle_prefix):
                    raise ArtifactPublicationError(
                        "root artifact key is outside its version bundle"
                    )
                relative = ref.key.removeprefix(bundle_prefix)
                target = stage.joinpath(*relative.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            self._inject(f"after_stage_write:{root.root_id}")
            for ref, payload in root.files:
                relative = ref.key.removeprefix(bundle_prefix)
                self._verify_file(
                    stage.joinpath(*relative.split("/")),
                    payload,
                    label=f"staging/{root.root_id}/{relative}",
                )
            return stage
        except PaveRecError:
            raise
        except OSError as exc:
            raise ArtifactPublicationError(f"cannot stage root bundle: {root.root_id}") from exc

    def _publish_root(self, root: RootPublication, *, execution_id: str) -> None:
        bundle_key = f"bundles/{root.manifest.data_version}"
        target = self._expected_path(root.root_id, bundle_key)
        if target.exists():
            self._verify_root(root)
            return
        stage = self._write_stage(root, execution_id=execution_id)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._inject(f"before_root_rename:{root.root_id}")
            stage.rename(target)
        except OSError as exc:
            if target.exists():
                self._verify_root(root)
                return
            raise ArtifactPublicationError(f"cannot publish root bundle: {root.root_id}") from exc
        self._verify_root(root)

    def _exclusive_publish_release(self, plan: ReleasePublicationPlan) -> bool:
        target = self._expected_path(plan.release_ref.store, plan.release_ref.key)
        if target.exists():
            self._verify_complete_release(plan)
            return False
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(plan.release_payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                self._inject("before_release_publish")
                os.link(temporary, target)
            except FileExistsError:
                self._verify_complete_release(plan)
                return False
            finally:
                temporary.unlink(missing_ok=True)
        except PaveRecError:
            raise
        except OSError as exc:
            raise ArtifactPublicationError("cannot exclusively publish release manifest") from exc
        self._verify_complete_release(plan)
        return True

    def publish(self, plan: ReleasePublicationPlan, *, execution_id: str) -> PublicationResult:
        release_path = self._expected_path(plan.release_ref.store, plan.release_ref.key)
        if release_path.exists():
            self._verify_complete_release(plan)
            return PublicationResult(outcome="reused")
        for root in plan.roots:
            self._publish_root(root, execution_id=execution_id)
        created = self._exclusive_publish_release(plan)
        return PublicationResult(outcome="created" if created else "reused")
