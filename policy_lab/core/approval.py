"""인간 승인 포트 (RFC-0002) — G-GATE 강화.

codex 리뷰 결함#1(치명): 기존 ``HumanGate`` 는 ``approve(expert)`` 에 임의 문자열을 받아
LLM 전문가도 자기 산출을 승인할 수 있었다. 여기서는 **승인을 인간 전용 포트로 분리**하고,
토큰에 발급자·단계·artifact digest·nonce 를 결합해 위조·전용·재사용·승인후 교체를 차단한다.

리허설에서는 ``PreapprovedTokenPort`` 로 사전발급 토큰(누가·언제 승인했는지 기록)을 써서
인간을 대리하되, **LLM 이 토큰을 발급·위조하는 경로는 구조적으로 막는다.**
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from .guards import GuardViolation


def digest_artifact(artifact: object) -> str:
    """승인 대상 artifact 의 안정 해시 — 승인 후 내용 교체(tamper) 탐지용."""
    try:
        payload = json.dumps(artifact, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        payload = str(artifact)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ApprovalToken:
    """인간 승인 증표. 네 요소 결합으로 신뢰경계를 만든다 (codex 3차).

    - ``issuer``: 신뢰 발급자(허용 목록과 대조). LLM 식별자는 허용 목록에 없다.
    - ``stage_id``: 이 토큰이 유효한 단계 — 타 단계 전용(reuse) 차단.
    - ``artifact_digest``: 승인한 artifact 해시 — 승인 후 내용 교체 차단.
    - ``nonce``: 1회용 식별자 — 재사용(replay) 차단.
    """

    issuer: str
    stage_id: str
    artifact_digest: str
    nonce: str
    issued_at: str = ""


class HumanApprovalPort(Protocol):
    """승인 요청 포트. 구현체는 **인간 입력 또는 사전발급 토큰만** 반환한다.

    LLM expert 는 이 포트를 구현하지 않는다 (EXPERT_COMMENT 발언만 담당).
    """

    def request(self, stage_id: str, artifact: object) -> ApprovalToken: ...


class PreapprovedTokenPort:
    """리허설용 — 사전발급 토큰으로 인간 승인을 대리.

    토큰은 (issuer, stage_id, artifact_digest, nonce) 로 사전 발급된다. ``request`` 는
    해당 단계·artifact 에 맞는 미사용 토큰을 찾아 반환하고, 없으면 거부한다.
    ``allowed_issuers`` 에 없는 발급자(예: LLM)는 받지 않는다.
    """

    def __init__(self, tokens: list[ApprovalToken], allowed_issuers: set[str]) -> None:
        self._tokens = list(tokens)
        self._allowed = set(allowed_issuers)
        self._used: set[str] = set()
        for t in self._tokens:
            if t.issuer not in self._allowed:
                raise GuardViolation(
                    f"승인 토큰 발급자 {t.issuer!r} 가 허용 목록 밖 — "
                    "LLM·비신뢰 주체는 human_gate 를 승인할 수 없음"
                )

    def request(self, stage_id: str, artifact: object) -> ApprovalToken:
        digest = digest_artifact(artifact)
        for t in self._tokens:
            if (
                t.stage_id == stage_id
                and t.artifact_digest == digest
                and t.nonce not in self._used
                and t.issuer in self._allowed
            ):
                self._used.add(t.nonce)
                return t
        raise GuardViolation(
            f"{stage_id}: 유효한 인간 승인 토큰 없음 "
            "(발급자·단계·artifact 일치 + 미사용 토큰 필요)"
        )


def verify_token(
    token: ApprovalToken, stage_id: str, artifact: object, allowed_issuers: set[str]
) -> None:
    """release 전 토큰 검증. 네 요소가 모두 맞아야 통과 (runner 가 호출)."""
    if token.issuer not in allowed_issuers:
        raise GuardViolation(f"승인 발급자 {token.issuer!r} 비신뢰")
    if token.stage_id != stage_id:
        raise GuardViolation(
            f"토큰 단계 불일치: {token.stage_id!r} ≠ {stage_id!r} (전용 차단)"
        )
    if token.artifact_digest != digest_artifact(artifact):
        raise GuardViolation(f"{stage_id}: 승인 후 artifact 교체 탐지 (digest 불일치)")
