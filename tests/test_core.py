"""코어 방어장치·프로토콜 테스트 (RFC §6).

이 테스트들은 "방어장치가 실제로 막는가"를 검증한다. 통과 = 가드가 동작.
"""
from __future__ import annotations

import pytest

from policy_lab.core import (
    Actor,
    DeliberationProtocol,
    GuardViolation,
    HumanGate,
    Lever,
    MeasurementPurpose,
    Stage,
    StageType,
    VoteRound,
    assert_ab_separation,
    assert_declared_purpose,
    assert_not_opinion_claim,
    assert_within_whitelist,
    mind_change,
    reject_single_number,
    standard_deliberation,
)


# --- 단일 정밀 숫자 금지 ---
def test_reject_single_number_blocks_bare_number():
    with pytest.raises(GuardViolation):
        reject_single_number("2071")
    with pytest.raises(GuardViolation):
        reject_single_number("13%")


def test_reject_single_number_allows_ranges_and_qualitative():
    reject_single_number("소진 시점 2~4년 지연")  # 통과해야 함
    reject_single_number("재정 지속가능성 개선 방향")
    reject_single_number("약 2064년")
    reject_single_number("")


# --- A/B 분리 ---
def test_ab_separation_rejects_shared_model():
    with pytest.raises(GuardViolation):
        assert_ab_separation({"gpt-x"}, {"gpt-x"})


def test_ab_separation_passes_when_disjoint():
    assert_ab_separation({"impact:calc"}, {"llm:deliberation"})


# --- 화이트리스트 ---
def test_whitelist_blocks_out_of_range():
    lv = Lever("수급연령", "수급연령", options=("유지", "단계적 상향"), numeric_range=(60, 68))
    assert_within_whitelist(lv, 67)  # 통과
    assert_within_whitelist(lv, "유지")  # 통과
    with pytest.raises(GuardViolation):
        assert_within_whitelist(lv, 99)
    with pytest.raises(GuardViolation):
        assert_within_whitelist(lv, "민영화")


# --- human_gate ---
def test_human_gate_blocks_release_without_approval():
    gate = HumanGate("쟁점 3개")
    with pytest.raises(GuardViolation):
        gate.release()
    gate.approve("public-reviewer")
    assert gate.release() == "쟁점 3개"
    assert gate.approved_by == "public-reviewer"


# --- 프로토콜 불변식: human_gate 누락 검출 ---
def test_standard_protocol_validates():
    standard_deliberation().validate()  # raise 없어야 함


def test_protocol_detects_missing_human_gate():
    bad = DeliberationProtocol(
        "bad",
        [
            Stage("a", StageType.AI_GENERATE, Actor.AI, "쟁점", requires_human_approval=True),
            Stage("b", StageType.VOTE, Actor.AUDIENCE, "투표"),  # human_gate 없음!
        ],
    )
    with pytest.raises(GuardViolation):
        bad.validate()


# --- 선택 변화 측정 (반대·소수 보존) ---
def test_mind_change_preserves_deltas():
    before = VoteRound("1차")
    before.record("youth", "1안", 10)
    before.record("youth", "2안", 5)
    after = VoteRound("2차")
    after.record("youth", "1안", 7)
    after.record("youth", "2안", 8)
    mc = mind_change(before, after)
    assert mc["overall"]["1안"] == -3
    assert mc["overall"]["2안"] == 3
    assert mc["by_segment"]["youth"]["1안"] == -3


# --- 목적 단위 선언 (AI 리뷰 06: codex '목적 혼재') ---
def test_declared_purpose_requires_non_opinion():
    assert_declared_purpose([MeasurementPurpose.OPERATIONAL])  # 통과
    assert_declared_purpose(
        [MeasurementPurpose.OPERATIONAL, MeasurementPurpose.FRAMING_SENSITIVITY]
    )
    with pytest.raises(GuardViolation):
        assert_declared_purpose([])  # 미선언
    with pytest.raises(GuardViolation):
        assert_declared_purpose([MeasurementPurpose.OPINION_MEASUREMENT])  # 여론 금지


# --- 여론 단정 금지 (AI 리뷰 06: 결과 수치 전면화 오용) ---
def test_not_opinion_claim_blocks_opinion_framing():
    assert_not_opinion_claim("시뮬 조건에서 1안 응답 7건")  # 통과
    assert_not_opinion_claim("")
    with pytest.raises(GuardViolation):
        assert_not_opinion_claim("여론은 1안을 지지한다")
    with pytest.raises(GuardViolation):
        assert_not_opinion_claim("실제 청중 다수가 2안에 반대한다")
