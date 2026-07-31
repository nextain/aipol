"""DeliberationRunner integration test (RFC-0002 §7).

검증: (1) 16 stage end-to-end 가 끝까지 돌고 votes/ledger/provenance/transcript 가 남는다.
(2) **7가드가 runner 실행 중 실제로 차단**한다 (가드를 우회하면 RED).
(3) stage 실패 시 부분 commit 이 없다(원자성).
"""
from __future__ import annotations

import copy

import pytest

from policy_lab.core.approval import ApprovalToken, PreapprovedTokenPort, digest_artifact
from policy_lab.core.guards import GuardViolation, MeasurementPurpose
from policy_lab.core.levers import PolicyOption
from policy_lab.core.provenance import ProvenanceLog
from policy_lab.core.runners import DeliberationRunner, RevisionResult
from policy_lab.domains.pension.plugin import PensionDomain

S5A_TEXT = "쟁점 3개: 수급연령(찬/반)·국고투입(찬/반)·기초연금(찬/반)"
PURPOSES = [MeasurementPurpose.OPERATIONAL, MeasurementPurpose.FRAMING_SENSITIVITY]


class MockActors:
    """결정론 mock — 실제 LLM 없이 16 stage 를 끝까지 돌린다."""

    def __init__(self, domain):
        self.engine = domain.impact_model()
        self.allowed_issuers = {"expert:박교수"}
        token = ApprovalToken("expert:박교수", "s5gate", digest_artifact(S5A_TEXT), "n1")
        self.approval = PreapprovedTokenPort([token], self.allowed_issuers)
        self._ai = "ai:mock-qwen"

    def declared_ai_model_ids(self):
        return {self._ai}

    def intro(self, stage):
        return ("오프닝: 오늘 절차를 설명합니다.", "moderator:mock")

    def expert_input(self, stage, options):
        return ("전문가 1·2안을 제시합니다.", "expert:박교수")

    def ai_generate(self, stage, prompt_text, ctx):
        if stage.id == "s5a":
            return (S5A_TEXT, self._ai, {"temperature": 0.2, "seed": 7})
        return (f"[{stage.id}] 산출 텍스트", self._ai, {"temperature": 0.2, "seed": 7})

    def audience_query(self, stage, levers):
        for lv in levers:                        # 도메인 중립: numeric 레버 자동 탐색
            if lv.numeric_range:
                lo, hi = lv.numeric_range
                return ({lv.key: (lo + hi) / 2}, self._ai)
        return ({}, self._ai)

    def audience_vote(self, stage, options, ctx):
        keys = [o.key for o in options]
        ballots = []
        for n in range(12):
            seg = ("youth", "middle", "senior")[n % 3]
            # 9명 opt1, 나머지는 마지막 라운드에 일부 이동 (전이 생성)
            choice = keys[0]
            if stage.id == "s11" and n in (0, 3):
                choice = keys[1]
            ballots.append((f"{seg}-{n:02d}", seg, choice, f"이유 {n}", self._ai))
        return ballots

    def expert_comment(self, stage, ctx):
        return (f"[{stage.id}] 전문가 코멘트(비용·제약).", "expert:박교수")

    def audience_verify(self, stage, revision, ctx):
        return ("수정안의 약점: 전환기 부담.", self._ai)

    def interpret(self, stage, ctx):
        return ("오늘 이 자리의 선택 패턴입니다. 표본은 민의가 아닙니다.", self._ai)

    def synthesize_revision(self, stage, inputs, ctx):
        base = ctx["s2"]["options"][0] if "s2" in ctx else PolicyOption("base", {})
        revised = PolicyOption(
            name="AI수정안(점진형)",
            lever_values={"수급연령": "단계적 상향", "국고투입": "확대", "기초연금": "혼합형"},
            origin="ai_revision",
        )
        return RevisionResult(revised, "청중선택+전문가의견 합성: 단계적·점진적 조합.", self._ai)


def _run(actors=None, purposes=PURPOSES):
    domain = PensionDomain()
    actors = actors or MockActors(domain)
    runner = DeliberationRunner(domain, actors, ProvenanceLog(), timestamp="2026-06-24T00:00:00Z")
    return runner.run(purposes)


# ---------------- (1) end-to-end ----------------

def test_full_run_completes_16_stages():
    res = _run()
    assert len(res.transcript) == 16                      # 16 stage 전부
    assert set(res.votes) == {"s3", "s5b", "s11"}         # 3회 투표
    # ⑪ 최종은 3지선다 (AI수정안 포함)
    s11 = res.transcript[[t["stage"] for t in res.transcript].index("s11")]
    assert "revision" in s11["options"]

def test_ledger_tracks_individual_transitions():
    res = _run()
    movers = res.ledger.movers("s3", "s11")
    assert len(movers) == 2                                # 개인 2명 이동
    # 분포 delta 와 개인 전이는 구분 기록
    delta = res.ledger.distribution_delta("s3", "s11")
    assert delta["opt2"] == 2 and delta["opt1"] == -2

def test_provenance_records_models_and_ab():
    res = _run()
    ids = res.provenance.model_ids()
    assert "ai:mock-qwen" in ids and any(m.startswith("impact:") for m in ids)


# ---------------- (2) 7가드 차단 ----------------

def test_guard_ab_separation_blocks_shared_model():
    domain = PensionDomain()
    actors = MockActors(domain)
    actors.declared_ai_model_ids = lambda: {actors.engine.model_id}   # A=B 공유
    with pytest.raises(GuardViolation, match="A/B 분리"):
        _run(actors)

