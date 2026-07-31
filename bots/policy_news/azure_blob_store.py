"""Durable Azure Blob RunStorePort using managed identity and private containers."""

from __future__ import annotations

import json
import re
import threading
from contextlib import contextmanager
from typing import Any

from contracts import RunRecord, SourcePacket


def _is_status(exc: Exception, status: int) -> bool:
    return getattr(exc, "status_code", None) == status or (
        status == 404 and type(exc).__name__ == "ResourceNotFoundError"
    ) or (status == 409 and type(exc).__name__ == "ResourceExistsError")


class ActiveRunError(RuntimeError):
    pass


class AzureBlobRunStore:
    """Two-container durable store.

    ``runs`` contains immutable idempotency indexes and mutable audit records;
    ``sources`` contains the private full official-source packet keyed by its
    content digest. Containers are provisioned private by Bicep. The runtime
    never creates containers or enables anonymous/shared-key access.
    """

    def __init__(
        self,
        account_url: str,
        *,
        runs_container: str = "policy-news-runs",
        sources_container: str = "policy-news-sources",
        credential: Any | None = None,
        service_client: Any | None = None,
        lease_factory: Any | None = None,
    ) -> None:
        if not account_url.startswith("https://") or not account_url.endswith(".blob.core.windows.net"):
            raise ValueError("AZURE_STORAGE_BLOB_URL must be an Azure Blob HTTPS account URL")
        if service_client is None:
            try:
                from azure.identity import DefaultAzureCredential
                from azure.storage.blob import BlobLeaseClient, BlobServiceClient, ContentSettings
            except ImportError as exc:
                raise RuntimeError("azure-identity and azure-storage-blob are required for AzureBlobRunStore") from exc
            credential = credential or DefaultAzureCredential(exclude_interactive_browser_credential=True)
            service_client = BlobServiceClient(account_url=account_url, credential=credential)
            self._content_settings = ContentSettings
            self._lease_factory = BlobLeaseClient
        else:
            self._content_settings = lambda **kwargs: kwargs
            self._lease_factory = lease_factory
        self.runs = service_client.get_container_client(runs_container)
        self.sources = service_client.get_container_client(sources_container)

    @contextmanager
    def claim_source(self, content_sha256: str):
        """Cross-execution lease preventing duplicate provider calls.

        Container Apps can start overlapping manual/scheduled executions even
        when each execution has parallelism=1. A renewable 60-second Blob lease
        closes that gap without leaving an infinite lock after a crash.
        """
        if not re.fullmatch(r"[a-f0-9]{64}", content_sha256):
            raise ValueError("content_sha256 must be lowercase SHA-256 hex")
        if self._lease_factory is None:
            raise RuntimeError("a Blob lease factory is required")
        lock_blob = self.runs.get_blob_client(f"locks/{content_sha256}.lock")
        try:
            lock_blob.upload_blob(b"", overwrite=False, content_settings=self._content_settings(content_type="application/octet-stream"))
        except Exception as exc:
            if not _is_status(exc, 409):
                raise
        lease = self._lease_factory(lock_blob)
        try:
            lease.acquire(lease_duration=60)
        except Exception as exc:
            if _is_status(exc, 409):
                raise ActiveRunError("source is already active in another execution") from exc
            raise
        stop = threading.Event()
        renewal_errors: list[Exception] = []

        def renew() -> None:
            while not stop.wait(30):
                try:
                    lease.renew()
                except Exception as exc:  # pragma: no cover - Azure timing path
                    renewal_errors.append(exc)
                    return

        thread = threading.Thread(target=renew, name="policy-news-blob-lease", daemon=True)
        thread.start()
        body_error = False
        try:
            yield
        except Exception:
            body_error = True
            raise
        finally:
            stop.set()
            thread.join(timeout=2)
            try:
                lease.release()
            finally:
                if renewal_errors and not body_error:
                    raise RuntimeError("lost durable source lease during processing") from renewal_errors[0]

    @staticmethod
    def _text(blob: Any) -> str:
        return blob.download_blob().readall().decode("utf-8")

    def load_by_idempotency_key(self, key: str) -> RunRecord | None:
        index = self.runs.get_blob_client(f"idempotency/{key}.txt")
        try:
            run_id = self._text(index).strip()
        except Exception as exc:
            if _is_status(exc, 404):
                return None
            raise
        if run_id != key[:24]:
            raise RuntimeError("idempotency index contains an unexpected run id")
        record_blob = self.runs.get_blob_client(f"records/{run_id}.json")
        try:
            return RunRecord.from_dict(json.loads(self._text(record_blob)))
        except Exception as exc:
            if _is_status(exc, 404):
                raise RuntimeError("idempotency index points to a missing run record") from exc
            raise

    def save_source(self, packet: SourcePacket) -> None:
        blob = self.sources.get_blob_client(f"sha256/{packet.content_sha256}.json")
        payload = json.dumps(packet.provider_payload(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        try:
            blob.upload_blob(
                payload.encode("utf-8"),
                overwrite=False,
                metadata={"sha256": packet.content_sha256, "source_id": packet.source_id},
                content_settings=self._content_settings(content_type="application/json; charset=utf-8"),
            )
        except Exception as exc:
            if not _is_status(exc, 409):
                raise
            existing = SourcePacket.from_dict(json.loads(self._text(blob)))
            if existing.content_sha256 != packet.content_sha256:
                raise RuntimeError("source artifact hash collision") from exc

    def save(self, record: RunRecord) -> None:
        # Write the deterministic record first. If the process dies before the
        # immutable index is created, the next attempt safely overwrites this
        # same run id and can create the index; the reverse order could leave a
        # permanently dangling index.
        serialized = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        self.runs.get_blob_client(f"records/{record.run_id}.json").upload_blob(
            serialized.encode("utf-8"),
            overwrite=True,
            metadata={"idempotency_key": record.idempotency_key, "state": record.state.value},
            content_settings=self._content_settings(content_type="application/json; charset=utf-8"),
        )
        index = self.runs.get_blob_client(f"idempotency/{record.idempotency_key}.txt")
        try:
            index.upload_blob((record.run_id + "\n").encode("utf-8"), overwrite=False, content_settings=self._content_settings(content_type="text/plain; charset=utf-8"))
        except Exception as exc:
            if not _is_status(exc, 409):
                raise
            existing = self._text(index).strip()
            if existing != record.run_id:
                raise RuntimeError("idempotency key belongs to a different run") from exc
