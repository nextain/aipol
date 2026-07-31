"""Provenance / 감사 로그 — 재현성 + 책임 추적.

모든 단계의 모델·버전·temp·시드·프롬프트·근거 출처·입출력을 기록한다.
타임스탬프는 외부에서 주입한다 (비결정성 회피 — 재현 패키지의 일부).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class ProvenanceRecord:
    stage_id: str
    actor: str
    model_id: Optional[str] = None
    model_version: Optional[str] = None
    temperature: Optional[float] = None
    seed: Optional[int] = None
    prompt_key: Optional[str] = None
    prompt_version: Optional[str] = None
    evidence_keys: tuple[str, ...] = field(default_factory=tuple)
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    timestamp: Optional[str] = None  # 외부 주입 (ISO8601 권장)


class ProvenanceLog:
    """세션 단위 감사 로그. 재현 패키지로 직렬화 가능."""

    def __init__(self) -> None:
        self._records: list[ProvenanceRecord] = []

    def append(self, record: ProvenanceRecord) -> ProvenanceRecord:
        self._records.append(record)
        return record

    def records(self) -> list[ProvenanceRecord]:
        return list(self._records)

    def model_ids(self) -> set[str]:
        """기록된 모든 model_id (A/B 분리 검증용)."""
        return {r.model_id for r in self._records if r.model_id}

    def model_ids_for_actor(self, actor: str) -> set[str]:
        return {r.model_id for r in self._records if r.model_id and r.actor == actor}

    def to_json(self) -> str:
        return json.dumps(
            [asdict(r) for r in self._records], ensure_ascii=False, indent=2
        )
