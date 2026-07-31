"""적대 리뷰 1라운드(2026-06-26 개발 리뷰)가 찾은 결함의 회귀 테스트.

리뷰어들의 mutation-probe(막혀야 하는데 통과하던 입력)를 박제해 같은 우회가 다시
통과하지 못하게 한다. 각 테스트 = [리뷰 결함 id] 주석.
"""
import json
import pytest

from policy_lab.core.guards import GuardViolation
from policy_lab.core.responses import (
    CitizenResponse, ProposalResponse, Stance, ResponseLedger,
)
from policy_lab.core.synthesis import (
    Claim, Clause, Draft, CoverJudgment, merge,
    assert_independent_drafts, assert_judge_separation,
)
from policy_lab.core.synthesis_runner import _extract_json, _req
from policy_lab.core.measurement import (
    Arm, ArmObservation, model_invariance, assert_citizen_model_invariance,
    ledger_to_arm_obs, run_measurement, CounterfactualObservation,
)


# ── 리뷰어1 C1·C2: 판정기 ≥2 미강제 ────────────────────────────────────

def test_judge_count_enforced():
    """[C1] 단일 판정기면 '불확실 노출'이 죽는다 → ≥2 강제."""
    drafters = {"codex", "gemini", "glm", "claude"}
    with pytest.raises(GuardViolation):
        assert_judge_separation(drafters, {"j1"})           # 1개 → 거부
    with pytest.raises(GuardViolation):
        assert_judge_separation(drafters, set())            # [C2] 0개 → 거부
    assert_judge_separation(drafters, {"j1", "j2"})         # 2개 → 통과


# ── 리뷰어1 M1·M2·M3: 문자열 정규화 / 모델 중복 ────────────────────────

def test_company_normalization():
    """[M1] 공백·대소문자 변형으로 가짜 다양성 통과 차단."""
    rigged = [Draft("m1", "OpenAI"), Draft("m2", "openai "), Draft("m3", " OPENAI")]
    with pytest.raises(GuardViolation):
        assert_independent_drafts(rigged)  # 실은 회사 1개

def test_judge_separation_normalized():
    """[M2] 대소문자·공백으로 자기 채점 우회 차단."""
    with pytest.raises(GuardViolation):
        assert_judge_separation({"GPT"}, {"gpt ", "j2"})

def test_drafter_model_dup():
    """[M3] 같은 모델 N콜은 독립 초안 아님."""
    rigged = [Draft("dup", "A"), Draft("dup", "B"), Draft("dup", "C")]
    with pytest.raises(GuardViolation):
        assert_independent_drafts(rigged)


# ── 리뷰어2: §3 minority ≤ majority 불변식 ─────────────────────────────

def test_threshold_invariant():
    """[리뷰§3] minority_threshold > majority_support 면 다수 k=1이 샌다 → 거부."""
    with pytest.raises(ValueError):
        merge([], [], [], majority_support=30, minority_threshold=100)
    merge([], [], [], majority_support=30, minority_threshold=30)  # 같음 → 허용


# ── 리뷰어2: §4.2 invariance Δ=0 / 전원 음수 ───────────────────────────

def _arm(model, arm, moved, total):
    return [
        ArmObservation(f"{model}{arm.value}{i}", "s", model, arm,
                       Stance.REJECT, Stance.ACCEPT if i < moved else Stance.REJECT)
        for i in range(total)
    ]

def test_invariance_rejects_zero_delta_model():
    """[리뷰§4.2] 한 모델 Δ=0(효과 미복제)을 '일관'으로 흡수하지 않는다."""
    # qwen Δ=0 (real==dummy), solar Δ>0
    obs = (_arm("qwen", Arm.REAL, 10, 20) + _arm("qwen", Arm.DUMMY, 10, 20)
           + _arm("solar", Arm.REAL, 16, 20) + _arm("solar", Arm.DUMMY, 6, 20))
    assert not model_invariance(obs).signs_agree
    with pytest.raises(GuardViolation):
        assert_citizen_model_invariance(obs)

def test_invariance_rejects_all_negative():
    """[리뷰§4.2] 전원 음수(일관 역효과)는 부호 일관이어도 '작동' 아님 → require_positive 거부."""
    obs = (_arm("qwen", Arm.REAL, 5, 20) + _arm("qwen", Arm.DUMMY, 15, 20)     # Δ<0
           + _arm("solar", Arm.REAL, 4, 20) + _arm("solar", Arm.DUMMY, 14, 20))  # Δ<0
    assert model_invariance(obs).signs_agree  # 부호는 일관(둘 다 음)
    with pytest.raises(GuardViolation):
        assert_citizen_model_invariance(obs)  # require_positive=기본 → 거부
    # 순수 부호-일관 연구 모드면 통과
    assert_citizen_model_invariance(obs, require_positive=False)


