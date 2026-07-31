"""Data contracts for a source-grounded chatbot.

Knowledge text is untrusted data even after editorial approval. Approval permits
retrieval; it never grants document text authority over application instructions.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, Sequence


class KnowledgeStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REVOKED = "revoked"


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    source_id: str
    title: str
    source_url: str
    text: str
    status: KnowledgeStatus = KnowledgeStatus.DRAFT
    approved_by: str | None = None
    approved_at: str | None = None
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.chunk_id.strip() or not self.source_id.strip():
            raise ValueError("chunk_id and source_id are required")
        if not self.title.strip() or not self.text.strip():
            raise ValueError("title and text are required")
        if not self.source_url.startswith("https://"):
            raise ValueError("source_url must use https")
        if self.status is KnowledgeStatus.APPROVED and not (
            self.approved_by and self.approved_at
        ):
            raise ValueError("approved chunks require approver and approval time")
        object.__setattr__(
            self,
            "content_hash",
            hashlib.sha256(self.text.encode("utf-8")).hexdigest(),
        )


@dataclass(frozen=True)
class Claim:
    text: str
    citation_chunk_ids: tuple[str, ...]
    evidence_quotes: tuple[str, ...]


@dataclass(frozen=True)
class GeneratedAnswer:
    """Provider-neutral structured output; free-form uncited output is rejected."""

    claims: tuple[Claim, ...]


class ClaimGenerator(Protocol):
    def generate(
        self, query: str, evidence: Sequence[KnowledgeChunk]
    ) -> GeneratedAnswer: ...


@dataclass(frozen=True)
class Citation:
    number: int
    chunk_id: str
    source_id: str
    title: str
    source_url: str
    content_hash: str


@dataclass(frozen=True)
class ChatAnswer:
    answer: str
    claims: tuple[Claim, ...] = ()
    citations: tuple[Citation, ...] = ()
    abstained: bool = False
    reason: str | None = None
