"""숙의 프로토콜 (B축) — 단계 그래프 + 투표·선택변화 측정.

행사별 순서와 분리된 도메인 중립 stage 타입을 제공한다(RFC §5).
``DeliberationProtocol.validate`` 가 핵심 불변식을 강제한다:
human_gate를 요구하는 AI 산출 단계 뒤에는 반드시 HUMAN_GATE가 와야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .guards import GuardViolation


class Actor(str, Enum):
    MODERATOR = "moderator"
    EXPERT = "expert"
    AI = "ai"
    AUDIENCE = "audience"
    ENGINE = "engine"  # A축 결정론 계산
    ALL = "all"


class StageType(str, Enum):
    INTRO = "intro"
    EXPERT_INPUT = "expert_input"
    EXPERT_COMMENT = "expert_comment"
    AI_GENERATE = "ai_generate"
    IMPACT_SIM = "impact_sim"
    AUDIENCE_QUERY = "audience_query"
    VOTE = "vote"
    HUMAN_GATE = "human_gate"
    VERIFY = "verify"
    MEASURE = "measure"
    INTERPRET = "interpret"


@dataclass
class Stage:
    id: str
    type: StageType
    actor: Actor
    label: str
    requires_human_approval: bool = False  # True면 다음 단계가 HUMAN_GATE여야 함
    prompt_key: Optional[str] = None  # ai_generate / impact_sim
    whitelist_lever_keys: tuple[str, ...] = field(default_factory=tuple)  # audience_query
    notes: str = ""


@dataclass
class DeliberationProtocol:
    name: str
    stages: list[Stage] = field(default_factory=list)

    def stage(self, sid: str) -> Optional[Stage]:
        for st in self.stages:
            if st.id == sid:
                return st
        return None

    def validate(self) -> "DeliberationProtocol":
        """구조 불변식 검사. 위반 시 ``GuardViolation``.

        불변식: ``requires_human_approval=True`` 인 단계 바로 다음은 HUMAN_GATE.
        (AI 쟁점정리가 전문가 승인 없이 청중에 노출되는 것을 구조적으로 차단)
        """
        errors: list[str] = []
        for i, st in enumerate(self.stages):
            if st.requires_human_approval:
                nxt = self.stages[i + 1] if i + 1 < len(self.stages) else None
                if nxt is None or nxt.type != StageType.HUMAN_GATE:
                    errors.append(
                        f"{st.id}({st.label}): human_gate 누락 — "
                        "AI 산출물이 전문가 승인 없이 노출될 수 있음"
                    )
        if errors:
            raise GuardViolation("프로토콜 불변식 위반:\n  - " + "\n  - ".join(errors))
        return self


@dataclass(frozen=True)
class Segment:
    """청중 세그먼트 (예: 연령대). 측정은 세그먼트별로 분리 집계."""

    key: str
    label: str
    target_share: tuple[float, float]  # 사전등록 배분 [최소, 최대]


@dataclass
class VoteRound:
    """한 차례 투표. 세그먼트 × 선택지 집계.

    합의/반대 분포를 둘 다 보존한다 (굿하트 방어 — 합의율을 목적함수로 쓰지 않음).
    """

    name: str
    # segment_key -> option_name -> count
    tallies: dict = field(default_factory=dict)

    def record(self, segment_key: str, option_name: str, count: int = 1) -> None:
        seg = self.tallies.setdefault(segment_key, {})
        seg[option_name] = seg.get(option_name, 0) + count

    def segment_totals(self, segment_key: str) -> dict:
        return dict(self.tallies.get(segment_key, {}))

    def totals(self) -> dict:
        """전 세그먼트 합산 {option_name: count}."""
        out: dict = {}
        for seg in self.tallies.values():
            for opt, c in seg.items():
                out[opt] = out.get(opt, 0) + c
        return out


def mind_change(before: VoteRound, after: VoteRound) -> dict:
    """1차 → 2차 투표 선택 변화 측정.

    Returns:
        {"overall": {option: delta}, "by_segment": {seg: {option: delta}}}
        — 변화량(델타)을 보존. 반대·소수 의견도 0으로 지우지 않는다.
    """
    before_tot = before.totals()
    after_tot = after.totals()
    options = set(before_tot) | set(after_tot)
    overall = {opt: after_tot.get(opt, 0) - before_tot.get(opt, 0) for opt in options}

    by_segment: dict = {}
    seg_keys = set(before.tallies) | set(after.tallies)
    for seg in seg_keys:
        b = before.segment_totals(seg)
        a = after.segment_totals(seg)
        opts = set(b) | set(a)
        by_segment[seg] = {opt: a.get(opt, 0) - b.get(opt, 0) for opt in opts}

    return {"overall": overall, "by_segment": by_segment}