# ── 리뷰어3 #2: _extract_json greedy / 다중 블록 / 잡설 ────────────────

def test_extract_json_robust():
    """[#2] 앞 잡설 괄호·다중 블록에서 첫 유효 JSON만."""
    # 텍스트 안 괄호가 먼저 와도 진짜 JSON을 찾는다
    assert _extract_json('설명 [목록] 입니다.\n```json\n{"covered": true}\n```')["covered"] is True
    # 펜스 없이 잡설 + JSON
    assert _extract_json('판정 결과: {"covered": false} 끝')["covered"] is False
    # 다중 객체 — 첫 유효 블록(greedy 오버런 아님)
    assert _extract_json('{"a": 1} 그리고 {"b": 2}')["a"] == 1

def test_extract_json_think_aware():
    """[실측 2026-06-27] thinking 판정기가 <think> 안에 가설 JSON을 먼저 내도 최종 답만 본다.

    kanana-thinking 판정기 슬라이스 테스트에서 발견: naive 스캔은 think 안의 가설을 잡아
    판정을 뒤집는다. </think> 뒤를 우선해야 한다.
    """
    sample = '<think>처음엔 {"covered": false} 일까 했지만 c2가 다룬다</think>\n{"covered": true, "clause_id": "c2"}'
    assert _extract_json(sample) == {"covered": True, "clause_id": "c2"}


def test_extract_json_none_vs_empty():
    """[#1] content=None 과 빈 문자열을 구분해 올린다(오진 방지)."""
    with pytest.raises(ValueError, match="None"):
        _extract_json(None)
    with pytest.raises(ValueError, match="빈 응답"):
        _extract_json("   ")

def test_req_attributes_missing_key():
    """[#3] 키 누락 시 raw KeyError 대신 어느 단계인지 밝힌다."""
    with pytest.raises(ValueError, match="claim 추출"):
        _req({"text": "x"}, "cid", "claim 추출")


# ── 리뷰어1 C3 / 리뷰어3 #5: [4] 가드 배선 + ledger 이음새 ─────────────

def _props():
    return ("1안",)

def _resp(pid, seg, model, stance):
    return CitizenResponse(pid, seg, model,
                           {"1안": ProposalResponse("1안", stance)}, proposals=_props())

def test_ledger_to_arm_obs_adapter():
    """[#5] ledger 두 round → ArmObservation (손으로 안 만들고 실제 데이터에서)."""
    led = ResponseLedger()
    led.record("base", _resp("K1", "senior", "qwen", Stance.REJECT))
    led.record("real", _resp("K1", "senior", "qwen", Stance.ACCEPT))   # 전환
    obs = ledger_to_arm_obs(led, "1안", baseline_round="base",
                            arm_rounds={"real": Arm.REAL})
    assert len(obs) == 1 and obs[0].arm == Arm.REAL and obs[0].moved

def test_run_measurement_gate_enforces_all_guards():
    """[C3] run_measurement 가 5개 가드를 호출 전 전부 발화 — 3-arm 누락이면 멈춤."""
    two_arm = _arm("qwen", Arm.REAL, 16, 20) + _arm("qwen", Arm.DUMMY, 6, 20)  # NEGATIVE 없음
    cf = [CounterfactualObservation("p", True, True)]
    with pytest.raises(GuardViolation):
        run_measurement(two_arm, cf, {}, min_genuine=0.5, max_unreflected_ratio=0.5)


# ── 리뷰어1 m2: exposure 완전성에 uncertain 포함 ───────────────────────

def test_exposure_completeness_includes_uncertain():
    """[m2] 판정기 불일치(불확실)를 뷰에서 떨어뜨리면 가드가 막는다."""
    from policy_lab.core.views import PresentationView, assert_exposure_complete
    claims = [Claim("c", "갈림", support=10)]
    drafts = [Draft("d1", "A"), Draft("d2", "B"), Draft("d3", "C")]
    j = [CoverJudgment("c", "d1", "j1", True, "x"), CoverJudgment("c", "d1", "j2", False)]
    m = merge(claims, drafts, j, majority_support=30, minority_threshold=5)
    # 불확실 항목을 비운 위조 뷰
    rigged = PresentationView(adopted=(), unreflected=(), needs_more=(), uncertain=())
    with pytest.raises(GuardViolation):
        assert_exposure_complete(rigged, m)
