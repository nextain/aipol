"""[4] 측정 채점표 계약 테스트 (RFC-0003 §4·§6).

핵심: 절대 전환율이 아니라 **Δ·통제·반사실**이 채점하는가, 그리고 가드가 순응
재생산을 기각하는가. 통계는 닫힌형이라 결정론.
"""
import pytest

from policy_lab.core.guards import GuardViolation
from policy_lab.core.responses import Stance
from policy_lab.core.measurement import (
    Arm,
    ArmObservation,
    improved,
    two_prop_ztest,
    placebo_result,
    assert_placebo_control,
    model_invariance,
    assert_citizen_model_invariance,
    CounterfactualObservation,
    genuine_reflection_rate,
    assert_counterfactual_reflection,
    SegmentEquity,
    segment_equity,
    assert_segment_equity,
)


def _obs(n, arm, moved, model="qwen", seg="senior", start=0):
    """n명 관측 — moved명이 reject→accept, 나머지 유지."""
    out = []
    for i in range(n):
        if i < moved:
            b, a = Stance.REJECT, Stance.ACCEPT
        else:
            b, a = Stance.REJECT, Stance.REJECT
        out.append(ArmObservation(f"{model}{seg}{arm.value}{start+i}", seg, model, arm, b, a))
    return out


def test_improved_order():
    assert improved(Stance.REJECT, Stance.ACCEPT)
    assert improved(Stance.CONDITIONAL, Stance.ACCEPT)
    assert not improved(Stance.ACCEPT, Stance.REJECT)
    assert not improved(Stance.ACCEPT, Stance.ACCEPT)


def test_placebo_works_when_real_beats_dummy_and_negative_lowest():
    """①Δ 유의 양 + ③<② → works. 진짜 반영 시나리오."""
    # real 80%, dummy 30%, negative 10% (각 100명)
    obs = _obs(100, Arm.REAL, 80) + _obs(100, Arm.DUMMY, 30) + _obs(100, Arm.NEGATIVE, 10)
    r = placebo_result(obs)
    assert r.delta == pytest.approx(0.5)
    assert r.delta_significant
    assert r.negative_below_dummy
    assert r.works


def test_placebo_rejects_compliance_reproduction():
    """순응 재생산: real≈dummy≈negative 다 높음 → Δ 유의 아님 → works=False."""
    # Solar식: 다 99% 이동 (안 품질 아니라 순응)
    obs = _obs(100, Arm.REAL, 99) + _obs(100, Arm.DUMMY, 98) + _obs(100, Arm.NEGATIVE, 97)
    r = placebo_result(obs)
    assert not r.delta_significant   # Δ 작아 유의 아님
    assert not r.works               # 절대 전환율 99%라도 기각


def test_placebo_rejects_when_negative_not_below_dummy():
    """③ < ② 부등식 안 서면 works=False (부정통제가 더미만큼 이동)."""
    obs = _obs(100, Arm.REAL, 80) + _obs(100, Arm.DUMMY, 30) + _obs(100, Arm.NEGATIVE, 35)
    r = placebo_result(obs)
    assert r.delta_significant
    assert not r.negative_below_dummy
    assert not r.works


def test_assert_placebo_control_requires_three_arms():
    """3-arm 누락 시 [4] 거부 (§6)."""
    two_arm = _obs(10, Arm.REAL, 5) + _obs(10, Arm.DUMMY, 2)
    with pytest.raises(GuardViolation):
        assert_placebo_control(two_arm)
    assert_placebo_control(two_arm + _obs(10, Arm.NEGATIVE, 1))  # 셋 다 → 통과


def test_two_prop_ztest_closed_form():
    """닫힌형 결정론 — 같은 입력 같은 출력, 명백한 차이는 유의."""
    z1, p1 = two_prop_ztest(80, 100, 30, 100)
    z2, p2 = two_prop_ztest(80, 100, 30, 100)
    assert (z1, p1) == (z2, p2)
    assert z1 > 0 and p1 < 0.01
    # n=0 보수 처리
    assert two_prop_ztest(0, 0, 5, 10) == (0.0, 1.0)


def test_model_invariance_sign_agreement():
    """2종 시민모델 ①Δ 부호 일관 → 통과. 불일치 → 실격."""
    # qwen: real>dummy (Δ+), solar: real>dummy (Δ+) → 부호 일관
    good = (_obs(50, Arm.REAL, 40, model="qwen") + _obs(50, Arm.DUMMY, 15, model="qwen")
            + _obs(50, Arm.REAL, 45, model="solar") + _obs(50, Arm.DUMMY, 20, model="solar"))
    assert model_invariance(good).signs_agree
    assert_citizen_model_invariance(good)

    # qwen Δ+, solar Δ− (real<dummy) → 부호 불일치 → 실격
    bad = (_obs(50, Arm.REAL, 40, model="qwen") + _obs(50, Arm.DUMMY, 15, model="qwen")
           + _obs(50, Arm.REAL, 10, model="solar") + _obs(50, Arm.DUMMY, 30, model="solar"))
    assert not model_invariance(bad).signs_agree
    with pytest.raises(GuardViolation):
        assert_citizen_model_invariance(bad)


def test_model_invariance_requires_two_models():
    """한 모델만이면 실격 (§4.2)."""
    one = _obs(50, Arm.REAL, 40) + _obs(50, Arm.DUMMY, 15)
    with pytest.raises(GuardViolation):
        assert_citizen_model_invariance(one)


def test_counterfactual_genuine_vs_compliance():
    """전환자 중 조항 제거 시 철회 비율 = 진짜 반영. 철회 안 하면 순응."""
    cf = [
        CounterfactualObservation("p1", True, True),    # 진짜
        CounterfactualObservation("p2", True, True),    # 진짜
        CounterfactualObservation("p3", True, False),   # 순응 (철회 안 함)
        CounterfactualObservation("p4", False, False),  # 전환 안 함 (분모 제외)
    ]
    assert genuine_reflection_rate(cf) == pytest.approx(2 / 3)
    assert_counterfactual_reflection(cf, min_genuine=0.5)  # 0.67 ≥ 0.5 통과
    with pytest.raises(GuardViolation):
        assert_counterfactual_reflection(cf, min_genuine=0.8)  # 0.67 < 0.8 기각


def test_counterfactual_no_transition_fails():
    """전환자 0 → 반사실 정의 불가 (§4.3)."""
    cf = [CounterfactualObservation("p1", False, False)]
    with pytest.raises(GuardViolation):
        assert_counterfactual_reflection(cf, min_genuine=0.5)


def test_segment_equity_prethreshold():
    """집단별 미반영률 사전 임계 초과 → 실격 (§4.4)."""
    obs = (_obs(20, Arm.REAL, 15, seg="senior") + _obs(20, Arm.DUMMY, 5, seg="senior")
           + _obs(20, Arm.REAL, 12, seg="youth") + _obs(20, Arm.DUMMY, 6, seg="youth"))
    eq = segment_equity(obs, {"senior": 0.1, "youth": 0.6})
    by = {e.segment: e for e in eq}
    assert by["senior"].delta == pytest.approx(0.5)
    # youth 미반영률 0.6 > 임계 0.4 → 실격
    with pytest.raises(GuardViolation):
        assert_segment_equity(eq, max_unreflected_ratio=0.4)
    # 임계 0.7 이면 통과
    assert_segment_equity(eq, max_unreflected_ratio=0.7)
