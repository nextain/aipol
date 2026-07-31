"""Provider-neutral ports used by the policy-news orchestrator."""

from __future__ import annotations

from typing import Protocol

from contracts import EditorialDraft, KbCompileResult, ReviewResult, RunRecord, SourcePacket


class DraftPort(Protocol):
    name: str

    def draft(self, packet: SourcePacket) -> EditorialDraft: ...


class ReviewPort(Protocol):
    name: str

    def review(self, packet: SourcePacket, draft: EditorialDraft) -> ReviewResult: ...


class KnowledgeCompilerPort(Protocol):
    name: str

    def compile(self, packet: SourcePacket, draft: EditorialDraft) -> KbCompileResult: ...


class RunStorePort(Protocol):
    def load_by_idempotency_key(self, key: str) -> RunRecord | None: ...

    def save_source(self, packet: SourcePacket) -> None: ...

    def save(self, record: RunRecord) -> None: ...
