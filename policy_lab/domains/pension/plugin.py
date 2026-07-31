"""연금 도메인 플러그인 — DomainPlugin 구현 (spec.md).

레버(변화/고정)·근거·영향모델·세그먼트·프롬프트를 한 단위로 캡슐화한다.
프로토콜·방어장치는 코어(``standard_deliberation`` + guards)에서 상속.
"""
from __future__ import annotations

from policy_lab.core.case import CaseDefinition, VoteOption
from policy_lab.core.deliberation import Segment
from policy_lab.core.evidence import EvidenceStore
from policy_lab.core.impact import ImpactModel
from policy_lab.core.levers import FixedVariable, Lever, PolicyOption
from policy_lab.core.plugin import DomainPlugin
from policy_lab.core.prompts import Prompt

from .evidence import pension_evidence
from .impact import PensionImpactModel
from .prompts import pension_prompts


class PensionDomain(DomainPlugin):
    key = "pension"
    label = "국민연금 개혁 (2026 한국정책학회)"

    def levers(self) -> list[Lever]:
        return [
            Lever(
                "수급연령", "수급 개시 연령",
                options=("유지", "단계적 상향"),
                numeric_range=(60, 68), unit="세",
            ),
            Lever(
                "국고투입", "국고 투입 수준",
                options=("최소화", "확대"),
                numeric_range=(0.0, 3.0), unit="% (GDP 대비)",
            ),
            Lever(
                "기초연금", "기초연금 구조",
                options=("선별 강화", "보편 확대", "혼합형"),
            ),
        ]

    def fixed_variables(self) -> list[FixedVariable]:
        return [
            FixedVariable("보험료율", "보험료율", "정부안 유지(2026 9.5% → 2033 13%)"),
            FixedVariable("소득대체율", "명목소득대체율", "정부안 유지(2026 43%)"),
        ]

    def evidence(self) -> EvidenceStore:
        return pension_evidence()

    def impact_model(self) -> ImpactModel:
        return PensionImpactModel()

    def segments(self) -> list[Segment]:
        return [
            Segment("youth", "20–30대", (0.30, 0.35)),
            Segment("middle", "40–50대", (0.35, 0.40)),
            Segment("senior", "60대+", (0.25, 0.30)),
        ]

    def prompts(self) -> dict[str, Prompt]:
        return pension_prompts()

    def build_case(self) -> CaseDefinition:
        """공개 합성 케이스 — 두 가정안과 AI 수정안을 비교하는 코드 예제."""
        opt1 = PolicyOption(
            name="1안(보장강화형)",
            lever_values={"수급연령": "유지", "국고투입": "확대", "기초연금": "보편 확대"},
            origin="expert",
        )
        opt2 = PolicyOption(
            name="2안(재정지속형)",
            lever_values={"수급연령": "단계적 상향", "국고투입": "최소화", "기초연금": "선별 강화"},
            origin="expert",
        )

        def vote_options(ctx: dict) -> list[VoteOption]:
            # ③1차·s5b방향 투표 = 1안/2안. ⑪최종 = +AI수정안(s9 산출이 ctx에 있으면 3지선다).
            opts = [
                VoteOption("opt1", opt1.name, opt1),
                VoteOption("opt2", opt2.name, opt2),
            ]
            revision = ctx.get("ai_revision")
            if revision is not None:
                opts.append(VoteOption("revision", revision.name, revision))
            return opts

        return CaseDefinition(
            version="public-synthetic-v1",
            source="public synthetic example; not an expert proposal",
            expert_options=[opt1, opt2],
            vote_options=vote_options,
            # ⑨ 합성 입력 = 실제 stage: s5b(청중 방향투표)·s6(전문가 리스크)·s8(전문가 기준).
            synthesis_inputs=["s5b", "s6", "s8"],
        )
