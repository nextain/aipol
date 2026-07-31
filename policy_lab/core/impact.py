"""영향 모델 (A축) — 레버 조합을 *결정론적으로* 계산.

핵심 규칙:
- ``ImpactModel`` 은 LLM을 호출하지 않는다 (순수 계산). LLM은 결과를 *설명*만 한다(B축).
- 출력은 방향성·불확실성 밴드만 — 단일 정밀 숫자를 권위로 제시하지 않는다(RFC §6).
- ``model_id`` 는 provenance + A/B 분리 검증(``assert_ab_separation``)에 쓰인다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from .guards import reject_single_number


class Direction(str, Enum):
    IMPROVES = "improves"
    WORSENS = "worsens"
    MIXED = "mixed"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ImpactResult:
    """A축 결정론 계산 결과 한 줄.

    ``band`` 는 방향성·범위·정성 표현만 허용된다. 단일 정밀 숫자면
    ``GuardViolation`` 으로 거부된다 (허위 정밀성 방어).
    """

    metric: str
    direction: Direction
    band: str
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        reject_single_number(self.band)


class ImpactModel(ABC):
    """레버 조합 → 결과를 결정론적으로 계산하는 A축 어댑터.

    구현체는 ``model_id`` 를 정의해야 한다 (provenance + A/B 분리 검증용).
    """

    model_id: str = "impact:abstract"

    @abstractmethod
    def evaluate(self, option) -> list[ImpactResult]:  # option: PolicyOption
        """정책안을 받아 영향 결과(방향·밴드) 리스트를 반환."""
        raise NotImplementedError
