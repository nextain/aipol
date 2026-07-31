"""연금 프롬프트 세트 — 5종, 버전·temp·시드 고정 (spec.md §5).

라이브는 사전생성·검수본을 연출한다. 각 프롬프트는 출력 규약으로 형식을 고정.
'정렬'→'공통 어휘', '시뮬레이션'→A축 결정론 계산으로 재프레이밍된 표현을 쓴다.
"""
from __future__ import annotations

from policy_lab.core.prompts import Prompt

SCENARIO = Prompt(
    key="scenario",
    version="0.1.0",
    template=(
        "정책안: {policy}\n근거(고정): {evidence}\n전제(고정변수): {fixed}\n"
        "위 정책안이 그대로 시행됐을 때 2045년 한국 사회의 '예시 서사'를 쓰라. "
        "예측이 아니라 하나의 가능한 그림이다."
    ),
    output_contract=(
        "2045년 모습 / 청년·중산층·저소득 노인 각각의 영향 / "
        "재정은 방향성만(연도·금액 단정 금지) / 긍정·부정 측면 / "
        "예상 사회갈등 2개 / 참고할 실제 사례 2개. 간결하게."
    ),
)

ISSUES = Prompt(
    key="issues",
    version="0.1.0",
    template=(
        "시나리오: {scenario}\n레버: {levers}\n"
        "이 정책 선택의 핵심 쟁점 3개를 각 레버(수급연령·국고투입·기초연금) 축에서 "
        "찬반이 드러나게 정리하라. '정답'이 아니라 '공통 어휘'를 만드는 것이다."
    ),
    output_contract=(
        "쟁점 3개(각 찬/반 한 줄). → 전문가 승인 게이트 필수(human_gate). "
        "대안 프레임이 있으면 함께 표기."
    ),
)

IMPACT_SIM = Prompt(
    key="impact_sim",
    version="0.1.0",
    template=(
        "기존 시나리오: {scenario}\n변경 변수: {variable}\n"
        "A축 결정론 계산 결과: {impact}\n"
        "위 계산 결과를 청중에게 '설명'만 하라. 새로운 수치를 만들어내지 말 것."
    ),
    output_contract="달라지는 점 / 수혜·불리 집단 / 예상 사회반응 2개. 5줄 이내.",
)

RISK = Prompt(
    key="risk",
    version="0.1.0",
    template=(
        "정책안: {policy}\n"
        "이 정책안의 주요 리스크 2개(현실적 실행 문제 + 사회갈등)를 짚으라. "
        "리스크는 '불가능'이 아니라 '비용·제약'으로 표현한다."
    ),
    output_contract="핵심 리스크 2개. (탐색·검증용 — 수정안에 자동 반영하지 않음)",
)

REVISION = Prompt(
    key="revision",
    version="0.1.0",
    template=(
        "청중 선택: {audience_choice}\n전문가 의견: {expert_opinion}\n"
        "전문가 기준: {criteria}\n전제: {fixed}\n근거(고정): {evidence}\n"
        "위를 '합성'해 현실적 정책 조합 1개를 제시하라. "
        "AI가 더 똑똑해서가 아니라 오늘의 숙의를 반영하는 것이다."
    ),
    output_contract=(
        "정책 조합(2줄) / 전문가안 대비 변화 / 2045년 모습 / 수혜·부담 집단 / "
        "trade-off 2개. 수치 대신 '단계적·점진적' 같은 방향 표현."
    ),
)

_PROMPTS = {p.key: p for p in (SCENARIO, ISSUES, IMPACT_SIM, RISK, REVISION)}


def pension_prompts() -> dict[str, Prompt]:
    return dict(_PROMPTS)
