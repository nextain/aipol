"""[2] claim 카운트 합치기 결정론 코어 계약 테스트 (RFC-0003 §3·§6).

테스트는 "산술이 결정론인가" + "가드가 실제로 막는가"를 검증한다(RFC-0001 원칙).
매칭 LLM 층은 여기 없다 — 판정표(CoverJudgment)는 입력으로 주어진다.
"""
import pytest

from policy_lab.core.guards import GuardViolation
from policy_lab.core.synthesis import (
    Claim,
    Clause,
    Draft,
    CoverJudgment,
    Disposition,
    merge,
    assert_independent_drafts,
    assert_judge_separation,
    assert_reflection_completeness,
)


# 4 플래그십 = 4 회사 (RFC §2)
DRAFTS = [
    Draft("codex-5.5", "openai", (Clause("o1", "재정안정 조항"),)),
    Draft("gemini-3.5-flash", "google", (Clause("g1", "대체율 조항"),)),
    Draft("glm-5.2", "zhipu", (Clause("z1", "하이브리드 조항"),)),
    Draft("claude-opus-4.8", "anthropic", (Clause("a1", "지식화합 조항"),)),
]
JUDGES = {"qwen-judge", "solar-judge"}  # 초안 4모델과 겹치지 않음


def _yes(claim, draft, clause, judges=("qwen-judge", "solar-judge")):
    return [CoverJudgment(claim, draft, jm, True, clause) for jm in judges]


def _no(claim, draft, judges=("qwen-judge", "solar-judge")):
    return [CoverJudgment(claim, draft, jm, False) for jm in judges]


def test_cover_count_thresholds_deterministic():
    """k≥2→반영, k=1+지지→강제포함, k=0+다수→추가숙의, 그 외→미반영. 같은 입력 같은 출력."""
    claims = [
        Claim("c_reflect", "다수가 cover", support=40),   # 3 초안 cover → REFLECTED
        Claim("c_robust", "전부 cover", support=30),       # 4 초안 cover → REFLECTED+robust
        Claim("c_minor", "소수지만 지지 높음", support=25),  # 1 초안 cover, 지지 25 → FORCED
        Claim("c_needs", "다수인데 미반영", support=35),     # 0 cover, 지지 35 → NEEDS_MORE
        Claim("c_drop", "소수+지지 낮음", support=2),        # 0 cover, 지지 2 → UNREFLECTED
    ]
    j = []
    j += _yes("c_reflect", "codex-5.5", "o1") + _yes("c_reflect", "gemini-3.5-flash", "g1") + _yes("c_reflect", "glm-5.2", "z1")
    j += _yes("c_robust", "codex-5.5", "o1") + _yes("c_robust", "gemini-3.5-flash", "g1") + _yes("c_robust", "glm-5.2", "z1") + _yes("c_robust", "claude-opus-4.8", "a1")
    j += _yes("c_minor", "codex-5.5", "o1")
    # c_needs, c_drop: 판정 없음(아무 초안도 cover 안 함) → k=0

    m1 = merge(claims, DRAFTS, j, majority_support=20, minority_threshold=20)
    m2 = merge(claims, DRAFTS, j, majority_support=20, minority_threshold=20)
    # 결정론: 두 번 실행 동일
    assert [d.disposition for d in m1.decisions] == [d.disposition for d in m2.decisions]

    disp = {d.claim.cid: d for d in m1.decisions}
    assert disp["c_reflect"].disposition == Disposition.REFLECTED
    assert disp["c_reflect"].cover == 3 and disp["c_reflect"].robust is False
    assert disp["c_robust"].disposition == Disposition.REFLECTED
    assert disp["c_robust"].robust is True  # k == n_drafts(4)
    assert disp["c_minor"].disposition == Disposition.FORCED_MINORITY
    assert disp["c_needs"].disposition == Disposition.NEEDS_MORE
    assert disp["c_drop"].disposition == Disposition.UNREFLECTED
    # 정직 노출 묶음
    assert len(m1.reflected()) == 3   # reflect + robust + forced
    assert len(m1.needs_more()) == 1
    assert len(m1.unreflected()) == 1


def test_judge_disagreement_marked_uncertain():
    """판정기 ≥2 불일치 → cover 로 안 세고 '불확실' 노출 (봉합 금지, §3)."""
    claim = Claim("c", "한 초안에 판정 갈림", support=10)
    judgments = [
        CoverJudgment("c", "codex-5.5", "qwen-judge", True, "o1"),
        CoverJudgment("c", "codex-5.5", "solar-judge", False),  # 불일치
    ]
    m = merge([claim], DRAFTS, judgments, majority_support=20, minority_threshold=5)
    d = m.decisions[0]
    assert d.cover == 0  # 불일치는 cover 아님
    assert "codex-5.5" in d.provenance.uncertain_drafts
    assert m.uncertain() == [d]


def test_cover_judgment_requires_clause_when_covered():
    """cover=True 면 조항 링크 필수 (provenance 4-tuple, §3)."""
    with pytest.raises(ValueError):
        CoverJudgment("c", "codex-5.5", "qwen-judge", True, "")  # 조항 미지정
    CoverJudgment("c", "codex-5.5", "qwen-judge", False)  # 미cover 는 조항 불필요


def test_independent_drafts_requires_three_companies():
    """단일 합성 금지: 초안 ≥3 이며 회사 ≥3 (§6)."""
    # 4 초안이지만 회사 2개 → 위반
    same_company = [
        Draft("m1", "openai"), Draft("m2", "openai"),
        Draft("m3", "google"), Draft("m4", "google"),
    ]
    with pytest.raises(GuardViolation):
        assert_independent_drafts(same_company)
    # 초안 2개 → 위반
    with pytest.raises(GuardViolation):
        assert_independent_drafts(DRAFTS[:2])
    # 4 초안 4 회사 → 통과
    assert_independent_drafts(DRAFTS)


def test_judge_separation():
    """초안가 ∩ 판정기 = ∅ (§6 자기 채점 금지)."""
    drafters = {d.model for d in DRAFTS}
    with pytest.raises(GuardViolation):
        assert_judge_separation(drafters, {"qwen-judge", "codex-5.5"})  # codex 겹침
    assert_judge_separation(drafters, JUDGES)  # 안 겹침 → 통과


def test_reflection_completeness():
    """다수 claim 전원 분류 + 채택 조항 ≥1 링크 (§6)."""
    claims = [Claim("c1", "다수", support=50), Claim("c2", "다수2", support=40)]
    j = _yes("c1", "codex-5.5", "o1") + _yes("c1", "gemini-3.5-flash", "g1")
    j += _no("c2", "codex-5.5") + _no("c2", "gemini-3.5-flash")  # c2 미반영이나 분류됨
    m = merge(claims, DRAFTS, j, majority_support=30, minority_threshold=30)
    assert_reflection_completeness(m, claims, majority_support=30)  # 둘 다 분류됨 → 통과

    # 다수 claim 인데 merge 에 안 들어간 경우 → 미분류 위반
    extra = claims + [Claim("c3", "다수인데 누락", support=45)]
    with pytest.raises(GuardViolation):
        assert_reflection_completeness(m, extra, majority_support=30)
