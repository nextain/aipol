"""근거 베이스 — 출처·버전이 고정된 팩트체크 앵커.

라이브 생성물(시나리오·수정안)이 이 앵커와 어긋나는지 검출하기 위한 저장소.
정량 앵커(``value``)는 RAG 코퍼스에 고정되며, 도메인이 ``verify`` 규칙을 확장한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Evidence:
    """하나의 근거 앵커.

    Attributes:
        key: 식별자 (예: ``"보험료율"``).
        statement: 사실 진술.
        source: 출처 (기관·문서).
        as_of: 기준 시점/버전 (예: ``"2025 합의 법률"``).
        value: 정량 앵커 (있으면). 라이브 생성물 검증의 기준값.
    """

    key: str
    statement: str
    source: str
    as_of: str
    value: Optional[str] = None


class EvidenceStore:
    """근거 앵커 모음. 출처·버전 고정 + 도메인 검증 규칙 부착 지점."""

    def __init__(self, items: Optional[list[Evidence]] = None) -> None:
        self._by_key: dict[str, Evidence] = {e.key: e for e in (items or [])}
        self._rules: list[Callable[[str], list[str]]] = []

    def add(self, e: Evidence) -> None:
        self._by_key[e.key] = e

    def get(self, key: str) -> Optional[Evidence]:
        return self._by_key.get(key)

    def all(self) -> list[Evidence]:
        return list(self._by_key.values())

    def anchored_values(self) -> dict[str, str]:
        """value가 있는 앵커만 {key: value} 로."""
        return {k: e.value for k, e in self._by_key.items() if e.value is not None}

    def add_rule(self, rule: Callable[[str], list[str]]) -> None:
        """텍스트를 받아 위반 메시지 리스트를 반환하는 도메인 검증 규칙 등록."""
        self._rules.append(rule)

    def contradictions(self, text: str) -> list[str]:
        """등록된 규칙으로 text가 앵커를 위반하는지 검사. 위반 메시지 리스트 반환."""
        hits: list[str] = []
        for rule in self._rules:
            hits.extend(rule(text))
        return hits
