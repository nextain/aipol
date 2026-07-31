"""[2] LLM sub-runner DAG 계약 테스트 (RFC-0003 §3·§7).

클라우드 호출 없이 stub ChatClient 로 오케스트레이션 전체를 검증한다:
DAG 가 결정론 코어에 유효한 입력을 흘려보내는가 + 가드가 호출 전 발화하는가.
프롬프트 문구가 아니라 **구조**를 테스트한다(프롬프트는 실험 단계서 튜닝).
"""
import json

import pytest

from policy_lab.core.guards import GuardViolation
from policy_lab.core.responses import CitizenResponse, ProposalResponse, Stance
from policy_lab.core.synthesis import Disposition
from policy_lab.core.synthesis_runner import (
    Flagship,
    SynthesisConfig,
    run_synthesis,
    draft_proposals,
    judge_cover,
    _extract_json,
)


FLAGSHIPS = (
    Flagship("codex-5.5", "openai", "openai"),
    Flagship("gemini-3.5-flash", "google", "google"),
    Flagship("glm-5.2", "zhipu", "zhipu"),
    Flagship("claude-opus-4.8", "anthropic", "anthropic"),
)
JUDGES = ("qwen-judge", "solar-judge")


def _responses():
    """2 시민, 조건부·거부 자유텍스트 보유 (claim 추출 재료)."""
    props = ("1안", "2안", "3안")
    r1 = CitizenResponse("K1", "senior", "qwen", {
        "1안": ProposalResponse("1안", Stance.CONDITIONAL, "저소득 고령자 예외면 수용"),
        "2안": ProposalResponse("2안", Stance.REJECT, "재정 부담이 과도"),
        "3안": ProposalResponse("3안", Stance.ACCEPT),
    }, proposals=props)
    r2 = CitizenResponse("K2", "youth", "qwen", {
        "1안": ProposalResponse("1안", Stance.REJECT, "청년 부담 가중"),
        "2안": ProposalResponse("2안", Stance.CONDITIONAL, "대체율 상한 두면 수용"),
        "3안": ProposalResponse("3안", Stance.ACCEPT),
    }, proposals=props)
    return [r1, r2]


class FakeClient:
    """system 프롬프트로 어느 단계인지 구분해 캔드 JSON 반환 (DAG 배선만 검증)."""

    def __call__(self, model, messages, *, temperature=0.7, provider=None):
        sys = messages[0]["content"]
        if "claim 추출기" in sys:
            return json.dumps([
                {"cid": "c1", "text": "저소득 고령자 예외", "support": 40, "segments": ["senior"]},
                {"cid": "c2", "text": "청년 부담 완화", "support": 35, "segments": ["youth"]},
                {"cid": "c3", "text": "대체율 상한", "support": 5, "segments": ["youth"]},
            ])
        if "통합안 초안가" in sys:
            return json.dumps({"clauses": [
                {"clause_id": f"{model[:3]}_1", "text": "고령자 예외 조항"},
                {"clause_id": f"{model[:3]}_2", "text": "청년 완화 조항"},
            ]})
        if "적대 리뷰어" in sys:
            return "이 안은 청년 트레이드오프를 다소 은폐함."
        if "cover 판정기" in sys:
            # claim 줄만 보고 cover 결정(조항 본문 단어 오염 방지): c1·c2 cover, c3 미cover
            claim_line = messages[1]["content"].split("\n", 1)[0]
            covered = ("고령자" in claim_line) or ("부담" in claim_line)
            cid = "x1" if covered else ""
            return json.dumps({"covered": covered, "clause_id": cid})
        raise AssertionError(f"알 수 없는 단계: {sys[:30]}")


def _cfg(**kw):
    base = dict(
        flagships=FLAGSHIPS, judges=JUDGES, extractor="extractor-model",
        majority_support=30, minority_threshold=20,
    )
    base.update(kw)
    return SynthesisConfig(**base)


def test_full_dag_produces_valid_merge():
    """추출→초안→리뷰→판정→merge 가 끝까지 흘러 유효한 통합안을 낸다."""
    res = run_synthesis(FakeClient(), _responses(), _cfg())
    assert len(res.claims) == 3
    assert len(res.drafts) == 4                 # 4 플래그십
    assert len(res.reviews) == 4                # 초안당 1 리뷰
    # 판정: 3 claim × 4 초안 × 2 판정기 = 24
    assert len(res.judgments) == 24
    disp = {d.claim.cid: d.disposition for d in res.merged.decisions}
    assert disp["c1"] == Disposition.REFLECTED     # 4 초안 cover (k=4)
    assert disp["c2"] == Disposition.REFLECTED
    # c3: k=0, 지지 5 < majority_support 30 이고 < minority 20 → UNREFLECTED
    assert disp["c3"] == Disposition.UNREFLECTED


def test_c3_low_support_unreflected():
    """소수+미cover claim 은 미반영으로 정직 노출 (봉합 안 함)."""
    res = run_synthesis(FakeClient(), _responses(), _cfg())
    c3 = next(d for d in res.merged.decisions if d.claim.cid == "c3")
    assert c3.cover == 0
    assert c3.disposition == Disposition.UNREFLECTED


def test_guard_fires_on_single_company_drafts():
    """초안가 회사 <3 이면 draft 단계 진입서 거부 (§6)."""
    one_co = (Flagship("a", "openai"), Flagship("b", "openai"), Flagship("c", "openai"))
    with pytest.raises(GuardViolation):
        draft_proposals(FakeClient(), [], _cfg(flagships=one_co))


def test_guard_fires_on_judge_overlap():
    """판정기가 초안가와 겹치면 judge 단계 진입서 거부 (§6 자기 채점)."""
    with pytest.raises(GuardViolation):
        judge_cover(FakeClient(), [], list(FLAGSHIPS), _cfg(judges=("codex-5.5", "solar-judge")))


def test_empty_response_surfaces():
    """빈 LLM 응답은 삼키지 않고 드러낸다 (§7 동시성 간섭 교훈)."""
    with pytest.raises(ValueError):
        _extract_json("")
    with pytest.raises(ValueError):
        _extract_json("   ")


def test_second_fixture_non_pension():
    """페르소나/도메인 비종속 (§6 2nd-fixture): 연금이 아닌 교통 도메인으로도 돈다.

    sub-runner 는 도메인 어휘를 모른다 — 응답 구조만 흘려보낸다.
    """
    props = ("버스안", "지하철안", "혼합안")
    r1 = CitizenResponse("T1", "driver", "qwen", {
        "버스안": ProposalResponse("버스안", Stance.CONDITIONAL, "배차 간격 줄이면 수용"),
        "지하철안": ProposalResponse("지하철안", Stance.REJECT, "건설비 과다"),
        "혼합안": ProposalResponse("혼합안", Stance.ACCEPT),
    }, proposals=props)

    class TrafficFake(FakeClient):
        def __call__(self, model, messages, *, temperature=0.7, provider=None):
            if "claim 추출기" in messages[0]["content"]:
                return json.dumps([{"cid": "t1", "text": "배차 간격 단축", "support": 40}])
            return super().__call__(model, messages, temperature=temperature, provider=provider)

    res = run_synthesis(TrafficFake(), [r1], _cfg(majority_support=30, minority_threshold=20))
    assert len(res.claims) == 1 and len(res.drafts) == 4
    assert res.merged.decisions  # 통합안이 나온다 — 도메인 무관
