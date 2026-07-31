"""Persistent AIPOL knowledge/admin adapter on the event-tool SQLite database.

Knowledge content and workflow transitions are append-only.  Current state is
derived from the newest status event, so approval revocation survives restart and
cannot silently rewrite history.  Every mutation appends to a hash-chained audit
ledger in the same SQLite transaction.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse

import db
import aipol_audit_checkpoint
from policy_lab.services.chatbot.models import KnowledgeChunk, KnowledgeStatus


GENESIS_HASH = "0" * 64
KNOWLEDGE_STATES = {"draft", "in_review", "approved", "revoked"}
GENERATOR_MODES = {"off", "extractive", "azure_foundry"}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS aipol_admin_sources (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL,
  allowed_hosts TEXT NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
  public_source INTEGER NOT NULL CHECK(public_source IN (0,1)),
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aipol_admin_knowledge (
  id TEXT PRIMARY KEY, source_id TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY(source_id) REFERENCES aipol_admin_sources(id)
);
CREATE TABLE IF NOT EXISTS aipol_admin_knowledge_revisions (
  id TEXT PRIMARY KEY, knowledge_id TEXT NOT NULL, revision INTEGER NOT NULL,
  title TEXT NOT NULL, text TEXT NOT NULL, source_url TEXT NOT NULL,
  content_hash TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
  import_origin TEXT, import_record_id TEXT,
  UNIQUE(knowledge_id, revision),
  FOREIGN KEY(knowledge_id) REFERENCES aipol_admin_knowledge(id)
);
CREATE TABLE IF NOT EXISTS aipol_admin_knowledge_status (
  id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, state TEXT NOT NULL,
  actor TEXT NOT NULL, occurred_at TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
  FOREIGN KEY(revision_id) REFERENCES aipol_admin_knowledge_revisions(id)
);
CREATE TABLE IF NOT EXISTS aipol_admin_batch_configs (
  id TEXT PRIMARY KEY, source_ids TEXT NOT NULL, schedule_utc TEXT NOT NULL,
  maximum_items INTEGER NOT NULL CHECK(maximum_items > 0), enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
  updated_by TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aipol_admin_batch_runs (
  id TEXT PRIMARY KEY, config_id TEXT NOT NULL, status TEXT NOT NULL,
  requested_by TEXT NOT NULL, requested_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, error_code TEXT,
  azure_job_resource_id TEXT, azure_execution_name TEXT,
  FOREIGN KEY(config_id) REFERENCES aipol_admin_batch_configs(id)
);
CREATE TABLE IF NOT EXISTS aipol_admin_chatbot_config (
  id TEXT PRIMARY KEY CHECK(id='public'), enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
  generator_mode TEXT NOT NULL, allow_extractive_fallback INTEGER NOT NULL CHECK(allow_extractive_fallback IN (0,1)),
  retrieval_limit INTEGER NOT NULL CHECK(retrieval_limit > 0),
  minimum_score REAL NOT NULL CHECK(minimum_score > 0 AND minimum_score <= 1),
  minimum_claim_support REAL NOT NULL CHECK(minimum_claim_support > 0 AND minimum_claim_support <= 1),
  monthly_budget_units INTEGER NOT NULL CHECK(monthly_budget_units >= 0),
  updated_by TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aipol_admin_chatbot_usage (
  month_utc TEXT PRIMARY KEY, used_units INTEGER NOT NULL CHECK(used_units >= 0), updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aipol_admin_audit (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
  timestamp TEXT NOT NULL, actor_id TEXT NOT NULL, action TEXT NOT NULL,
  resource_type TEXT NOT NULL, resource_id TEXT NOT NULL, payload_json TEXT NOT NULL,
  previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS aipol_admin_metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aipol_admin_knowledge_source ON aipol_admin_knowledge(source_id);
CREATE INDEX IF NOT EXISTS idx_aipol_admin_status_revision ON aipol_admin_knowledge_status(revision_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_aipol_admin_import_record
ON aipol_admin_knowledge_revisions(import_origin, import_record_id)
WHERE import_origin IS NOT NULL AND import_record_id IS NOT NULL;
CREATE TRIGGER IF NOT EXISTS aipol_admin_revision_no_update BEFORE UPDATE ON aipol_admin_knowledge_revisions
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_admin_revision_no_delete BEFORE DELETE ON aipol_admin_knowledge_revisions
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_admin_status_no_update BEFORE UPDATE ON aipol_admin_knowledge_status
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_admin_status_no_delete BEFORE DELETE ON aipol_admin_knowledge_status
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_admin_audit_no_update BEFORE UPDATE ON aipol_admin_audit
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_admin_audit_no_delete BEFORE DELETE ON aipol_admin_audit
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
"""


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _audit_body(row: sqlite3.Row | dict, *, sequence: int, previous_hash: str) -> dict:
    return {
        "sequence": sequence,
        "event_id": row["event_id"],
        "timestamp": row["timestamp"],
        "actor_id": row["actor_id"],
        "action": row["action"],
        "resource_type": row["resource_type"],
        "resource_id": row["resource_id"],
        "payload_json": row["payload_json"],
        "previous_hash": previous_hash,
    }


