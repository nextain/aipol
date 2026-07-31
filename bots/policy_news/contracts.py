"""Portable contracts for the AIPOL policy-news pipeline.

The contracts intentionally contain no Azure, Upstage, OpenRouter, or
``naia-kb-compiler`` types.  Provider adapters translate at the boundary so a
run can be replayed or migrated without changing its canonical JSON record.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any
from urllib.parse import urlparse


EDITORIAL_FIELDS = (
    "title_ko",
    "summary_ko",
    "policy_use",
    "human_review",
    "relevance",
    "caveat",
)
SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class ApprovalState(str, Enum):
    DISCOVERED = "discovered"
    DRAFTED = "drafted"
    REVIEW_BLOCKED = "review_blocked"
    REVIEW_PASSED = "review_passed"
    KB_COMPILED = "kb_compiled"
    HUMAN_APPROVED = "human_approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


ALLOWED_TRANSITIONS: dict[ApprovalState, set[ApprovalState]] = {
    ApprovalState.DISCOVERED: {ApprovalState.DRAFTED, ApprovalState.REJECTED},
    ApprovalState.DRAFTED: {ApprovalState.REVIEW_BLOCKED, ApprovalState.REVIEW_PASSED, ApprovalState.REJECTED},
    ApprovalState.REVIEW_BLOCKED: {ApprovalState.DRAFTED, ApprovalState.REJECTED},
    ApprovalState.REVIEW_PASSED: {ApprovalState.KB_COMPILED, ApprovalState.HUMAN_APPROVED, ApprovalState.REJECTED},
    ApprovalState.KB_COMPILED: {ApprovalState.HUMAN_APPROVED, ApprovalState.REJECTED},
    ApprovalState.HUMAN_APPROVED: {ApprovalState.PUBLISHED, ApprovalState.REJECTED},
    ApprovalState.REJECTED: set(),
    ApprovalState.PUBLISHED: set(),
}


def transition(current: ApprovalState, target: ApprovalState) -> ApprovalState:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid approval transition: {current.value} -> {target.value}")
    return target


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_nonempty(name: str, value: str, max_length: int = 50_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"{name} exceeds {max_length} characters")
    return value.strip()


@dataclass(frozen=True)
class SourcePacket:
    source_name: str
    source_url: str
    published: str
    country: str
    title: str
    source_text: str
    fetched_at: str
    license_note: str = "official source; store privately and publish only a short summary"
    source_id: str = ""
    content_sha256: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SourcePacket":
        required = {"source_name", "source_url", "published", "country", "title", "source_text"}
        allowed = required | {"fetched_at", "license_note", "source_id", "content_sha256"}
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(f"missing source fields: {', '.join(missing)}")
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise ValueError(f"unexpected source fields: {', '.join(unexpected)}")
        source_url = _require_nonempty("source_url", value["source_url"], 2_048)
        parsed = urlparse(source_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("source_url must be an absolute https URL")
        published = _require_nonempty("published", value["published"], 10)
        date.fromisoformat(published)
        fetched_at = str(value.get("fetched_at") or "").strip()
        if not fetched_at:
            raise ValueError("fetched_at is required for source provenance")
        fetched_datetime = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        if fetched_datetime.tzinfo is None or fetched_datetime.utcoffset() is None:
            raise ValueError("fetched_at must include a timezone offset")
        source_text = _require_nonempty("source_text", value["source_text"], 24_000)
        digest = sha256_text(source_text)
        supplied_digest = str(value.get("content_sha256") or "").strip()
        if supplied_digest and supplied_digest != digest:
            raise ValueError("content_sha256 does not match source_text")
        source_id = str(value.get("source_id") or "").strip() or sha256_text(source_url)[:24]
        if not SAFE_SOURCE_ID.fullmatch(source_id):
            raise ValueError("source_id may contain only letters, digits, dot, underscore, and hyphen")
        return cls(
            source_name=_require_nonempty("source_name", value["source_name"], 200),
            source_url=source_url,
            published=published,
            country=_require_nonempty("country", value["country"], 100),
            title=_require_nonempty("title", value["title"], 500),
            source_text=source_text,
            fetched_at=fetched_at,
            license_note=_require_nonempty("license_note", str(value.get("license_note") or cls.license_note), 500),
            source_id=source_id,
            content_sha256=digest,
        )

    def provider_payload(self) -> dict[str, str]:
        return asdict(self)

    def public_source_metadata(self) -> dict[str, str]:
        """Source text is deliberately excluded from public/export artifacts."""
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "published": self.published,
            "country": self.country,
            "title": self.title,
            "fetched_at": self.fetched_at,
            "content_sha256": self.content_sha256,
            "license_note": self.license_note,
        }


@dataclass(frozen=True)
class EditorialDraft:
    title_ko: str
    summary_ko: str
    policy_use: str
    human_review: str
    relevance: str
    caveat: str
    provider: str
    model: str
    generated_at: str
    response_id: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, provider: str, model: str, generated_at: str) -> "EditorialDraft":
        limits = {"title_ko": 160, "summary_ko": 900, "policy_use": 600, "human_review": 600, "relevance": 600, "caveat": 600}
        fields = {name: _require_nonempty(name, str(value.get(name, "")), limits[name]) for name in EDITORIAL_FIELDS}
        datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        return cls(**fields, provider=provider, model=model, generated_at=generated_at, response_id=str(value.get("response_id") or ""))

    def editorial_fields(self) -> dict[str, str]:
        value = asdict(self)
        return {name: value[name] for name in EDITORIAL_FIELDS}


@dataclass(frozen=True)
class ReviewResult:
    verdict: str
    issues: list[dict[str, str]]
    coverage: list[str]
    summary: str
    provider: str
    model: str
    reviewed_at: str
    response_id: str = ""

    def __post_init__(self) -> None:
        if self.verdict not in {"PASS", "BLOCK"}:
            raise ValueError("review verdict must be PASS or BLOCK")
        if self.verdict == "PASS" and self.issues:
            raise ValueError("PASS review cannot contain issues")
        if self.verdict == "BLOCK" and not self.issues:
            raise ValueError("BLOCK review must contain at least one issue")
        _require_nonempty("review summary", self.summary, 1_000)
        datetime.fromisoformat(self.reviewed_at.replace("Z", "+00:00"))


@dataclass(frozen=True)
class KbCompileResult:
    compiler: str
    compiler_version: str
    export_format: str
    artifact_uri: str
    artifact_sha256: str
    accepted_count: int
    gap_count: int
    compiled_at: str
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.accepted_count < 0 or self.gap_count < 0:
            raise ValueError("KB counts cannot be negative")
        if len(self.artifact_sha256) != 64:
            raise ValueError("artifact_sha256 must be SHA-256 hex")


@dataclass
class RunRecord:
    schema_version: str
    run_id: str
    idempotency_key: str
    state: ApprovalState
    source: dict[str, str]
    config_snapshot: dict[str, Any]
    created_at: str
    updated_at: str
    draft: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    kb: dict[str, Any] | None = None
    attempts: dict[str, int] = field(default_factory=dict)
    audit: list[dict[str, Any]] = field(default_factory=list)

    def move(self, target: ApprovalState, *, at: str, actor: str, reason: str) -> None:
        previous = self.state
        self.state = transition(self.state, target)
        self.updated_at = at
        self.audit.append({"at": at, "actor": actor, "from": previous.value, "to": target.value, "reason": reason})

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state"] = self.state.value
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RunRecord":
        copy = dict(value)
        copy["state"] = ApprovalState(copy["state"])
        return cls(**copy)


def idempotency_key(packet: SourcePacket, config_revision: str, prompt_sha256: str) -> str:
    return sha256_text(canonical_json({
        "source_url": packet.source_url,
        "content_sha256": packet.content_sha256,
        "config_revision": config_revision,
        "prompt_sha256": prompt_sha256,
    }))
