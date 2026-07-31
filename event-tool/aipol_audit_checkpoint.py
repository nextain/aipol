"""Keyed, monotonic checkpoints for the AIPOL audit chain.

The SQLite chain remains the detailed source of truth.  This module anchors
each committed chain head in a separately administered create-only store so a
writer that can rewrite the SQLite file cannot silently truncate or rebuild
history.  Production uses an immutable Azure Blob container; file and memory
stores are development/test adapters only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import secret_env


CHECKPOINT_VERSION = "aipol-audit-checkpoint-v1"
AUDIT_SCHEMA_VERSION = "aipol-admin-audit-v2"
GENESIS_HASH = "0" * 64
_BLOB_PREFIX = "aipol-audit-checkpoint-"
_BLOB_RE = re.compile(r"^aipol-audit-checkpoint-(\d{20})\.json$")


class CheckpointError(RuntimeError):
    """The external checkpoint cannot prove the current SQLite audit head."""


class CheckpointStore(Protocol):
    name: str

    def list(self) -> list[dict]:
        """Return every immutable checkpoint in sequence order."""

    def create(self, sequence: int, payload: dict) -> None:
        """Create exactly one checkpoint for sequence; never overwrite."""


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _keyset() -> dict[str, str]:
    try:
        raw = secret_env.text("AIPOL_AUDIT_CHECKPOINT_SECRETS_JSON")
    except ValueError as exc:
        raise CheckpointError(
            "AIPOL_AUDIT_CHECKPOINT_SECRETS_JSON_B64 must be valid base64-encoded UTF-8"
        ) from exc
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CheckpointError("audit checkpoint secret keyset must be valid JSON") from exc
    if (
        not isinstance(parsed, dict)
        or not parsed
        or any(
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(secret, str)
            or len(secret) < 32
            for key, secret in parsed.items()
        )
    ):
        raise CheckpointError("audit checkpoint keyset must map key ids to 32+ character secrets")
    return {key.strip(): secret for key, secret in parsed.items()}


def _active_key_id(keys: dict[str, str]) -> str:
    key_id = os.environ.get("AIPOL_AUDIT_CHECKPOINT_ACTIVE_KEY_ID", "").strip()
    if not key_id or key_id not in keys:
        raise CheckpointError("an active audit checkpoint signing key is required")
    return key_id


def _signed(envelope: dict, *, key_id: str, secret: str) -> dict:
    signature = hmac.new(secret.encode("utf-8"), _canonical(envelope).encode("utf-8"), hashlib.sha256).hexdigest()
    return {**envelope, "key_id": key_id, "signature": signature}


def _verify(value: dict, keys: dict[str, str]) -> dict:
    expected_fields = {
        "version", "sequence", "head_hash", "previous_hash", "db_instance_id",
        "schema_version", "created_at", "key_id", "signature",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise CheckpointError("audit checkpoint fields do not match the canonical contract")
    key_id = value.get("key_id")
    secret = keys.get(key_id) if isinstance(key_id, str) else None
    if not secret:
        raise CheckpointError("audit checkpoint signing key is unavailable")
    envelope = {key: value[key] for key in value if key not in {"key_id", "signature"}}
    expected = hmac.new(secret.encode("utf-8"), _canonical(envelope).encode("utf-8"), hashlib.sha256).hexdigest()
    if not isinstance(value.get("signature"), str) or not hmac.compare_digest(value["signature"], expected):
        raise CheckpointError("audit checkpoint signature is invalid")
    if value["version"] != CHECKPOINT_VERSION or value["schema_version"] != AUDIT_SCHEMA_VERSION:
        raise CheckpointError("audit checkpoint version is unsupported")
    if isinstance(value["sequence"], bool) or not isinstance(value["sequence"], int) or value["sequence"] < 0:
        raise CheckpointError("audit checkpoint sequence is invalid")
    for field in ("head_hash", "previous_hash"):
        if not isinstance(value[field], str) or not re.fullmatch(r"[0-9a-f]{64}", value[field]):
            raise CheckpointError(f"audit checkpoint {field} is invalid")
    try:
        timestamp = datetime.fromisoformat(str(value["created_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CheckpointError("audit checkpoint created_at is invalid") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise CheckpointError("audit checkpoint created_at must be timezone-aware")
    if not isinstance(value["db_instance_id"], str) or not value["db_instance_id"].strip():
        raise CheckpointError("audit checkpoint db instance is invalid")
    return value


@dataclass
class MemoryCheckpointStore:
    """Explicit test adapter. It intentionally provides no durable guarantee."""

    blobs: dict[int, dict]
    name: str = "memory-development-only"

    def list(self) -> list[dict]:
        return [json.loads(_canonical(self.blobs[key])) for key in sorted(self.blobs)]

    def create(self, sequence: int, payload: dict) -> None:
        existing = self.blobs.get(sequence)
        if existing is not None:
            if _canonical(existing) != _canonical(payload):
                raise CheckpointError("create-only checkpoint already exists with different content")
            return
        self.blobs[sequence] = json.loads(_canonical(payload))


class FileCheckpointStore:
    """Local development adapter; never accepted in production."""

    name = "file-development-only"

    def __init__(self, directory: Path) -> None:
        if not directory.is_absolute():
            raise CheckpointError("audit checkpoint file directory must be absolute")
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory

    def _path(self, sequence: int) -> Path:
        return self.directory / f"{_BLOB_PREFIX}{sequence:020d}.json"

    def list(self) -> list[dict]:
        values: list[dict] = []
        for path in sorted(self.directory.glob(f"{_BLOB_PREFIX}*.json")):
            if not _BLOB_RE.fullmatch(path.name):
                raise CheckpointError("unexpected file in audit checkpoint directory")
            try:
                values.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as exc:
                raise CheckpointError("audit checkpoint file is unreadable") from exc
        return values

    def create(self, sequence: int, payload: dict) -> None:
        path = self._path(sequence)
        serialized = _canonical(payload)
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != serialized:
                raise CheckpointError("create-only checkpoint already exists with different content")


class AzureBlobCheckpointStore:
    """Managed-identity adapter for a dedicated immutable Blob container."""

    name = "azure-blob-immutable"

    def __init__(self, container_url: str, client_id: str, policy_resource_id: str, *, opener=None, credential=None) -> None:
        parsed = urllib.parse.urlsplit(container_url)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or not host.endswith(".blob.core.windows.net")
            or parsed.username
            or parsed.password
            or parsed.port is not None
            or not parsed.path.strip("/")
            or "/" in parsed.path.strip("/")
            or parsed.query
            or parsed.fragment
            or container_url != f"https://{host}/{parsed.path.strip('/')}"
        ):
            raise CheckpointError("audit checkpoint container must be a canonical Azure Blob container URL")
        if not client_id.strip():
            raise CheckpointError("AZURE_CLIENT_ID is required for Azure audit checkpoints")
        policy_pattern = re.compile(
            r"^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.Storage/"
            r"storageAccounts/([^/]+)/blobServices/default/containers/([^/]+)/"
            r"immutabilityPolicies/default$",
            re.IGNORECASE,
        )
        policy_match = policy_pattern.fullmatch(policy_resource_id)
        if (
            not policy_match
            or policy_match.group(1).casefold() != host.split(".", 1)[0].casefold()
            or policy_match.group(2).casefold() != parsed.path.strip("/").casefold()
        ):
            raise CheckpointError("audit checkpoint immutability policy resource ID is invalid")
        if credential is None:
            try:
                from azure.identity import ManagedIdentityCredential
            except ImportError as exc:
                raise CheckpointError("azure-identity is required for Azure audit checkpoints") from exc
            credential = ManagedIdentityCredential(client_id=client_id.strip())
        self.container_url = container_url
        self.policy_resource_id = policy_resource_id
        self.credential = credential
        self.opener = opener or urllib.request.build_opener()

    def _headers(self, scope: str = "https://storage.azure.com/.default") -> dict[str, str]:
        token = self.credential.get_token(scope).token
        return {
            "Authorization": f"Bearer {token}",
            "x-ms-date": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "x-ms-version": "2023-11-03",
        }

    def _request(self, url: str, *, method: str = "GET", body: bytes | None = None, extra=None):
        headers = {**self._headers(), **(extra or {})}
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        return self.opener.open(request, timeout=20)

    def _assert_locked(self) -> None:
        url = (
            "https://management.azure.com"
            f"{urllib.parse.quote(self.policy_resource_id, safe='/')}?api-version=2025-01-01"
        )
        request = urllib.request.Request(
            url,
            headers=self._headers("https://management.azure.com/.default"),
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read(65_537)
            if len(raw) > 65_536:
                raise CheckpointError("immutability policy response exceeds size limit")
            policy = json.loads(raw)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise CheckpointError("unable to verify Azure immutability policy") from exc
        properties = policy.get("properties") if isinstance(policy, dict) else None
        if not isinstance(properties, dict) or properties.get("state") != "Locked":
            raise CheckpointError("Azure audit checkpoint immutability policy is not Locked")

    def list(self) -> list[dict]:
        self._assert_locked()
        values: list[dict] = []
        marker = ""
        while True:
            query = {"restype": "container", "comp": "list", "prefix": _BLOB_PREFIX}
            if marker:
                query["marker"] = marker
            url = f"{self.container_url}?{urllib.parse.urlencode(query)}"
            try:
                with self._request(url) as response:
                    root = ET.fromstring(response.read(1_000_001))
            except (urllib.error.URLError, ET.ParseError, OSError) as exc:
                raise CheckpointError("unable to list immutable audit checkpoints") from exc
            names = [node.text or "" for node in root.findall("./Blobs/Blob/Name")]
            for name in names:
                if not _BLOB_RE.fullmatch(name):
                    raise CheckpointError("unexpected blob in dedicated audit checkpoint container")
                try:
                    with self._request(f"{self.container_url}/{urllib.parse.quote(name)}") as response:
                        raw = response.read(65_537)
                    if len(raw) > 65_536:
                        raise CheckpointError("audit checkpoint blob exceeds size limit")
                    values.append(json.loads(raw))
                except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
                    raise CheckpointError("unable to read immutable audit checkpoint") from exc
            marker = root.findtext("./NextMarker", default="")
            if not marker:
                break
        return values

    def create(self, sequence: int, payload: dict) -> None:
        self._assert_locked()
        name = f"{_BLOB_PREFIX}{sequence:020d}.json"
        url = f"{self.container_url}/{name}"
        raw = _canonical(payload).encode("utf-8")
        try:
            with self._request(
                url,
                method="PUT",
                body=raw,
                extra={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(raw)),
                    "If-None-Match": "*",
                    "x-ms-blob-type": "BlockBlob",
                },
            ):
                return
        except urllib.error.HTTPError as exc:
            if exc.code != 412:
                raise CheckpointError("unable to create immutable audit checkpoint") from exc
        existing = next((item for item in self.list() if item.get("sequence") == sequence), None)
        if existing is None or _canonical(existing) != _canonical(payload):
            raise CheckpointError("create-only checkpoint conflict")


_store: CheckpointStore | None = None


def configure(store: CheckpointStore | None) -> None:
    global _store
    _store = store


def configured() -> bool:
    return _store is not None


def store_from_environment(*, production: bool) -> CheckpointStore | None:
    mode = os.environ.get("AIPOL_AUDIT_CHECKPOINT_MODE", "disabled").strip().lower()
    if mode in {"", "disabled"}:
        if production:
            raise CheckpointError("production requires Azure immutable audit checkpoints")
        return None
    if mode == "memory":
        if production:
            raise CheckpointError("memory audit checkpoints are development-only")
        return MemoryCheckpointStore({})
    if mode == "file":
        if production:
            raise CheckpointError("file audit checkpoints are development-only")
        raw_directory = os.environ.get("AIPOL_AUDIT_CHECKPOINT_FILE_DIR", "").strip()
        if not raw_directory:
            raise CheckpointError("file checkpoint mode requires AIPOL_AUDIT_CHECKPOINT_FILE_DIR")
        directory = Path(raw_directory)
        return FileCheckpointStore(directory)
    if mode == "azure_blob":
        return AzureBlobCheckpointStore(
            os.environ.get("AIPOL_AUDIT_CHECKPOINT_CONTAINER_URL", "").strip(),
            os.environ.get("AZURE_CLIENT_ID", "").strip(),
            os.environ.get("AIPOL_AUDIT_IMMUTABILITY_POLICY_RESOURCE_ID", "").strip(),
        )
    raise CheckpointError("unsupported audit checkpoint mode")


def _db_state(connection) -> tuple[str, list[dict]]:
    row = connection.execute(
        "SELECT value FROM aipol_admin_metadata WHERE key='db_instance_id'"
    ).fetchone()
    if not row:
        db_instance_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO aipol_admin_metadata(key,value) VALUES('db_instance_id',?)",
            (db_instance_id,),
        )
    else:
        db_instance_id = str(row["value"])
    rows = [
        dict(item)
        for item in connection.execute(
            "SELECT sequence,previous_hash,event_hash FROM aipol_admin_audit ORDER BY sequence"
        )
    ]
    return db_instance_id, rows


def _envelope(sequence: int, head_hash: str, previous_hash: str, db_instance_id: str) -> dict:
    return {
        "version": CHECKPOINT_VERSION,
        "sequence": sequence,
        "head_hash": head_hash,
        "previous_hash": previous_hash,
        "db_instance_id": db_instance_id,
        "schema_version": AUDIT_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def reconcile(connection_factory, *, fail: bool = False) -> dict:
    """Catch up immutable checkpoints and prove an exact local/remote head."""
    if _store is None:
        result = {"configured": False, "ready": False, "store": "disabled", "sequence": None, "error": "disabled"}
        if fail:
            raise CheckpointError("audit checkpoint store is disabled")
        return result
    try:
        keys = _keyset()
        active_key = _active_key_id(keys)
        with connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            db_instance_id, rows = _db_state(connection)
        checkpoints = [_verify(value, keys) for value in _store.list()]
        checkpoints.sort(key=lambda value: value["sequence"])
        if [value["sequence"] for value in checkpoints] != list(range(len(checkpoints))):
            raise CheckpointError("immutable audit checkpoint sequence has a gap or rollback")
        for checkpoint in checkpoints:
            if checkpoint["db_instance_id"] != db_instance_id:
                raise CheckpointError("audit checkpoint database instance does not match")
            sequence = checkpoint["sequence"]
            if sequence == 0:
                expected_head = expected_previous = GENESIS_HASH
            elif sequence <= len(rows):
                expected_head = rows[sequence - 1]["event_hash"]
                expected_previous = rows[sequence - 1]["previous_hash"]
            else:
                raise CheckpointError("immutable checkpoint is ahead of the SQLite audit chain")
            if not hmac.compare_digest(checkpoint["head_hash"], expected_head) or not hmac.compare_digest(
                checkpoint["previous_hash"], expected_previous
            ):
                raise CheckpointError("SQLite audit chain does not match immutable checkpoint history")
        next_sequence = len(checkpoints)
        if not checkpoints:
            if rows:
                raise CheckpointError("existing SQLite audit chain has no bootstrap checkpoint")
            envelope = _envelope(0, GENESIS_HASH, GENESIS_HASH, db_instance_id)
            _store.create(0, _signed(envelope, key_id=active_key, secret=keys[active_key]))
            next_sequence = 1
        for row in rows[next_sequence - 1 :]:
            sequence = int(row["sequence"])
            envelope = _envelope(sequence, row["event_hash"], row["previous_hash"], db_instance_id)
            _store.create(sequence, _signed(envelope, key_id=active_key, secret=keys[active_key]))
        final = [_verify(value, keys) for value in _store.list()]
        final.sort(key=lambda value: value["sequence"])
        expected_sequence = len(rows)
        if [value["sequence"] for value in final] != list(range(len(final))):
            raise CheckpointError("immutable audit checkpoint sequence changed during reconciliation")
        if any(value["db_instance_id"] != db_instance_id for value in final):
            raise CheckpointError("audit checkpoint database instance changed during reconciliation")
        if not final or final[-1]["sequence"] != expected_sequence:
            raise CheckpointError("immutable checkpoint head is not exact")
        expected_head = rows[-1]["event_hash"] if rows else GENESIS_HASH
        if not hmac.compare_digest(final[-1]["head_hash"], expected_head):
            raise CheckpointError("immutable checkpoint head differs from SQLite")
        return {
            "configured": True,
            "ready": True,
            "store": _store.name,
            "sequence": expected_sequence,
            "head_hash": expected_head,
            "db_instance_id": db_instance_id,
            "active_key_id": active_key,
            "error": None,
        }
    except (CheckpointError, OSError, urllib.error.URLError) as exc:
        if fail:
            raise CheckpointError(str(exc)) from exc
        return {"configured": True, "ready": False, "store": getattr(_store, "name", "unknown"), "sequence": None, "error": str(exc)}