def _audit_rows_valid(rows: list[sqlite3.Row], *, include_sequence: bool) -> bool:
    previous = GENESIS_HASH
    for expected_sequence, row in enumerate(rows, start=1):
        if row["sequence"] != expected_sequence or row["previous_hash"] != previous:
            return False
        body = _audit_body(row, sequence=expected_sequence, previous_hash=previous)
        if not include_sequence:
            body.pop("sequence")
        calculated = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
        if row["event_hash"] != calculated:
            return False
        previous = row["event_hash"]
    return True


def _migrate_audit_sequence_hashes(connection: sqlite3.Connection) -> None:
    """Upgrade a verified legacy chain to sequence-bound hashes atomically."""
    rows = connection.execute("SELECT * FROM aipol_admin_audit ORDER BY sequence").fetchall()
    if _audit_rows_valid(rows, include_sequence=True):
        return
    if not _audit_rows_valid(rows, include_sequence=False):
        raise RuntimeError("AIPOL 관리자 감사 로그 legacy 해시 체인이 손상되었습니다")
    connection.execute("DROP TRIGGER IF EXISTS aipol_admin_audit_no_update")
    connection.execute("DROP TRIGGER IF EXISTS aipol_admin_audit_no_delete")
    previous = GENESIS_HASH
    for sequence, row in enumerate(rows, start=1):
        body = _audit_body(row, sequence=sequence, previous_hash=previous)
        event_hash = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
        connection.execute(
            "UPDATE aipol_admin_audit SET previous_hash=?,event_hash=? WHERE sequence=?",
            (previous, event_hash, sequence),
        )
        previous = event_hash
    connection.execute(
        "CREATE TRIGGER aipol_admin_audit_no_update BEFORE UPDATE ON aipol_admin_audit "
        "BEGIN SELECT RAISE(ABORT, 'append-only'); END"
    )
    connection.execute(
        "CREATE TRIGGER aipol_admin_audit_no_delete BEFORE DELETE ON aipol_admin_audit "
        "BEGIN SELECT RAISE(ABORT, 'append-only'); END"
    )


def init() -> None:
    with db._conn() as connection:
        connection.executescript(_SCHEMA)
        connection.execute("BEGIN IMMEDIATE")
        _migrate_audit_sequence_hashes(connection)
        existing = {row["name"] for row in connection.execute("PRAGMA table_info(aipol_admin_batch_runs)")}
        for name in ("started_at", "azure_job_resource_id", "azure_execution_name"):
            if name not in existing:
                connection.execute(f"ALTER TABLE aipol_admin_batch_runs ADD COLUMN {name} TEXT")
        connection.execute(
            """INSERT OR IGNORE INTO aipol_admin_chatbot_config
               (id,enabled,generator_mode,allow_extractive_fallback,retrieval_limit,minimum_score,
                minimum_claim_support,monthly_budget_units,updated_by,updated_at)
               VALUES('public',0,'off',0,4,0.2,0.2,0,'system',?)""",
            (_now(),),
        )
    if not verify_audit_chain():
        raise RuntimeError("AIPOL 관리자 감사 로그 해시 체인이 손상되었습니다")


