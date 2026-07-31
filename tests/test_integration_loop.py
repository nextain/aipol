"""전체 시민 루프 통합 — [1]→[2]→[3a]→[4]→[3b] 가 실제로 합쳐지는가 (RFC-0003).

격리 단위 테스트가 못 잡는 **이음새**를 관통으로 드러낸다(메모리: 계약 리뷰는 런타임
바인딩을 못 잡는다 — 한 슬라이스 실배선으로 조기 노출). 클라우드 비용 없이 stub 플래그십,
실 측정. 실 클라우드/실 시민 실행은 판정기 선정(§9) 후 config 교체일 뿐 — 토폴로지는 동일.

적대 리뷰(2026-06-26) 반영: [4]는 손으로 만든 ArmObservation 리터럴이 아니라 **ledger
어댑터(ledger_to_arm_obs) + run_measurement 게이트**로 측정한다 — 이음새가 코드로 존재함을
관통으로 증명(이전 '가짜 이음새' 비판 해소). [3b]는 claim_pids 를 손으로 안 주고 Claim.pids
에서 자동 유도한다.
"""
import json

from policy_lab.core.responses import (
    CitizenResponse, ProposalResponse, Stance, ResponseLedger,
)
from policy_lab.core.synthesis import Disposition
from policy_lab.core.synthesis_runner import (
    Flagship, SynthesisConfig, run_synthesis,
)
from policy_lab.core.views import build_presentation, build_reflection_paths
from policy_lab.core.measurement import (
    Arm, ledger_to_arm_obs, run_measurement, CounterfactualObservation,
)


FLAGSHIPS = (
    Flagship("codex-5.5", "openai"),
    Flagship("gemini-3.5-flash", "google"),
    Flagship("glm-5.2", "zhipu"),
    Flagship("claude-opus-4.8", "anthropic"),
)
JUDGES = ("qwen-judge", "solar-judge")
PROPS = ("1안", "2안", "3안")


class LoopFakeClient:
    """[2] 전 단계 stub — 고령자/청년 claim 을 4 초안이 cover, fringe 는 미cover.

    추출기는 claim 별 pids 를 함께 낸다([3b] 자동 유도 재료) — 실 추출기 계약과 동형.
    """

    def __call__(self, model, messages, *, temperature=0.7, provider=None):
        sys = messages[0]["content"]
        if "claim 추출기" in sys:
            return json.dumps([
                {"cid": "elder", "text": "저소득 고령자 예외", "support": 38,
                 "segments": ["senior"], "pids": ["K1"]},
                {"cid": "youth", "text": "청년 부담 완화", "support": 41,
                 "segments": ["youth"], "pids": ["K2"]},
                {"cid": "fringe", "text": "주식 연동 사적연금", "support": 2,
                 "segments": ["youth"], "pids": ["K2"]},
            ])
        if "통합안 초안가" in sys:
            return json.dumps({"clauses": [
                {"clause_id": f"{model[:3]}_e", "text": "고령자 예외 조항"},
                {"clause_id": f"{model[:3]}_y", "text": "청년 완화 조항"},
            ]})
        if "적대 리뷰어" in sys:
            return "트레이드오프(고령 보장↔청년 부담)를 더 드러낼 것."
        if "cover 판정기" in sys:
            line = messages[1]["content"].split("\n", 1)[0]
            covered = ("고령자" in line) or ("청년" in line)  # fringe(주식)은 미cover
            return json.dumps({"covered": covered, "clause_id": "c" if covered else ""})
        raise AssertionError(sys[:20])


def _stage1_responses():
    """[1] 다차원 수집 — 2 시민, 조건부·거부 텍스트 보유 (claim 추출 재료)."""
    r1 = CitizenResponse("K1", "senior", "qwen", {
        "1안": ProposalResponse("1안", Stance.CONDITIONAL, "저소득 고령자 예외면 수용"),
        "2안": ProposalResponse("2안", Stance.REJECT, "재정 부담 과도"),
        "3안": ProposalResponse("3안", Stance.CONDITIONAL, "고령 보장 담기면"),
    }, proposals=PROPS)
    r2 = CitizenResponse("K2", "youth", "solar", {
        "1안": ProposalResponse("1안", Stance.REJECT, "청년 부담 가중"),
        "2안": ProposalResponse("2안", Stance.CONDITIONAL, "대체율 상한 두면"),
        "3안": ProposalResponse("3안", Stance.REJECT, "주식 연동 사적연금 원함"),
    }, proposals=PROPS)
    return [r1, r2]