def test_guard_human_gate_blocks_llm_issuer():
    domain = PensionDomain()
    # LLM 이 발급한 토큰 → PreapprovedTokenPort 가 거부
    with pytest.raises(GuardViolation, match="허용 목록 밖|승인할 수 없"):
        PreapprovedTokenPort(
            [ApprovalToken("ai:mock-qwen", "s5gate", "x", "n1")], {"expert:박교수"}
        )

def test_guard_human_gate_blocks_missing_token():
    domain = PensionDomain()
    actors = MockActors(domain)
    actors.approval = PreapprovedTokenPort([], {"expert:박교수"})      # 토큰 없음
    with pytest.raises(GuardViolation, match="유효한 인간 승인 토큰 없음"):
        _run(actors)

def test_guard_whitelist_blocks_out_of_range():
    domain = PensionDomain()
    actors = MockActors(domain)
    actors.audience_query = lambda stage, levers: ({"수급연령": 99}, "ai:mock-qwen")
    with pytest.raises(GuardViolation, match="화이트리스트"):
        _run(actors)

def test_guard_provenance_blocks_missing_model_id():
    domain = PensionDomain()
    actors = MockActors(domain)
    orig = actors.ai_generate
    actors.ai_generate = lambda s, p, c: (orig(s, p, c)[0], "", {})   # model_id 누락
    with pytest.raises(GuardViolation, match="model_id 누락"):
        _run(actors)

def test_guard_declared_purpose_blocks_opinion_measurement():
    with pytest.raises(GuardViolation, match="여론 측정"):
        _run(purposes=[MeasurementPurpose.OPINION_MEASUREMENT])

def test_guard_not_opinion_claim_blocks_verdict():
    domain = PensionDomain()
    actors = MockActors(domain)
    actors.interpret = lambda s, c: ("국민이 1안을 지지한다.", "ai:mock-qwen")
    with pytest.raises(GuardViolation, match="여론.*단정|단정"):
        _run(actors)

def test_guard_single_number_blocks_in_impact():
    # ImpactResult band 가 단일 정밀 숫자면 생성 시점에 차단(G-NUM)
    from policy_lab.core.impact import Direction, ImpactResult
    with pytest.raises(GuardViolation):
        ImpactResult("재정", Direction.WORSENS, "12조")


# ---------------- 도메인 중립 증명 (RFC §7) ----------------

def test_domain_neutral_runner_drives_non_pension_domain():
    """같은 runner 가 pension 을 전혀 참조하지 않는 stub 도메인을 끝까지 돌린다.

    codex "plugin 교체만으로 된다는 주장은 과장" 에 대한 실증 — runner/handler 가
    도메인 콘텐츠를 DomainPlugin·CaseDefinition 계약으로만 받는지 확인.
    """
    from policy_lab.core.case import CaseDefinition, VoteOption
    from policy_lab.core.deliberation import Segment
    from policy_lab.core.evidence import EvidenceStore
    from policy_lab.core.impact import Direction, ImpactModel, ImpactResult
    from policy_lab.core.levers import Lever
    from policy_lab.core.plugin import DomainPlugin

    class HousingImpact(ImpactModel):
        model_id = "impact:housing-v0"
        def evaluate(self, option):
            return [ImpactResult("공급", Direction.IMPROVES, "증가 방향(범위)")]

    class HousingDomain(DomainPlugin):
        key = "housing"
        label = "주거 정책(stub)"
        def levers(self):
            return [Lever("공급방식", "공급 방식", options=("공공", "민간"))]
        def fixed_variables(self):
            return []
        def evidence(self):
            return EvidenceStore()
        def impact_model(self):
            return HousingImpact()
        def segments(self):
            return [Segment("all", "전체", (1.0, 1.0))]
        def prompts(self):
            return {}
        def build_case(self):
            a = PolicyOption("공공안", {"공급방식": "공공"}, origin="expert")
            b = PolicyOption("민간안", {"공급방식": "민간"}, origin="expert")
            return CaseDefinition(
                version="0.1", source="stub",
                expert_options=[a, b],
                vote_options=lambda ctx: [VoteOption("a", a.name, a), VoteOption("b", b.name, b)],
                synthesis_inputs=[],
            )

    domain = HousingDomain()
    actors = MockActors(domain)            # 같은 mock, engine 만 housing 으로 바뀜
    runner = DeliberationRunner(domain, actors, ProvenanceLog(), timestamp="t")
    res = runner.run(PURPOSES)
    assert len(res.transcript) == 16
    assert "impact:housing-v0" in res.provenance.model_ids()
    assert res.case.source == "stub"       # pension 콘텐츠 미참조


# ---------------- (3) 원자성 ----------------

def test_atomic_no_partial_commit_on_failure():
    domain = PensionDomain()
    actors = MockActors(domain)
    actors.audience_query = lambda stage, levers: ({"수급연령": 99}, "ai:mock-qwen")  # s7a 실패
    prov = ProvenanceLog()
    runner = DeliberationRunner(domain, actors, prov, timestamp="t")
    with pytest.raises(GuardViolation):
        runner.run(PURPOSES)
    # s7a 가 실패했으면 s7a artifact 는 commit 되지 않아야(부분 commit 금지)
    assert "s7a" not in runner.ctx
