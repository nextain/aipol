"""Authorization and session-policy contracts for an external identity adapter."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    VIEWER = "viewer"
    EDITOR = "editor"
    APPROVER = "approver"
    OPERATOR = "operator"
    AUDITOR = "auditor"
    ADMIN = "admin"


class Action(str, Enum):
    READ = "read"
    EDIT_SOURCE = "edit_source"
    EDIT_KNOWLEDGE = "edit_knowledge"
    SUBMIT_KNOWLEDGE = "submit_knowledge"
    APPROVE_KNOWLEDGE = "approve_knowledge"
    REVOKE_KNOWLEDGE = "revoke_knowledge"
    RUN_BATCH = "run_batch"
    CONFIGURE_CHATBOT = "configure_chatbot"
    MANAGE_ADMISSION = "manage_admission"
    READ_AUDIT = "read_audit"
    MAINTAIN_SERVICE = "maintain_service"


_ALLOWED: dict[Role, frozenset[Action]] = {
    Role.VIEWER: frozenset({Action.READ}),
    Role.EDITOR: frozenset(
        {Action.READ, Action.EDIT_SOURCE, Action.EDIT_KNOWLEDGE, Action.SUBMIT_KNOWLEDGE}
    ),
    Role.APPROVER: frozenset(
        {Action.READ, Action.APPROVE_KNOWLEDGE, Action.REVOKE_KNOWLEDGE}
    ),
    Role.OPERATOR: frozenset({Action.READ, Action.RUN_BATCH}),
    Role.AUDITOR: frozenset({Action.READ, Action.READ_AUDIT}),
    Role.ADMIN: frozenset({
        Action.READ, Action.CONFIGURE_CHATBOT, Action.MANAGE_ADMISSION, Action.MAINTAIN_SERVICE
    }),
}


@dataclass(frozen=True)
class Principal:
    principal_id: str
    roles: frozenset[Role]

    def __post_init__(self) -> None:
        if not self.principal_id.strip() or not self.roles:
            raise ValueError("principal_id and at least one role are required")

    def require(self, action: Action) -> None:
        if not any(action in _ALLOWED[role] for role in self.roles):
            raise PermissionError(f"{self.principal_id} is not allowed to {action.value}")


@dataclass(frozen=True)
class SessionContext:
    session_id: str
    authenticated_at_epoch: int
    last_seen_at_epoch: int
    mfa_verified_at_epoch: int | None = None


@dataclass(frozen=True)
class SessionPolicy:
    """Validation contract only; token issuance and MFA belong to an IdP adapter."""

    idle_timeout_seconds: int = 1800
    absolute_timeout_seconds: int = 28800
    require_mfa_for_privileged: bool = True
    mfa_max_age_seconds: int = 43200

    def validate(self, session: SessionContext, action: Action, now_epoch: int) -> None:
        if now_epoch < session.last_seen_at_epoch:
            raise PermissionError("invalid session clock")
        if now_epoch - session.last_seen_at_epoch > self.idle_timeout_seconds:
            raise PermissionError("session idle timeout")
        if now_epoch - session.authenticated_at_epoch > self.absolute_timeout_seconds:
            raise PermissionError("session absolute timeout")
        privileged = action is not Action.READ
        if self.require_mfa_for_privileged and privileged:
            if session.mfa_verified_at_epoch is None:
                raise PermissionError("MFA required")
            if now_epoch - session.mfa_verified_at_epoch > self.mfa_max_age_seconds:
                raise PermissionError("MFA verification expired")
