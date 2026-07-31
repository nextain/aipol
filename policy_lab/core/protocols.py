"""표준 숙의 프로토콜 — 도메인 중립 참조 골격 (RFC §5).

``human_gate``는 AI 쟁점정리를 청중에 노출하기 전에 사람 승인을 구조적으로 강제한다.
도메인은 이 골격을 받아 ``audience_query`` 단계의 화이트리스트만 채운다.
"""
from __future__ import annotations

from .deliberation import Actor, DeliberationProtocol, Stage, StageType


def standard_deliberation() -> DeliberationProtocol:
    """사람 승인과 측정을 분리한 도메인 중립 참조 프로토콜."""
    stages = [
        Stage("s1", StageType.INTRO, Actor.MODERATOR, "오프닝·구조 설명"),
        Stage("s2", StageType.EXPERT_INPUT, Actor.EXPERT, "전문가안 제시(1·2안)"),
        Stage("s3", StageType.VOTE, Actor.AUDIENCE, "1차 투표(baseline)"),
        Stage(
            "s4", StageType.AI_GENERATE, Actor.AI,
            "시나리오(예시 서사)", prompt_key="scenario",
            notes="'예측'이 아니라 '예시 서사'로 라벨. 재정은 방향성만.",
        ),
        Stage(
            "s5a", StageType.AI_GENERATE, Actor.AI,
            "쟁점정리", prompt_key="issues", requires_human_approval=True,
            notes="'정렬'이 아니라 '공통 어휘'. 대안 프레임도 로깅.",
        ),
        Stage("s5gate", StageType.HUMAN_GATE, Actor.EXPERT, "전문가 쟁점 승인"),
        Stage("s5b", StageType.VOTE, Actor.AUDIENCE, "방향 투표"),
        Stage(
            "s6", StageType.EXPERT_COMMENT, Actor.EXPERT,
            "리스크 = 비용·제약(가능/불가 아님)",
        ),
        Stage(
            "s7a", StageType.AUDIENCE_QUERY, Actor.AUDIENCE,
            "변수형 질문(화이트리스트)",
            notes="허용 레버·범위는 도메인 plugin이 채운다.",
        ),
        Stage(
            "s7b", StageType.IMPACT_SIM, Actor.ENGINE,
            "변수 영향(A축 결정론 계산)", prompt_key="impact_sim",
            notes="'시뮬레이션'은 이 결정론 계산에만. LLM은 설명만.",
        ),
        Stage("s8", StageType.EXPERT_COMMENT, Actor.EXPERT, "가장 중요한 기준"),
        Stage(
            "s9", StageType.AI_GENERATE, Actor.AI,
            "수정안 합성", prompt_key="revision",
            notes="청중선택 + 전문가의견 '합성'. AI 우월성 주장 금지.",
        ),
        Stage("s10", StageType.VERIFY, Actor.AUDIENCE, "수정안 약점 청취"),
        Stage("s11", StageType.VOTE, Actor.AUDIENCE, "2차 투표(final)"),
        Stage(
            "s11m", StageType.MEASURE, Actor.ALL,
            "선택 변화 측정",
            notes="'오늘 이 자리의 선택' 라벨. 표본≠민의.",
        ),
        Stage(
            "s12", StageType.INTERPRET, Actor.ALL,
            "결과해석·마무리",
            notes="비참여자·미래세대 누락 명시.",
        ),
    ]
    return DeliberationProtocol(name="standard-reference", stages=stages)
