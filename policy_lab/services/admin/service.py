"""In-memory admin application service with explicit storage/auth adapter seams."""
from __future__ import annotations

from dataclasses import replace

from .audit import HashChainedAuditLog
from .models import (
    BatchRun,
    BatchStatus,
    ChatbotConfig,
    KnowledgeRecord,
    SourceConfig,
)
from .rbac import Action, Principal, SessionContext, SessionPolicy


class AdminService:
    """Domain core, not a production identity provider, database, or web admin."""

    def __init__(
        self,
        *,
        session_policy: SessionPolicy | None = None,
        audit_log: HashChainedAuditLog | None = None,
    ) -> None:
        self.session_policy = session_policy or SessionPolicy()
        self.audit_log = audit_log or HashChainedAuditLog()
        self.sources: dict[str, SourceConfig] = {}
        self.batch_runs: dict[str, BatchRun] = {}
        self.knowledge: dict[str, KnowledgeRecord] = {}
        self.chatbot_configs: dict[str, ChatbotConfig] = {}

    def _authorize(
        self,
        principal: Principal,
        session: SessionContext,
        action: Action,
        now_epoch: int,
    ) -> None:
        principal.require(action)
        self.session_policy.validate(session, action, now_epoch)

    def save_source(
        self,
        config: SourceConfig,
        *,
        principal: Principal,
        session: SessionContext,
        now_epoch: int,
        timestamp: str,
        event_id: str,
    ) -> SourceConfig:
        self._authorize(principal, session, Action.EDIT_SOURCE, now_epoch)
        self.sources[config.source_id] = config
        self._audit(event_id, timestamp, principal, "source.saved", "source", config.source_id)
        return config

    def queue_batch(
        self,
        run_id: str,
        source_ids: tuple[str, ...],
        *,
        principal: Principal,
        session: SessionContext,
        now_epoch: int,
        timestamp: str,
        event_id: str,
    ) -> BatchRun:
        self._authorize(principal, session, Action.RUN_BATCH, now_epoch)
        if not source_ids or any(source_id not in self.sources for source_id in source_ids):
            raise ValueError("batch sources must exist")
        run = BatchRun(run_id, source_ids, BatchStatus.QUEUED, principal.principal_id, timestamp)
        self.batch_runs[run_id] = run
        self._audit(event_id, timestamp, principal, "batch.queued", "batch", run_id)
        return run

    def add_knowledge(
        self,
        record: KnowledgeRecord,
        *,
        principal: Principal,
        session: SessionContext,
        now_epoch: int,
        timestamp: str,
        event_id: str,
    ) -> KnowledgeRecord:
        self._authorize(principal, session, Action.EDIT_KNOWLEDGE, now_epoch)
        if record.created_by != principal.principal_id:
            raise PermissionError("created_by must match authenticated principal")
        if record.source_id not in self.sources:
            raise ValueError("knowledge source must exist")
        self.knowledge[record.record_id] = record
        self._audit(event_id, timestamp, principal, "knowledge.created", "knowledge", record.record_id)
        return record

    def submit_knowledge(
        self,
        record_id: str,
        *,
        principal: Principal,
        session: SessionContext,
        now_epoch: int,
        timestamp: str,
        event_id: str,
    ) -> KnowledgeRecord:
        self._authorize(principal, session, Action.SUBMIT_KNOWLEDGE, now_epoch)
        record = self.knowledge[record_id].submit(principal.principal_id)
        self.knowledge[record_id] = record
        self._audit(event_id, timestamp, principal, "knowledge.submitted", "knowledge", record_id)
        return record

    def approve_knowledge(
        self,
        record_id: str,
        *,
        principal: Principal,
        session: SessionContext,
        now_epoch: int,
        timestamp: str,
        event_id: str,
    ) -> KnowledgeRecord:
        self._authorize(principal, session, Action.APPROVE_KNOWLEDGE, now_epoch)
        record = self.knowledge[record_id].approve(principal.principal_id, timestamp)
        self.knowledge[record_id] = record
        self._audit(event_id, timestamp, principal, "knowledge.approved", "knowledge", record_id)
        return record

    def save_chatbot_config(
        self,
        config: ChatbotConfig,
        *,
        principal: Principal,
        session: SessionContext,
        now_epoch: int,
        timestamp: str,
        event_id: str,
    ) -> ChatbotConfig:
        self._authorize(principal, session, Action.CONFIGURE_CHATBOT, now_epoch)
        self.chatbot_configs[config.config_id] = config
        self._audit(event_id, timestamp, principal, "chatbot.configured", "chatbot", config.config_id)
        return config

    def finish_batch(
        self,
        run_id: str,
        *,
        succeeded: bool,
        principal: Principal,
        session: SessionContext,
        now_epoch: int,
        timestamp: str,
        event_id: str,
        error_code: str | None = None,
    ) -> BatchRun:
        self._authorize(principal, session, Action.RUN_BATCH, now_epoch)
        current = self.batch_runs[run_id]
        run = replace(
            current,
            status=BatchStatus.SUCCEEDED if succeeded else BatchStatus.FAILED,
            finished_at=timestamp,
            error_code=None if succeeded else error_code or "unspecified",
        )
        self.batch_runs[run_id] = run
        self._audit(event_id, timestamp, principal, "batch.finished", "batch", run_id)
        return run

    def _audit(
        self,
        event_id: str,
        timestamp: str,
        principal: Principal,
        action: str,
        resource_type: str,
        resource_id: str,
    ) -> None:
        self.audit_log.append(
            event_id=event_id,
            timestamp=timestamp,
            actor_id=principal.principal_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload={},
        )