def _append_audit(
    connection: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    payload: dict | None = None,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> None:
    previous = connection.execute(
        "SELECT sequence,event_hash FROM aipol_admin_audit ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    previous_hash = previous["event_hash"] if previous else GENESIS_HASH
    sequence = int(previous["sequence"]) + 1 if previous else 1
    count = connection.execute("SELECT COUNT(*) FROM aipol_admin_audit").fetchone()[0]
    if sequence != count + 1:
        raise RuntimeError("AIPOL 관리자 감사 로그 sequence가 연속적이지 않습니다")
    event_id = event_id or _id("audit")
    timestamp = timestamp or _now()
    payload_json = _canonical(payload or {})
    row = {
        "sequence": sequence,
        "event_id": event_id,
        "timestamp": timestamp,
        "actor_id": actor,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "payload_json": payload_json,
        "previous_hash": previous_hash,
    }
    event_hash = hashlib.sha256(_canonical(row).encode("utf-8")).hexdigest()
    connection.execute(
        """INSERT INTO aipol_admin_audit
           (sequence,event_id,timestamp,actor_id,action,resource_type,resource_id,payload_json,previous_hash,event_hash)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (*row.values(), event_hash),
    )


def verify_audit_chain() -> bool:
    with db._conn() as connection:
        rows = connection.execute("SELECT * FROM aipol_admin_audit ORDER BY sequence").fetchall()
    return _audit_rows_valid(rows, include_sequence=True)


def reconcile_external_checkpoint(*, fail: bool = False) -> dict:
    """Anchor and verify the committed audit head outside the SQLite trust boundary."""
    if not verify_audit_chain():
        if fail:
            raise aipol_audit_checkpoint.CheckpointError("SQLite audit hash chain is invalid")
        return {
            "configured": True,
            "ready": False,
            "store": "unknown",
            "sequence": None,
            "error": "SQLite audit hash chain is invalid",
        }
    return aipol_audit_checkpoint.reconcile(db._conn, fail=fail)


def list_audit(limit: int = 200) -> list[dict]:
    with db._conn() as connection:
        return [
            {**dict(row), "payload": json.loads(row["payload_json"])}
            for row in connection.execute(
                "SELECT * FROM aipol_admin_audit ORDER BY sequence DESC LIMIT ?", (min(max(limit, 1), 500),)
            )
        ]


def append_external_audit(
    *, actor: str, action: str, resource_type: str, resource_id: str, payload: dict
) -> None:
    """Append an authenticated mutation from another AIPOL bounded context."""
    if not all(value.strip() for value in (actor, action, resource_type, resource_id)):
        raise ValueError("audit actor, action, resource type, and resource id are required")
    if not isinstance(payload, dict):
        raise ValueError("audit payload must be an object")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _append_audit(
            connection,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
        )
    if aipol_audit_checkpoint.configured():
        reconcile_external_checkpoint(fail=True)


def drain_experiment_audit_outbox(limit: int = 200) -> int:
    """Atomically move durable experiment audit events into the hash chain."""
    delivered = 0
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            "SELECT * FROM aipol_experiment_audit_outbox WHERE delivered_at IS NULL "
            "ORDER BY created_at,event_id LIMIT ?", (min(max(limit, 1), 1000),)
        ).fetchall()
        for row in rows:
            existing = connection.execute(
                "SELECT 1 FROM aipol_admin_audit WHERE event_id=?", (row["event_id"],)
            ).fetchone()
            if not existing:
                _append_audit(
                    connection, actor=row["actor"], action=row["action"],
                    resource_type="experiment", resource_id=row["experiment_id"],
                    payload=json.loads(row["payload_json"]), event_id=row["event_id"],
                    timestamp=row["created_at"],
                )
            connection.execute(
                "UPDATE aipol_experiment_audit_outbox SET delivered_at=? WHERE event_id=?",
                (_now(), row["event_id"]),
            )
            delivered += 1
    if delivered and aipol_audit_checkpoint.configured():
        reconcile_external_checkpoint(fail=True)
    return delivered


_CREDENTIAL_QUERY_KEYS = frozenset({
    "token", "access_token", "id_token", "api_key", "apikey", "key", "secret",
    "client_secret", "password", "passwd", "pwd", "credential", "credentials",
    "auth", "authorization", "signature", "sig", "sas",
})
_SAFE_PUBLIC_QUERY_KEYS = frozenset({"p", "viewmode", "reqidx"})


def _sanitized_public_url(value: str, *, allowed_hosts: tuple[str, ...] | None = None) -> str:
    candidate = value.strip()
    parsed = urlparse(candidate)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("공개 URL 포트가 올바르지 않습니다") from exc
    try:
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ValueError("공개 URL query 형식이 올바르지 않습니다") from exc
    query_keys = {key.strip().casefold() for key, _ in query_pairs}
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.fragment)
        or port not in (None, 443)
        or query_keys & _CREDENTIAL_QUERY_KEYS
        or not query_keys <= _SAFE_PUBLIC_QUERY_KEYS
        or ";" in parsed.query
    ):
        raise ValueError("공개 URL에는 HTTPS 기본 포트와 비자격증명 query만 사용할 수 있습니다")
    host = parsed.hostname.lower()
    if allowed_hosts is not None and host not in allowed_hosts:
        raise ValueError("지식 원문 URL은 출처 허용 호스트의 HTTPS 주소여야 합니다")
    # Rebuild authority from the parsed hostname so userinfo or ambiguous netloc
    # can never survive into a public citation even if storage was externally altered.
    authority = f"[{host}]" if ":" in host else host
    safe_query = urlencode(query_pairs, doseq=True)
    return parsed._replace(netloc=authority, query=safe_query, fragment="").geturl()


def _validate_source(value: dict) -> tuple[str, str, str, tuple[str, ...], bool, bool]:
    source_id = str(value.get("id") or "").strip()
    name = str(value.get("name") or "").strip()
    base_url = str(value.get("base_url") or "").strip()
    allowed_hosts = tuple(str(host).lower().strip() for host in value.get("allowed_hosts") or ())
    if not source_id or not name:
        raise ValueError("출처 ID·이름과 절대 HTTPS base_url이 필요합니다")
    if not allowed_hosts or any(not host or "/" in host for host in allowed_hosts):
        raise ValueError("allowed_hosts에는 호스트 이름이 필요합니다")
    sanitized_base_url = _sanitized_public_url(base_url, allowed_hosts=allowed_hosts)
    if urlparse(sanitized_base_url).hostname.lower() not in allowed_hosts:
        raise ValueError("base_url 호스트가 allowed_hosts에 포함되어야 합니다")
    return (
        source_id, name, sanitized_base_url, allowed_hosts,
        bool(value.get("enabled", True)), bool(value.get("public_source", True)),
    )


def save_source(value: dict, actor: str) -> dict:
    source_id, name, base_url, hosts, enabled, public_source = _validate_source(value)
    now = _now()
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("SELECT created_by,created_at FROM aipol_admin_sources WHERE id=?", (source_id,)).fetchone()
        if existing:
            current = get_source(source_id)
            approved = connection.execute(
                """SELECT 1 FROM aipol_admin_knowledge k
                   JOIN aipol_admin_knowledge_revisions r ON r.knowledge_id=k.id
                   WHERE k.source_id=? AND r.revision=(SELECT MAX(r2.revision) FROM aipol_admin_knowledge_revisions r2 WHERE r2.knowledge_id=k.id)
                   AND (SELECT s.state FROM aipol_admin_knowledge_status s WHERE s.revision_id=r.id ORDER BY s.rowid DESC LIMIT 1)='approved'
                   LIMIT 1""",
                (source_id,),
            ).fetchone()
            boundary_changed = (
                current["base_url"] != base_url
                or tuple(current["allowed_hosts"]) != hosts
                or current["public_source"] != public_source
            )
            if approved and boundary_changed:
                raise ValueError("승인 지식이 있는 출처의 URL·허용 호스트·공개 경계는 변경할 수 없습니다")
        created_by, created_at = (existing["created_by"], existing["created_at"]) if existing else (actor, now)
        connection.execute(
            """INSERT INTO aipol_admin_sources
               (id,name,base_url,allowed_hosts,enabled,public_source,created_by,created_at,updated_by,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name,base_url=excluded.base_url,
                 allowed_hosts=excluded.allowed_hosts,enabled=excluded.enabled,public_source=excluded.public_source,
                 updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
            (source_id, name, base_url, _canonical(hosts), int(enabled), int(public_source),
             created_by, created_at, actor, now),
        )
        _append_audit(connection, actor=actor, action="source.saved", resource_type="source", resource_id=source_id)
    return get_source(source_id)


def get_source(source_id: str) -> dict:
    with db._conn() as connection:
        row = connection.execute("SELECT * FROM aipol_admin_sources WHERE id=?", (source_id,)).fetchone()
    if not row:
        raise KeyError(source_id)
    result = dict(row)
    result["allowed_hosts"] = json.loads(result["allowed_hosts"])
    result["enabled"] = bool(result["enabled"])
    result["public_source"] = bool(result["public_source"])
    return result


def list_sources() -> list[dict]:
    with db._conn() as connection:
        ids = [row["id"] for row in connection.execute("SELECT id FROM aipol_admin_sources ORDER BY name,id")]
    return [get_source(source_id) for source_id in ids]


def _validate_knowledge(source_id: str, title: str, text: str, source_url: str) -> str:
    source = get_source(source_id)
    if not title.strip() or not text.strip() or len(title) > 500 or len(text) > 12_000:
        raise ValueError("지식 제목·본문 길이가 올바르지 않습니다")
    return _sanitized_public_url(source_url, allowed_hosts=tuple(source["allowed_hosts"]))


def create_knowledge(value: dict, actor: str, *, import_origin: str | None = None, import_record_id: str | None = None) -> dict:
    source_id = str(value.get("source_id") or "").strip()
    title, text, source_url = (str(value.get(key) or "").strip() for key in ("title", "text", "source_url"))
    source_url = _validate_knowledge(source_id, title, text, source_url)
    knowledge_id, revision_id, now = _id("kb"), _id("kbr"), _now()
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO aipol_admin_knowledge(id,source_id,created_by,created_at) VALUES(?,?,?,?)", (knowledge_id, source_id, actor, now))
        connection.execute(
            """INSERT INTO aipol_admin_knowledge_revisions
               (id,knowledge_id,revision,title,text,source_url,content_hash,created_by,created_at,import_origin,import_record_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (revision_id, knowledge_id, 1, title, text, source_url, _content_hash(text), actor, now, import_origin, import_record_id),
        )
        connection.execute("INSERT INTO aipol_admin_knowledge_status(id,revision_id,state,actor,occurred_at) VALUES(?,?,?,?,?)", (_id("kbs"), revision_id, "draft", actor, now))
        _append_audit(connection, actor=actor, action="knowledge.created", resource_type="knowledge", resource_id=knowledge_id, payload={"revision": 1, "content_hash": _content_hash(text)})
    return get_knowledge(knowledge_id)


def revise_knowledge(
    knowledge_id: str, value: dict, actor: str, expected_revision: int | None = None
) -> dict:
    current = get_knowledge(knowledge_id)
    source_id = current["source_id"]
    title = str(value.get("title") or current["title"]).strip()
    text = str(value.get("text") or "").strip()
    source_url = str(value.get("source_url") or current["source_url"]).strip()
    source_url = _validate_knowledge(source_id, title, text, source_url)
    expected = int(current["revision"]) if expected_revision is None else int(expected_revision)
    revision_id, now = _id("kbr"), _now()
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        live_rows = _latest_rows(connection, knowledge_id)
        if not live_rows:
            raise KeyError(knowledge_id)
        live = live_rows[0]
        if live["revision"] != expected or live["id"] != current["revision_id"]:
            raise ValueError("동시에 새 개정본이 생성되었습니다. 다시 불러와 주세요")
        if live["state"] not in {"draft", "revoked"}:
            raise ValueError("초안 또는 철회된 지식만 새 개정본을 만들 수 있습니다")
        revision = int(live["revision"]) + 1
        connection.execute(
            """INSERT INTO aipol_admin_knowledge_revisions
               (id,knowledge_id,revision,title,text,source_url,content_hash,created_by,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (revision_id, knowledge_id, revision, title, text, source_url, _content_hash(text), actor, now),
        )
        connection.execute("INSERT INTO aipol_admin_knowledge_status(id,revision_id,state,actor,occurred_at) VALUES(?,?,?,?,?)", (_id("kbs"), revision_id, "draft", actor, now))
        _append_audit(connection, actor=actor, action="knowledge.revised", resource_type="knowledge", resource_id=knowledge_id, payload={"revision": revision, "content_hash": _content_hash(text)})
    return get_knowledge(knowledge_id)


def _latest_rows(connection: sqlite3.Connection, knowledge_id: str | None = None):
    where, args = ("WHERE k.id=?", (knowledge_id,)) if knowledge_id else ("", ())
    return connection.execute(
        f"""SELECT k.id knowledge_id,k.source_id,r.*,
          (SELECT s.state FROM aipol_admin_knowledge_status s WHERE s.revision_id=r.id ORDER BY s.rowid DESC LIMIT 1) state,
          (SELECT s.actor FROM aipol_admin_knowledge_status s WHERE s.revision_id=r.id ORDER BY s.rowid DESC LIMIT 1) status_actor,
          (SELECT s.occurred_at FROM aipol_admin_knowledge_status s WHERE s.revision_id=r.id ORDER BY s.rowid DESC LIMIT 1) status_at
          FROM aipol_admin_knowledge k JOIN aipol_admin_knowledge_revisions r ON r.knowledge_id=k.id
          AND r.revision=(SELECT MAX(r2.revision) FROM aipol_admin_knowledge_revisions r2 WHERE r2.knowledge_id=k.id)
          {where} ORDER BY r.created_at DESC""",
        args,
    ).fetchall()


def get_knowledge(knowledge_id: str) -> dict:
    with db._conn() as connection:
        rows = _latest_rows(connection, knowledge_id)
        history = [dict(row) for row in connection.execute(
            """SELECT s.state,s.actor,s.occurred_at,s.reason,r.revision FROM aipol_admin_knowledge_status s
               JOIN aipol_admin_knowledge_revisions r ON r.id=s.revision_id
               WHERE r.knowledge_id=? ORDER BY s.rowid""", (knowledge_id,)
        )]
    if not rows:
        raise KeyError(knowledge_id)
    result = dict(rows[0])
    result["revision_id"] = result["id"]
    result["id"] = result.pop("knowledge_id")
    result["history"] = history
    return result


def list_knowledge() -> list[dict]:
    with db._conn() as connection:
        ids = [row["knowledge_id"] for row in _latest_rows(connection)]
    return [get_knowledge(knowledge_id) for knowledge_id in ids]


def transition_knowledge(
    knowledge_id: str,
    target: str,
    actor: str,
    reason: str = "",
    expected_revision: int | None = None,
) -> dict:
    current = get_knowledge(knowledge_id)
    expected = int(current["revision"]) if expected_revision is None else int(expected_revision)
    now = _now()
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        live_rows = _latest_rows(connection, knowledge_id)
        if not live_rows:
            raise KeyError(knowledge_id)
        live = live_rows[0]
        if live["revision"] != expected or live["id"] != current["revision_id"]:
            raise ValueError("동시에 개정본이 변경되었습니다. 다시 불러와 주세요")
        allowed = {"draft": {"in_review"}, "in_review": {"approved"}, "approved": {"revoked"}, "revoked": set()}
        if target not in allowed.get(live["state"], set()):
            raise ValueError(f"허용되지 않은 지식 상태 전이: {live['state']} -> {target}")
        if target == "approved":
            submitter_row = connection.execute(
                """SELECT actor FROM aipol_admin_knowledge_status
                   WHERE revision_id=? AND state='in_review' ORDER BY rowid DESC LIMIT 1""",
                (live["id"],),
            ).fetchone()
            submitter = submitter_row["actor"] if submitter_row else None
            if actor in {live["created_by"], submitter}:
                raise PermissionError("작성자/검토 요청자는 같은 개정본을 승인할 수 없습니다")
        current_state = connection.execute(
            "SELECT state FROM aipol_admin_knowledge_status WHERE revision_id=? ORDER BY rowid DESC LIMIT 1",
            (live["id"],),
        ).fetchone()
        if not current_state or current_state["state"] != live["state"]:
            raise ValueError("동시에 상태가 변경되었습니다. 다시 불러와 주세요")
        connection.execute("INSERT INTO aipol_admin_knowledge_status(id,revision_id,state,actor,occurred_at,reason) VALUES(?,?,?,?,?,?)", (_id("kbs"), live["id"], target, actor, now, reason.strip()))
        _append_audit(connection, actor=actor, action=f"knowledge.{target}", resource_type="knowledge", resource_id=knowledge_id, payload={"revision": live["revision"], "reason": reason.strip()})
    return get_knowledge(knowledge_id)


def approved_chunks() -> list[KnowledgeChunk]:
    # One explicit read transaction binds the latest revision, latest approval
    # state, and source publication boundary to the same SQLite snapshot.
    with db._conn() as connection:
        connection.execute("BEGIN")
        rows = connection.execute(
            """WITH latest_revision AS (
                 SELECT knowledge_id, MAX(revision) AS revision
                 FROM aipol_admin_knowledge_revisions GROUP BY knowledge_id
               ), latest_status AS (
                 SELECT s.* FROM aipol_admin_knowledge_status s
                 WHERE s.rowid=(
                   SELECT MAX(s2.rowid) FROM aipol_admin_knowledge_status s2
                   WHERE s2.revision_id=s.revision_id
                 )
               )
               SELECT k.id AS knowledge_id,k.source_id,r.title,r.text,r.source_url,
                      st.actor AS approved_by,st.occurred_at AS approved_at,
                      src.allowed_hosts AS allowed_hosts
               FROM aipol_admin_knowledge k
               JOIN latest_revision lr ON lr.knowledge_id=k.id
               JOIN aipol_admin_knowledge_revisions r
                 ON r.knowledge_id=k.id AND r.revision=lr.revision
               JOIN latest_status st ON st.revision_id=r.id AND st.state='approved'
               JOIN aipol_admin_sources src ON src.id=k.source_id
               WHERE src.enabled=1 AND src.public_source=1
               ORDER BY r.created_at DESC,k.id"""
        ).fetchall()
        chunks = [
            KnowledgeChunk(
                chunk_id=row["knowledge_id"], source_id=row["source_id"],
                title=row["title"],
                source_url=_sanitized_public_url(
                    row["source_url"],
                    allowed_hosts=tuple(json.loads(row["allowed_hosts"])),
                ),
                text=row["text"],
                status=KnowledgeStatus.APPROVED, approved_by=row["approved_by"],
                approved_at=row["approved_at"],
            )
            for row in rows
        ]
        connection.commit()
    return chunks


def get_chatbot_config() -> dict:
    with db._conn() as connection:
        row = connection.execute("SELECT * FROM aipol_admin_chatbot_config WHERE id='public'").fetchone()
    result = dict(row)
    for key in ("enabled", "allow_extractive_fallback"):
        result[key] = bool(result[key])
    return result


def save_chatbot_config(value: dict, actor: str) -> dict:
    mode = str(value.get("generator_mode") or "off")
    enabled = bool(value.get("enabled", False))
    fallback = bool(value.get("allow_extractive_fallback", False))
    retrieval_limit = int(value.get("retrieval_limit", 4))
    minimum_score = float(value.get("minimum_score", 0.2))
    support = float(value.get("minimum_claim_support", 0.2))
    budget = int(value.get("monthly_budget_units", 0))
    if mode not in GENERATOR_MODES or retrieval_limit not in range(1, 11) or not (0 < minimum_score <= 1 and 0 < support <= 1) or budget < 0:
        raise ValueError("챗봇 설정 값이 올바르지 않습니다")
    if enabled and mode == "off":
        raise ValueError("활성 챗봇은 off 생성 모드를 사용할 수 없습니다")
    if mode == "azure_foundry" and enabled and budget <= 0:
        raise ValueError("Azure Foundry 활성화에는 양수 비용 상한이 필요합니다")
    now = _now()
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """UPDATE aipol_admin_chatbot_config SET enabled=?,generator_mode=?,allow_extractive_fallback=?,
               retrieval_limit=?,minimum_score=?,minimum_claim_support=?,monthly_budget_units=?,updated_by=?,updated_at=? WHERE id='public'""",
            (int(enabled), mode, int(fallback), retrieval_limit, minimum_score, support, budget, actor, now),
        )
        _append_audit(connection, actor=actor, action="chatbot.configured", resource_type="chatbot", resource_id="public", payload={"enabled": enabled, "generator_mode": mode, "allow_extractive_fallback": fallback, "monthly_budget_units": budget})
    return get_chatbot_config()


def reserve_chatbot_cost_unit() -> int:
    """Atomically reserve one provider-call unit without retaining the question."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        config = connection.execute(
            "SELECT generator_mode,enabled,monthly_budget_units FROM aipol_admin_chatbot_config WHERE id='public'"
        ).fetchone()
        if not config or not config["enabled"] or config["generator_mode"] != "azure_foundry":
            raise ValueError("유료 생성 모드가 활성화되지 않았습니다")
        used = connection.execute(
            "SELECT used_units FROM aipol_admin_chatbot_usage WHERE month_utc=?", (month,)
        ).fetchone()
        next_value = (used["used_units"] if used else 0) + 1
        if next_value > config["monthly_budget_units"]:
            raise ValueError("월간 챗봇 비용 상한에 도달했습니다")
        connection.execute(
            """INSERT INTO aipol_admin_chatbot_usage(month_utc,used_units,updated_at) VALUES(?,?,?)
               ON CONFLICT(month_utc) DO UPDATE SET used_units=excluded.used_units,updated_at=excluded.updated_at""",
            (month, next_value, _now()),
        )
    return next_value


def save_batch_config(value: dict, actor: str) -> dict:
    config_id = str(value.get("id") or "").strip()
    source_ids = tuple(str(item) for item in value.get("source_ids") or ())
    schedule = str(value.get("schedule_utc") or "manual").strip()
    maximum = int(value.get("maximum_items", 100))
    enabled = bool(value.get("enabled", False))
    if not config_id or not source_ids or maximum < 1 or maximum > 1000:
        raise ValueError("배치 설정 ID·출처·처리 상한이 필요합니다")
    for source_id in source_ids:
        get_source(source_id)
    now = _now()
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT INTO aipol_admin_batch_configs(id,source_ids,schedule_utc,maximum_items,enabled,updated_by,updated_at)
               VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET source_ids=excluded.source_ids,
               schedule_utc=excluded.schedule_utc,maximum_items=excluded.maximum_items,enabled=excluded.enabled,
               updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
            (config_id, _canonical(source_ids), schedule, maximum, int(enabled), actor, now),
        )
        _append_audit(connection, actor=actor, action="batch.configured", resource_type="batch_config", resource_id=config_id, payload={"enabled": enabled, "maximum_items": maximum})
    return get_batch_config(config_id)


def get_batch_config(config_id: str) -> dict:
    with db._conn() as connection:
        row = connection.execute("SELECT * FROM aipol_admin_batch_configs WHERE id=?", (config_id,)).fetchone()
    if not row:
        raise KeyError(config_id)
    result = dict(row); result["source_ids"] = json.loads(result["source_ids"]); result["enabled"] = bool(result["enabled"])
    return result


def list_batch_configs() -> list[dict]:
    with db._conn() as connection:
        ids = [row["id"] for row in connection.execute("SELECT id FROM aipol_admin_batch_configs ORDER BY id")]
    return [get_batch_config(config_id) for config_id in ids]


def request_batch(config_id: str, actor: str) -> dict:
    config = get_batch_config(config_id)
    if not config["enabled"]:
        raise ValueError("배치 kill switch가 OFF입니다")
    run_id, now = _id("batch"), _now()
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO aipol_admin_batch_runs(id,config_id,status,requested_by,requested_at) VALUES(?,?,?,?,?)", (run_id, config_id, "requested", actor, now))
        _append_audit(connection, actor=actor, action="batch.requested", resource_type="batch_run", resource_id=run_id, payload={"config_id": config_id})
    return get_batch_run(run_id)


def mark_batch_started(run_id: str, job_resource_id: str, execution_name: str, status: str, actor: str) -> dict:
    if status not in {"processing", "running", "started"}:
        status = "started"
    now = _now()
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute("SELECT status FROM aipol_admin_batch_runs WHERE id=?", (run_id,)).fetchone()
        if not current:
            raise KeyError(run_id)
        if current["status"] != "requested":
            raise ValueError("요청 상태의 배치만 시작할 수 있습니다")
        connection.execute(
            """UPDATE aipol_admin_batch_runs SET status=?,started_at=?,azure_job_resource_id=?,azure_execution_name=?
               WHERE id=?""",
            (status, now, job_resource_id, execution_name, run_id),
        )
        _append_audit(connection, actor=actor, action="batch.started", resource_type="batch_run", resource_id=run_id, payload={"execution_name": execution_name})
    return get_batch_run(run_id)


def mark_batch_dispatch_failed(run_id: str, error_code: str, actor: str) -> dict:
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE aipol_admin_batch_runs SET status='failed',finished_at=?,error_code=? WHERE id=? AND status='requested'",
            (_now(), error_code[:80], run_id),
        )
        _append_audit(connection, actor=actor, action="batch.dispatch_failed", resource_type="batch_run", resource_id=run_id, payload={"error_code": error_code[:80]})
    return get_batch_run(run_id)


def update_batch_remote_status(run_id: str, status: str, started_at: str | None, finished_at: str | None, actor: str) -> dict:
    normalized = status.lower()
    allowed = {"processing", "running", "succeeded", "failed", "stopped"}
    if normalized not in allowed:
        normalized = "processing"
    terminal = normalized in {"succeeded", "failed", "stopped"}
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if not connection.execute("SELECT 1 FROM aipol_admin_batch_runs WHERE id=?", (run_id,)).fetchone():
            raise KeyError(run_id)
        connection.execute(
            """UPDATE aipol_admin_batch_runs SET status=?,started_at=COALESCE(?,started_at),
               finished_at=CASE WHEN ? THEN COALESCE(?,finished_at) ELSE finished_at END WHERE id=?""",
            (normalized, started_at, int(terminal), finished_at or (_now() if terminal else None), run_id),
        )
        _append_audit(connection, actor=actor, action="batch.status_refreshed", resource_type="batch_run", resource_id=run_id, payload={"status": normalized})
    return get_batch_run(run_id)


def get_batch_run(run_id: str) -> dict:
    with db._conn() as connection:
        row = connection.execute("SELECT * FROM aipol_admin_batch_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise KeyError(run_id)
    return dict(row)


def list_batch_runs() -> list[dict]:
    with db._conn() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM aipol_admin_batch_runs ORDER BY requested_at DESC")]


def import_human_approved(value: dict, actor: str) -> dict:
    allowed = {"state", "origin", "record_id", "source_id", "title", "summary", "source_url", "public_export"}
    if set(value) - allowed:
        raise ValueError("raw/private 필드는 import 계약에 허용되지 않습니다")
    if value.get("state") != "human_approved" or value.get("public_export") is not True:
        raise ValueError("human_approved 공개 export만 import할 수 있습니다")
    if value.get("origin") not in {"policy_news", "naia-kb-compiler"}:
        raise ValueError("지원하지 않는 import origin입니다")
    record_id = str(value.get("record_id") or "").strip()
    if not record_id:
        raise ValueError("import record_id가 필요합니다")
    with db._conn() as connection:
        duplicate = connection.execute("SELECT knowledge_id FROM aipol_admin_knowledge_revisions WHERE import_origin=? AND import_record_id=?", (value["origin"], record_id)).fetchone()
    if duplicate:
        return get_knowledge(duplicate["knowledge_id"])
    # Import is deliberately a draft. A different approver must still approve it here.
    return create_knowledge({"source_id": value.get("source_id"), "title": value.get("title"), "text": value.get("summary"), "source_url": value.get("source_url")}, actor, import_origin=value["origin"], import_record_id=record_id)
