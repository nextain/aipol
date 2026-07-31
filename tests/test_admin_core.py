from __future__ import annotations

from dataclasses import replace

import pytest

from policy_lab.services.admin.audit import HashChainedAuditLog
from policy_lab.services.admin.models import (
    BatchConfig,
    ChatbotConfig,
    KnowledgeConfig,
    KnowledgeRecord,
    KnowledgeState,
    SourceConfig,
)
from policy_lab.services.admin.rbac import Action, Principal, Role, SessionContext, SessionPolicy
from policy_lab.services.admin.service import AdminService


NOW = 1_000_000
STAMP = "2026-07-28T12:00:00Z"


def principal(name: str, role: Role) -> Principal:
    return Principal(name, frozenset({role}))


def session(*, mfa: bool = True) -> SessionContext:
    return SessionContext("session-1", NOW - 100, NOW - 10, NOW - 20 if mfa else None)


def source() -> SourceConfig:
    return SourceConfig("kaps", "KAPS", "https://kaps.or.kr", ("kaps.or.kr",))


def call(service: AdminService, method: str, *args, actor: Principal, event: str, **kwargs):
    return getattr(service, method)(
        *args,
        principal=actor,
        session=session(),
        now_epoch=NOW,
        timestamp=STAMP,
        event_id=event,
        **kwargs,
    )


def test_editor_approver_separation_and_audit_chain() -> None:
    service = AdminService()
    editor = principal("editor-1", Role.EDITOR)
    approver = principal("approver-1", Role.APPROVER)
    call(service, "save_source", source(), actor=editor, event="e1")
    record = KnowledgeRecord(
        "knowledge-1", "kaps", "행사", "공식 행사 자료", KnowledgeState.DRAFT, "editor-1", STAMP
    )
    call(service, "add_knowledge", record, actor=editor, event="e2")
    call(service, "submit_knowledge", "knowledge-1", actor=editor, event="e3")
    approved = call(service, "approve_knowledge", "knowledge-1", actor=approver, event="e4")
    assert approved.state is KnowledgeState.APPROVED
    assert approved.approved_by == "approver-1"
    assert service.audit_log.verify()
    assert [event.action for event in service.audit_log.events()] == [
        "source.saved", "knowledge.created", "knowledge.submitted", "knowledge.approved"
    ]


def test_submitter_cannot_self_approve_even_with_both_roles() -> None:
    record = KnowledgeRecord(
        "k", "s", "t", "body", KnowledgeState.DRAFT, "dual", STAMP
    ).submit("dual")
    with pytest.raises(PermissionError, match="cannot approve"):
        record.approve("dual", STAMP)


def test_roles_do_not_implicitly_inherit_unrelated_privileges() -> None:
    with pytest.raises(PermissionError):
        principal("admin", Role.ADMIN).require(Action.APPROVE_KNOWLEDGE)
    with pytest.raises(PermissionError):
        principal("approver", Role.APPROVER).require(Action.EDIT_KNOWLEDGE)


def test_privileged_actions_require_fresh_mfa_and_session() -> None:
    policy = SessionPolicy()
    with pytest.raises(PermissionError, match="MFA required"):
        policy.validate(session(mfa=False), Action.EDIT_SOURCE, NOW)
    stale = replace(session(), last_seen_at_epoch=NOW - policy.idle_timeout_seconds - 1)
    with pytest.raises(PermissionError, match="idle timeout"):
        policy.validate(stale, Action.READ, NOW)
    policy.validate(session(mfa=False), Action.READ, NOW)


def test_audit_payload_is_copied_and_tampering_is_detected() -> None:
    log = HashChainedAuditLog()
    payload = {"status": "draft"}
    event = log.append(
        event_id="e1", timestamp=STAMP, actor_id="editor", action="create",
        resource_type="knowledge", resource_id="k1", payload=payload,
    )
    payload["status"] = "approved"
    assert event.payload == {"status": "draft"}
    assert log.verify()
    tampered = (replace(event, action="approve"),)
    assert not log.verify(tampered)
    with pytest.raises(ValueError, match="duplicate"):
        log.append(
            event_id="e1", timestamp=STAMP, actor_id="editor", action="retry",
            resource_type="knowledge", resource_id="k1",
        )


def test_source_batch_and_chatbot_configuration_contracts() -> None:
    service = AdminService()
    editor = principal("editor", Role.EDITOR)
    operator = principal("operator", Role.OPERATOR)
    admin = principal("admin", Role.ADMIN)
    call(service, "save_source", source(), actor=editor, event="e1")
    batch = call(service, "queue_batch", "run-1", ("kaps",), actor=operator, event="e2")
    assert batch.status.value == "queued"
    finished = call(
        service, "finish_batch", "run-1", succeeded=True, actor=operator, event="e3"
    )
    assert finished.status.value == "succeeded"
    config = ChatbotConfig("public", monthly_budget_units=1000, enabled=True)
    saved = call(service, "save_chatbot_config", config, actor=admin, event="e4")
    assert saved.enabled
    assert service.audit_log.verify()


def test_configuration_validation_fails_closed() -> None:
    with pytest.raises(ValueError, match="https"):
        SourceConfig("bad", "Bad", "http://example.com", ("example.com",))
    with pytest.raises(ValueError, match="positive budget"):
        ChatbotConfig("bad", enabled=True)
    batch = BatchConfig("daily", ("kaps",), "0 1 * * *", maximum_items=50)
    knowledge = KnowledgeConfig("public")
    assert batch.maximum_items == 50
    assert knowledge.distinct_approver_required
    with pytest.raises(ValueError, match="cannot be disabled"):
        KnowledgeConfig("unsafe", distinct_approver_required=False)
