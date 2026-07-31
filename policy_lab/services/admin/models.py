"""Configuration and workflow records for the integrated admin core."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    name: str
    base_url: str
    allowed_hosts: tuple[str, ...]
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.name.strip():
            raise ValueError("source_id and name are required")
        if not self.base_url.startswith("https://"):
            raise ValueError("source base_url must use https")
        if not self.allowed_hosts or any("/" in host or not host for host in self.allowed_hosts):
            raise ValueError("allowed_hosts must contain host names")


class BatchStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class BatchConfig:
    config_id: str
    source_ids: tuple[str, ...]
    schedule_utc: str
    maximum_items: int = 100
    enabled: bool = False

    def __post_init__(self) -> None:
        if not self.config_id.strip() or not self.source_ids:
            raise ValueError("batch config id and sources are required")
        if not self.schedule_utc.strip():
            raise ValueError("schedule_utc is required")
        if self.maximum_items < 1:
            raise ValueError("maximum_items must be positive")


@dataclass(frozen=True)
class BatchRun:
    run_id: str
    source_ids: tuple[str, ...]
    status: BatchStatus
    requested_by: str
    requested_at: str
    finished_at: str | None = None
    error_code: str | None = None


class KnowledgeState(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REVOKED = "revoked"


@dataclass(frozen=True)
class KnowledgeConfig:
    config_id: str
    maximum_chunk_characters: int = 4000
    allowed_languages: tuple[str, ...] = ("ko", "en")
    public_sources_only: bool = True
    distinct_approver_required: bool = True

    def __post_init__(self) -> None:
        if not self.config_id.strip() or self.maximum_chunk_characters < 1:
            raise ValueError("invalid knowledge configuration")
        if not self.allowed_languages:
            raise ValueError("at least one language is required")
        if not self.distinct_approver_required:
            raise ValueError("editor/approver separation cannot be disabled")


@dataclass(frozen=True)
class KnowledgeRecord:
    record_id: str
    source_id: str
    title: str
    text: str
    state: KnowledgeState
    created_by: str
    created_at: str
    submitted_by: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    revision: int = 1

    def submit(self, actor_id: str) -> "KnowledgeRecord":
        if self.state is not KnowledgeState.DRAFT:
            raise ValueError("only drafts may be submitted")
        return replace(self, state=KnowledgeState.IN_REVIEW, submitted_by=actor_id)

    def approve(self, actor_id: str, approved_at: str) -> "KnowledgeRecord":
        if self.state is not KnowledgeState.IN_REVIEW:
            raise ValueError("only records in review may be approved")
        if actor_id in {self.created_by, self.submitted_by}:
            raise PermissionError("the editor/submitter cannot approve the same record")
        return replace(
            self,
            state=KnowledgeState.APPROVED,
            approved_by=actor_id,
            approved_at=approved_at,
        )

    def revoke(self) -> "KnowledgeRecord":
        if self.state is not KnowledgeState.APPROVED:
            raise ValueError("only approved records may be revoked")
        return replace(self, state=KnowledgeState.REVOKED)


@dataclass(frozen=True)
class ChatbotConfig:
    config_id: str
    retrieval_limit: int = 4
    minimum_score: float = 0.2
    monthly_budget_units: int = 0
    enabled: bool = False

    def __post_init__(self) -> None:
        if not self.config_id.strip():
            raise ValueError("config_id is required")
        if self.retrieval_limit < 1 or not 0 < self.minimum_score <= 1:
            raise ValueError("invalid retrieval configuration")
        if self.monthly_budget_units < 0:
            raise ValueError("monthly budget cannot be negative")
        if self.enabled and self.monthly_budget_units == 0:
            raise ValueError("enabled chatbot requires a positive budget cap")
