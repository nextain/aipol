"""정책 레버 — 실험에서 *변화*시키는 파라미터와 *고정* 전제.

핵심 구분: 무엇을 바꾸고(``Lever``) 무엇을 전제로 고정하는지(``FixedVariable``)를
명시적으로 분리한다. 변수형 청중 질문은 ``Lever.numeric_range`` 화이트리스트로만
허용한다(프롬프트 인젝션 방어, RFC §6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Lever:
    """실험에서 변화시키는 정책 파라미터.

    Attributes:
        key: 식별자 (예: ``"수급연령"``).
        label: 사람이 읽는 이름.
        options: 이산 선택지 (예: ``("유지", "단계적 상향")``).
        numeric_range: 변수형 질문이 허용되는 [최소, 최대] 범위. None이면 이산만.
        unit: 수치 단위 (예: ``"세"``, ``"%"``).
    """

    key: str
    label: str
    options: tuple[str, ...] = ()
    numeric_range: Optional[tuple[float, float]] = None
    unit: Optional[str] = None

    def allows(self, value: object) -> bool:
        """value가 이 레버의 허용 선택지/범위 안인지."""
        if value in self.options:
            return True
        if self.numeric_range is not None and isinstance(value, (int, float)):
            lo, hi = self.numeric_range
            return lo <= float(value) <= hi
        return False


@dataclass(frozen=True)
class FixedVariable:
    """실험에서 변경 금지인 전제 변수 (예: 정부안으로 고정한 보험료율)."""

    key: str
    label: str
    value: str


@dataclass
class PolicyOption:
    """레버 값의 조합 = 하나의 정책안.

    ``origin`` 으로 전문가안/AI 수정안/청중제안을 구분해 추적성을 남긴다.
    """

    name: str
    lever_values: dict = field(default_factory=dict)
    origin: str = "expert"  # expert | ai_revision | audience

    def with_change(self, lever_key: str, value: object, name: Optional[str] = None) -> "PolicyOption":
        """한 레버 값만 바꾼 새 정책안을 반환 (원본 불변)."""
        nv = dict(self.lever_values)
        nv[lever_key] = value
        return PolicyOption(
            name=name or f"{self.name}·{lever_key}={value}",
            lever_values=nv,
            origin=self.origin,
        )
