"""프롬프트 레지스트리 항목 — 버전·temperature·시드 고정 (재현성).

라이브는 사전생성·검수본을 연출한다. 각 프롬프트는 출력 규약(output_contract)을
명시해 형식을 고정하고, provenance에 버전과 함께 기록된다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Prompt:
    key: str
    version: str
    template: str
    output_contract: str
    temperature: float = 0.2
    seed: Optional[int] = 7

    def render(self, **kwargs) -> str:
        """간단 치환. 누락 키는 그대로 둔다(검수에서 발견되도록)."""
        try:
            return self.template.format(**kwargs)
        except (KeyError, IndexError):
            return self.template
