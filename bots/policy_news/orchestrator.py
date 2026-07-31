"""Idempotent, fail-closed orchestration for AIPOL policy-news AI processing."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar
from urllib.parse import urlparse

from adapters import TransientProviderError
from config import RuntimeConfig
from contracts import (
    ApprovalState,
    EditorialDraft,
    RunRecord,
    SourcePacket,
    idempotency_key,
    sha256_text,
)
from ports import DraftPort, KnowledgeCompilerPort, ReviewPort, RunStorePort


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_DIR = ROOT / "data-private" / "policy-news" / "runs"
PROMPT = Path(__file__).with_name("prompt.txt")
SOURCES_CONFIG = Path(__file__).with_name("sources.json")
T = TypeVar("T")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def configured_official_hosts() -> set[str]:
    config = json.loads(SOURCES_CONFIG.read_text(encoding="utf-8"))
    return {host.lower() for feed in config.get("feeds", []) for host in feed.get("allowed_hosts", [])}


class FileRunStore:
    """Portable JSON run store for development and low-volume scheduled jobs.

    Raw official-source text is kept beside the run in ``data-private`` and is
    never copied into a public record.  Production may replace this port with a
    database/blob adapter while retaining the same contract.
    """

    def __init__(self, root: Path = DEFAULT_STATE_DIR) -> None:
        self.root = root.resolve()
        project_root = ROOT.resolve()
        if self.root.is_relative_to(project_root):
            allowed_roots = ((project_root / "data-private").resolve(), (project_root / "tmp").resolve())
            if not any(self.root.is_relative_to(allowed) for allowed in allowed_roots):
                raise ValueError("policy-news state inside the repository must be under data-private/ or tmp/")
        self.runs = self.root / "records"
        self.sources = self.root / "sources"
        self.index = self.root / "idempotency"

    def _record_path(self, run_id: str) -> Path:
        return self.runs / f"{run_id}.json"

    def load_by_idempotency_key(self, key: str) -> RunRecord | None:
        index_path = self.index / f"{key}.txt"
        if not index_path.exists():
            return None
        run_id = index_path.read_text(encoding="utf-8").strip()
        path = self._record_path(run_id)
        if not path.exists():
            raise RuntimeError("idempotency index points to a missing run record")
        return RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_source(self, packet: SourcePacket) -> None:
        self.sources.mkdir(parents=True, exist_ok=True)
        path = self.sources / f"{packet.content_sha256}.json"
        payload = json.dumps(packet.provider_payload(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if path.exists():
            existing = SourcePacket.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if existing.content_sha256 != packet.content_sha256:
                raise RuntimeError("source artifact hash collision")
            return
        temp = path.with_suffix(f".{os.getpid()}.tmp")
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, path)

    def save(self, record: RunRecord) -> None:
        self.runs.mkdir(parents=True, exist_ok=True)
        self.index.mkdir(parents=True, exist_ok=True)
        index_path = self.index / f"{record.idempotency_key}.txt"
        if index_path.exists():
            existing_id = index_path.read_text(encoding="utf-8").strip()
            if existing_id != record.run_id:
                raise RuntimeError("idempotency key already belongs to a different run")
        else:
            try:
                fd = os.open(index_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(record.run_id + "\n")
            except FileExistsError:
                existing_id = index_path.read_text(encoding="utf-8").strip()
                if existing_id != record.run_id:
                    raise RuntimeError("concurrent idempotency conflict")
        path = self._record_path(record.run_id)
        temp = path.with_suffix(f".{os.getpid()}.tmp")
        temp.write_text(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)


class PolicyNewsOrchestrator:
    def __init__(
        self,
        *,
        config: RuntimeConfig,
        draft_port: DraftPort,
        review_port: ReviewPort,
        store: RunStorePort,
        knowledge_compiler: KnowledgeCompilerPort | None = None,
        clock: Callable[[], str] = utcnow,
        sleeper: Callable[[float], None] = time.sleep,
        allowed_hosts: set[str] | None = None,
    ) -> None:
        self.config = config
        self.draft_port = draft_port
        self.review_port = review_port
        self.knowledge_compiler = knowledge_compiler
        self.store = store
        self.clock = clock
        self.sleeper = sleeper
        self.allowed_hosts = {host.lower() for host in (allowed_hosts if allowed_hosts is not None else configured_official_hosts())}

    def _call(self, stage: str, record: RunRecord, operation: Callable[[], T]) -> T:
        for attempt in range(1, self.config.max_attempts + 1):
            record.attempts[stage] = attempt
            self.store.save(record)
            try:
                return operation()
            except TransientProviderError as exc:
                record.audit.append({"at": self.clock(), "actor": stage, "event": "transient_failure", "attempt": attempt, "error_type": type(exc).__name__})
                self.store.save(record)
                if attempt >= self.config.max_attempts:
                    raise
                self.sleeper(self.config.retry_base_seconds * (2 ** (attempt - 1)))
        raise AssertionError("retry loop exhausted unexpectedly")

    def run(self, raw_packet: dict[str, object]) -> RunRecord:
        packet = SourcePacket.from_dict(raw_packet)
        source_host = (urlparse(packet.source_url).hostname or "").lower()
        if source_host not in self.allowed_hosts:
            raise ValueError(f"source host is not allow-listed: {source_host}")
        prompt_hash = sha256_text(PROMPT.read_text(encoding="utf-8"))
        key = idempotency_key(packet, self.config.revision, prompt_hash)
        if not self.config.enabled:
            raise RuntimeError("policy-news kill switch is OFF")
        if self.config.dry_run and not (self.draft_port.name.startswith("mock") and self.review_port.name.startswith("mock")):
            raise RuntimeError("dry-run mode permits only deterministic mock adapters")
        if self.config.dry_run and self.knowledge_compiler is not None and not self.knowledge_compiler.name.startswith("mock"):
            raise RuntimeError("dry-run mode permits only a deterministic mock KB compiler")
        self.store.save_source(packet)
        record = self.store.load_by_idempotency_key(key)
        if record is None:
            now = self.clock()
            record = RunRecord(
                schema_version="1.0.0",
                run_id=key[:24],
                idempotency_key=key,
                state=ApprovalState.DISCOVERED,
                source=packet.public_source_metadata(),
                config_snapshot={**self.config.public_snapshot(), "prompt_sha256": prompt_hash},
                created_at=now,
                updated_at=now,
                audit=[{"at": now, "actor": "orchestrator", "from": None, "to": ApprovalState.DISCOVERED.value, "reason": "validated official-source packet"}],
            )
            self.store.save(record)

        # A provider/process failure leaves the last durable stage in place. A
        # retry resumes from that stage instead of repeating completed calls.
        if record.state == ApprovalState.DISCOVERED:
            draft = self._call("draft", record, lambda: self.draft_port.draft(packet))
            record.draft = asdict(draft)
            record.move(ApprovalState.DRAFTED, at=self.clock(), actor=self.draft_port.name, reason="bounded editorial draft created")
            self.store.save(record)
        elif record.draft is not None:
            draft = EditorialDraft(**record.draft)
        else:
            return record

        if record.state == ApprovalState.DRAFTED:
            review = self._call("review", record, lambda: self.review_port.review(packet, draft))
            record.review = asdict(review)
            if review.verdict != "PASS":
                record.move(ApprovalState.REVIEW_BLOCKED, at=self.clock(), actor=self.review_port.name, reason="adversarial review blocked publication")
                self.store.save(record)
                return record
            record.move(ApprovalState.REVIEW_PASSED, at=self.clock(), actor=self.review_port.name, reason="independent source comparison passed")
            self.store.save(record)

        if record.state == ApprovalState.REVIEW_PASSED and self.knowledge_compiler is not None:
            kb = self._call("kb_compile", record, lambda: self.knowledge_compiler.compile(packet, draft))
            record.kb = asdict(kb)
            record.move(ApprovalState.KB_COMPILED, at=self.clock(), actor=self.knowledge_compiler.name, reason="portable KB artifact compiled; human approval still required")
            self.store.save(record)
        return record

    def human_approve(self, key: str, *, actor: str, reason: str) -> RunRecord:
        if not actor.strip() or not reason.strip():
            raise ValueError("human approver and reason are required")
        record = self.store.load_by_idempotency_key(key)
        if record is None:
            raise KeyError("run not found")
        record.move(ApprovalState.HUMAN_APPROVED, at=self.clock(), actor=actor.strip(), reason=reason.strip())
        self.store.save(record)
        return record

    def mark_published(self, key: str, *, actor: str, reason: str) -> RunRecord:
        if not actor.strip() or not reason.strip():
            raise ValueError("publisher and reason are required")
        record = self.store.load_by_idempotency_key(key)
        if record is None:
            raise KeyError("run not found")
        record.move(ApprovalState.PUBLISHED, at=self.clock(), actor=actor.strip(), reason=reason.strip())
        self.store.save(record)
        return record