def test_full_loop_composes_and_closes():
    """[1] 수집 → [2] 숙의 → [3a] 제시 → [3b] 경로 → [4] 측정 이 끝까지 합쳐진다."""
    # ── [1] 수집 + ledger 기록 (1차 round) ──
    responses = _stage1_responses()
    led = ResponseLedger()
    for cr in responses:
        led.record("collect", cr)
    assert led.stance_dist("collect", "1안")["reject"] == 1

    # ── [2] 숙의 (stub 플래그십) — 통합안 + 미반영 노출 ──
    cfg = SynthesisConfig(
        flagships=FLAGSHIPS, judges=JUDGES, extractor="extractor",
        majority_support=30, minority_threshold=20,
    )
    syn = run_synthesis(LoopFakeClient(), responses, cfg)  # assert_reflection_completeness 내부
    disp = {d.claim.cid: d.disposition for d in syn.merged.decisions}
    assert disp["elder"] == Disposition.REFLECTED      # 4 cover
    assert disp["youth"] == Disposition.REFLECTED
    assert disp["fringe"] == Disposition.UNREFLECTED   # 미cover·소수 → 정직 미반영
    # claim 에 pids 가 실려 [3b] 가 손 매핑 없이 돈다
    assert {c.cid: c.pids for c in syn.claims}["elder"] == ("K1",)

    # ── [3a] 제시 — 미반영(fringe)이 통합안과 같은 구조에 노출(누락 불가) ──
    view = build_presentation(syn.merged, syn.reviews)
    assert {e.claim_id for e in view.unreflected} == {"fringe"}
    assert len(view.adopted) == 2
    assert view.reviews  # 교차리뷰 지적 동반

    # ── [3b] 반영 경로 — claim_pids 를 Claim.pids 에서 자동 유도(손 매핑 없음) ──
    real_obs_k = [
        _ob("K1", "senior", "qwen", Arm.REAL, Stance.CONDITIONAL, Stance.ACCEPT),
        _ob("K2", "youth", "solar", Arm.REAL, Stance.REJECT, Stance.CONDITIONAL),
    ]
    paths = build_reflection_paths(syn.merged, real_obs_k)  # claim_pids=None → 자동
    by = {p.pid: p for p in paths}
    assert by["K1"].moved and by["K2"].moved
    # K2 는 youth(반영) + fringe(미반영) 둘 다 자기 경로에 — 반영·미반영 동시 추적
    k2 = {s.claim_id: s.disposition for s in by["K2"].steps}
    assert k2["youth"] == "reflected" and k2["fringe"] == "unreflected"

    # ── [4] 재의견 — ledger 어댑터 + run_measurement 게이트(손 리터럴 아님) ──
    mled = _arm_ledger()
    obs = ledger_to_arm_obs(
        mled, "통합안", baseline_round="base",
        arm_rounds={"real": Arm.REAL, "dummy": Arm.DUMMY, "negative": Arm.NEGATIVE},
    )
    # qwen·solar 2모델 × 3arm 이 ledger 에서 그대로 흘러나온다
    assert {o.citizen_model for o in obs} == {"qwen", "solar"}
    assert {o.arm for o in obs} == {Arm.REAL, Arm.DUMMY, Arm.NEGATIVE}

    cf = [CounterfactualObservation(f"p{i}", True, i % 4 != 0) for i in range(20)]
    # 집단별 미반영률(fringe 가 youth 라 youth=0.5, senior=0)
    unreflected_by_seg = {"senior": 0.0, "youth": 0.5}
    result = run_measurement(
        obs, cf, unreflected_by_seg,
        min_genuine=0.5, max_unreflected_ratio=0.6,
    )
    assert result.placebo.works           # ①Δ 유의 양 + ③<②
    assert result.invariance.signs_agree  # 2모델 부호 일관(양)


# ── 헬퍼 ────────────────────────────────────────────────────────────────

def _ob(pid, seg, model, arm, before, after):
    from policy_lab.core.measurement import ArmObservation
    return ArmObservation(pid, seg, model, arm, before, after)


def _resp_single(pid, seg, model, stance):
    return CitizenResponse(pid, seg, model,
                           {"통합안": ProposalResponse("통합안", stance)}, proposals=("통합안",))


def _arm_ledger():
    """base + real/dummy/negative round 로 채운 ledger (between-subject, 2모델).

    real 16/20·dummy 6/20·negative 2/20 (양 모델 동일) → Δ 유의 양, ③<②, 부호 일관.
    """
    led = ResponseLedger()
    plan = {"real": (Arm.REAL, 16), "dummy": (Arm.DUMMY, 6), "negative": (Arm.NEGATIVE, 2)}
    for model, seg in (("qwen", "senior"), ("solar", "youth")):
        for round_id, (_arm, moved) in plan.items():
            for i in range(20):
                pid = f"{model}_{round_id}_{i}"
                led.record("base", _resp_single(pid, seg, model, Stance.REJECT))
                after = Stance.ACCEPT if i < moved else Stance.REJECT
                led.record(round_id, _resp_single(pid, seg, model, after))
    return led
