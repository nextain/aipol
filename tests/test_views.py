"""[3a]·[3b] 가시화 뷰모델 계약 테스트 (RFC-0003 §1·§6).

핵심: 가시화가 미반영을 **조용히 떨어뜨릴 수 없는가**(포장 금지 = 구조 노출).
렌더링이 아니라 뷰모델 완전성을 테스트한다.
"""
import pytest

from policy_lab.core.guards import GuardViolation
from policy_lab.core.responses import Stance
from policy_lab.core.synthesis import (
    Claim, Clause, Draft, CoverJudgment, merge,
)
from policy_lab.core.measurement import Arm, ArmObservation
from policy_lab.core.views import (
    build_presentation,
    assert_exposure_complete,
    PresentationView,
    build_reflection_paths,
)


DRAFTS = [
    Draft("codex", "openai", (Clause("o1", "고령자 조항"),)),
    Draft("gemini", "google", (Clause("g1", "청년 조항"),)),
    Draft("glm", "zhipu", ()),
    Draft("claude", "anthropic", ()),
]


def _yes(cid, draft, clause):
    return [CoverJudgment(cid, draft, j, True, clause) for j in ("jq", "js")]


def _merged():
    claims = [
        Claim("c_ref", "고령자 예외", support=40),    # 2 cover → reflected
        Claim("c_unref", "소수 미반영", support=3),    # 0 cover, 낮은지지 → unreflected
        Claim("c_nm", "다수 미반영", support=50),       # 0 cover, 높은지지 → needs_more
    ]
    j = _yes("c_ref", "codex", "o1") + _yes("c_ref", "gemini", "g1")
    return merge(claims, DRAFTS, j, majority_support=30, minority_threshold=20)


def test_presentation_exposes_unreflected_and_needs_more():
    """채택뿐 아니라 미반영·추가숙의가 같은 구조에 있다."""
    m = _merged()
    view = build_presentation(m)
    assert len(view.adopted) == 1
    assert {e.claim_id for e in view.unreflected} == {"c_unref"}
    assert {e.claim_id for e in view.needs_more} == {"c_nm"}
    # 미반영 항목에 사유가 비어있지 않다
    assert all(e.reason for e in view.unreflected)


def test_exposure_guard_blocks_dropped_unreflected():
    """미반영을 떨어뜨린 뷰는 가드가 막는다 (§6 포장 금지)."""
    m = _merged()
    # 채택만 담고 미반영/추가숙의를 비운 위조 뷰
    rigged = PresentationView(
        adopted=build_presentation(m).adopted,
        unreflected=(), needs_more=(), uncertain=(),
    )
    with pytest.raises(GuardViolation):
        assert_exposure_complete(rigged, m)


def test_uncertain_surfaced_in_view():
    """판정기 불일치(불확실)도 뷰에 노출."""
    claims = [Claim("c", "갈린 판정", support=10)]
    j = [CoverJudgment("c", "codex", "jq", True, "o1"),
         CoverJudgment("c", "codex", "js", False)]
    m = merge(claims, DRAFTS, j, majority_support=30, minority_threshold=5)
    view = build_presentation(m)
    assert {e.claim_id for e in view.uncertain} == {"c"}


def test_reflection_paths_per_citizen():
    """[3b] 시민별 조건 → 조항/사유 → 전환/유지."""
    m = _merged()
    claim_pids = {"c_ref": ["K1"], "c_unref": ["K1", "K2"], "c_nm": ["K2"]}
    obs = [
        ArmObservation("K1", "senior", "qwen", Arm.REAL, Stance.REJECT, Stance.ACCEPT),  # 전환
        ArmObservation("K2", "youth", "qwen", Arm.REAL, Stance.REJECT, Stance.REJECT),   # 유지
    ]
    paths = build_reflection_paths(m, obs, claim_pids)
    by = {p.pid: p for p in paths}
    assert by["K1"].moved is True and by["K2"].moved is False
    # K1: c_ref(반영, 조항 o1·g1) + c_unref(미반영)
    k1_steps = {s.claim_id: s for s in by["K1"].steps}
    assert k1_steps["c_ref"].disposition == "reflected"
    assert "o1" in k1_steps["c_ref"].clause_ids
    assert k1_steps["c_unref"].disposition == "unreflected"
    assert k1_steps["c_unref"].reason  # 사유 있음
    assert by["K1"].segment == "senior"
