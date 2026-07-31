"""숙의 실행 엔진 (RFC-0002) — 16 stage 를 도메인 중립으로 끝까지 실행.

instance 하드코딩을 제거한다: ``DomainPlugin`` + ``Actors`` 포트만 주입하면
protocol 의 16 stage 가 자동 실행되고, 모든 산출이 provenance·transcript·ledger 로
감사 가능하게 기록된다. runner/handler 는 어느 도메인도 직접 참조하지 않는다.

방어장치는 **강화만**(RFC-0001 §6 불변):
- preflight: ``assert_declared_purpose`` + ``assert_ab_separation`` (실행 전).
- 단계별: AI_GENERATE/IMPACT_SIM provenance 완전성 + A/B 재확인,
  HUMAN_GATE 인간 토큰 검증(LLM 승인 차단), AUDIENCE_QUERY 화이트리스트,
  IMPACT_SIM 단일숫자 거부, INTERPRET 여론단정 차단.
- 원자성: stage 산출은 가드 통과 후에만 commit (부분 commit 금지).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from .approval import HumanApprovalPort, verify_token
from .case import CaseDefinition, VoteOption
from .deliberation import (
    Actor,
    DeliberationProtocol,
    Stage,
    StageType,
    VoteRound,
    mind_change,
)
from .guards import (
    GuardViolation,
    assert_ab_separation,
    assert_declared_purpose,
    assert_not_opinion_claim,
    assert_within_whitelist,
)
from .impact import ImpactModel
from .ledger import BallotLedger
from .provenance import ProvenanceLog, ProvenanceRecord


class Actors(Protocol):
    """배우 포트 — instance 가 LLM/engine/인간 어댑터로 구현해 주입한다.

    각 메서드는 (산출, model_id[, meta]) 를 반환한다. model_id 는 provenance·A/B 검증용.
    engine 은 ``domain.impact_model()`` (A축 결정론, LLM 아님).
    """

    approval: HumanApprovalPort
    allowed_issuers: set
    engine: ImpactModel

    def declared_ai_model_ids(self) -> set: ...
    def intro(self, stage: Stage) -> tuple[str, str]: ...
    def expert_input(self, stage: Stage, options: list) -> tuple[str, str]: ...
    def ai_generate(self, stage: Stage, prompt_text: str, ctx: dict) -> tuple[str, str, dict]: ...
    def audience_query(self, stage: Stage, levers: list) -> tuple[dict, str]: ...
    def audience_vote(self, stage: Stage, options: list, ctx: dict) -> list: ...
    def expert_comment(self, stage: Stage, ctx: dict) -> tuple[str, str]: ...
    def audience_verify(self, stage: Stage, revision, ctx: dict) -> tuple[str, str]: ...
    def interpret(self, stage: Stage, ctx: dict) -> tuple[str, str]: ...
    def synthesize_revision(self, stage: Stage, inputs: dict, ctx: dict): ...


@dataclass
class StageResult:
    """한 stage 의 *미커밋* 산출. 가드 통과 후에만 runner 가 commit (원자성)."""

    artifact: object = None
    provenance: list = field(default_factory=list)        # ProvenanceRecord[]
    ballots: Optional[list] = None                         # VOTE: (pid, seg, opt_key, reason)[]
    vote_round: Optional[VoteRound] = None
    measure: Optional[dict] = None
    transcript: Optional[dict] = None                      # 사람이 읽는 기록


@dataclass
class RunResult:
    votes: dict                      # round_name -> VoteRound
    ledger: BallotLedger
    mind_changes: dict               # "from->to" -> mind_change()
    provenance: ProvenanceLog
    transcript: list                 # stage별 기록 (순서)
    case: CaseDefinition


class DeliberationRunner:
    """16 stage 오케스트레이터."""

    def __init__(self, domain, actors: Actors, prov: ProvenanceLog, timestamp: str = "",
                 seed: Optional[int] = None, actor_temperatures: Optional[dict] = None) -> None:
        self.domain = domain
        self.actors = actors
        self.prov = prov
        self.timestamp = timestamp
        self.seed = seed                 # 재현성: LLM stage provenance 에 기록(codex/gemini 결함)
        self.actor_temps = actor_temperatures or {}  # instance 주입(도메인 중립): actor→temperature
        self.ctx: dict = {}
        self.votes: dict = {}
        self.ledger = BallotLedger()
        self.transcript: list = []
        self.case: CaseDefinition = domain.build_case().validate_case(domain)

    # ---- preflight (실행 전 가드) ----
    def _preflight(self, purposes) -> None:
        assert_declared_purpose(purposes)                       # 여론측정 목적 차단
        engine_ids = {self.actors.engine.model_id}
        ai_ids = set(self.actors.declared_ai_model_ids())
        assert_ab_separation(engine_ids, ai_ids)                # A/B 사전 검증

    # ---- 메인 ----
    def run(self, purposes) -> RunResult:
        proto: DeliberationProtocol = self.domain.protocol().validate()
        self._preflight(purposes)
        for i, stage in enumerate(proto.stages):
            handler = _REGISTRY.get(stage.type)
            if handler is None:
                raise GuardViolation(f"미지원 stage type: {stage.type}")
            result = handler(self, stage, proto, i)
            self._check_guards(stage, result)      # 통과해야
            self._commit(stage, result)            # commit (원자성)
        mc = self._mind_changes()
        return RunResult(self.votes, self.ledger, mc, self.prov, self.transcript, self.case)

    # ---- 가드 (commit 전) ----
    def _check_guards(self, stage: Stage, result: StageResult) -> None:
        # provenance 완전성: 생성/계산 단계는 model_id 필수
        if stage.type in (StageType.AI_GENERATE, StageType.IMPACT_SIM):
            for rec in result.provenance:
                if not rec.model_id:
                    raise GuardViolation(f"{stage.id}: provenance model_id 누락")
            # A/B 단계별 재확인
            engine_ids = {self.actors.engine.model_id}
            ai_ids = {r.model_id for r in result.provenance
                      if r.model_id and r.actor == Actor.AI.value}
            if stage.type == StageType.AI_GENERATE:
                assert_ab_separation(engine_ids, ai_ids)

    def _commit(self, stage: Stage, result: StageResult) -> None:
        _llm_actors = {Actor.AI.value, Actor.AUDIENCE.value, Actor.EXPERT.value}
        for rec in result.provenance:
            if rec.timestamp is None:
                rec.timestamp = self.timestamp
            if rec.actor in _llm_actors:        # LLM 호출 단계: 재현성 메타 기록
                if rec.seed is None:
                    rec.seed = self.seed
                if rec.temperature is None:
                    rec.temperature = self.actor_temps.get(rec.actor)
                if rec.model_version is None and rec.model_id:
                    rec.model_version = rec.model_id
            self.prov.append(rec)
        if result.artifact is not None:
            self.ctx[stage.id] = result.artifact
        if result.vote_round is not None:
            self.votes[result.vote_round.name] = result.vote_round
        if result.ballots is not None and result.vote_round is not None:
            for (pid, seg, opt_key, _reason) in result.ballots:
                result.vote_round.record(seg, opt_key)
                self.ledger.record(pid, seg, result.vote_round.name, opt_key)
        if result.measure is not None:
            self.ctx[stage.id] = result.measure
        if result.transcript is not None:
            self.transcript.append(result.transcript)

    def _mind_changes(self) -> dict:
        names = [v for v in self.votes]
        out = {}
        for a, b in zip(names, names[1:]):
            out[f"{a}->{b}"] = mind_change(self.votes[a], self.votes[b])
        return out


# =========================================================================
# stage type 핸들러 — 각자 StageResult(미커밋) 반환. 부작용 없음(runner 가 commit).
# =========================================================================

def _prov(stage: Stage, actor: str, model_id=None, prompt_key=None, meta=None,
          inputs=None, outputs=None) -> ProvenanceRecord:
    meta = meta or {}
    return ProvenanceRecord(
        stage_id=stage.id, actor=actor, model_id=model_id, prompt_key=prompt_key,
        temperature=meta.get("temperature"), seed=meta.get("seed"),
        prompt_version=meta.get("prompt_version"),
        inputs=inputs or {}, outputs=outputs or {},
    )


def _h_intro(r: DeliberationRunner, stage, proto, i) -> StageResult:
    text, model_id = r.actors.intro(stage)
    return StageResult(
        artifact=text,
        provenance=[_prov(stage, Actor.MODERATOR.value, model_id, outputs={"text": text})],
        transcript={"stage": stage.id, "label": stage.label, "actor": "moderator", "text": text},
    )


def _h_expert_input(r: DeliberationRunner, stage, proto, i) -> StageResult:
    text, model_id = r.actors.expert_input(stage, r.case.expert_options)
    return StageResult(
        artifact={"options": r.case.expert_options, "text": text},
        provenance=[_prov(stage, Actor.EXPERT.value, model_id, outputs={"text": text})],
        transcript={"stage": stage.id, "label": stage.label, "actor": "expert",
                    "options": [o.name for o in r.case.expert_options], "text": text},
    )


def _h_ai_generate(r: DeliberationRunner, stage, proto, i) -> StageResult:
    prompt = r.domain.prompts().get(stage.prompt_key)
    # s9 수정안은 전용 합성 경로 (다입력) — synthesis_inputs 의 stage id 를
    # 투표 분포(votes) 또는 산출(ctx)에서 실제 데이터로 채운다(청중선택+전문가의견).
    if stage.prompt_key == "revision":
        inputs = {}
        for sid in r.case.synthesis_inputs:
            inputs[sid] = r.votes[sid].totals() if sid in r.votes else r.ctx.get(sid)
        option = r.actors.synthesize_revision(stage, inputs, r.ctx)
        text = option.rationale if hasattr(option, "rationale") else str(option)
        model_id = getattr(option, "model_id", None) or _ai_model(r)
        r.ctx["ai_revision"] = option.policy_option
        r.ctx["ai_revision_rationale"] = text          # ⑩⑪ 노출 계약: 수정안 근거 보존
        return StageResult(
            artifact=option.policy_option,
            provenance=[_prov(stage, Actor.AI.value, model_id, prompt_key="revision",
                              inputs={k: str(v) for k, v in inputs.items()},
                              outputs={"name": option.policy_option.name, "rationale": text})],
            transcript={"stage": stage.id, "label": stage.label, "actor": "ai",
                        "revision": option.policy_option.name, "rationale": text},
        )
    prompt_text = prompt.render(**_render_ctx(r)) if prompt else stage.label
    text, model_id, meta = r.actors.ai_generate(stage, prompt_text, r.ctx)
    meta = dict(meta or {})
    if prompt:
        meta.setdefault("prompt_version", prompt.version)
    return StageResult(
        artifact=text,
        provenance=[_prov(stage, Actor.AI.value, model_id, prompt_key=stage.prompt_key,
                          meta=meta, outputs={"text": text})],
        transcript={"stage": stage.id, "label": stage.label, "actor": "ai", "text": text},
    )


def _h_human_gate(r: DeliberationRunner, stage, proto, i) -> StageResult:
    # 직전 stage(요승인 AI 산출)를 인간 토큰으로 승인 — LLM 승인 불가.
    prev = proto.stages[i - 1] if i > 0 else None
    artifact = r.ctx.get(prev.id) if prev else None
    token = r.actors.approval.request(stage.id, artifact)
    verify_token(token, stage.id, artifact, set(r.actors.allowed_issuers))
    return StageResult(
        artifact={"approved": True, "by": token.issuer, "of": prev.id if prev else None},
        provenance=[_prov(stage, Actor.EXPERT.value, inputs={"approved_stage": prev.id if prev else None},
                          outputs={"issuer": token.issuer, "nonce": token.nonce})],
        transcript={"stage": stage.id, "label": stage.label, "actor": "human_gate",
                    "approved_by": token.issuer, "approved_stage": prev.id if prev else None},
    )


def _h_vote(r: DeliberationRunner, stage, proto, i) -> StageResult:
    options = r.case.vote_options(r.ctx)
    ballots = r.actors.audience_vote(stage, options, r.ctx)  # (pid, seg, opt_key, reason)[]
    vr = VoteRound(name=stage.id)
    # 모델 다양성을 provenance 로 (개별 표는 ledger·transcript 에)
    recs = []
    seen_models = set()
    for b in ballots:
        m = b[4] if len(b) > 4 else None
        if m and m not in seen_models:
            seen_models.add(m)
            recs.append(_prov(stage, Actor.AUDIENCE.value, m, outputs={"vote_stage": stage.id}))
    return StageResult(
        ballots=[(b[0], b[1], b[2], b[3] if len(b) > 3 else "") for b in ballots],
        vote_round=vr,
        provenance=recs,
        transcript={"stage": stage.id, "label": stage.label, "actor": "audience",
                    "options": [o.key for o in options],
                    "ballots": [{"pid": b[0], "seg": b[1], "choice": b[2],
                                 "reason": (b[3] if len(b) > 3 else "")} for b in ballots]},
    )


def _h_expert_comment(r: DeliberationRunner, stage, proto, i) -> StageResult:
    text, model_id = r.actors.expert_comment(stage, r.ctx)
    return StageResult(
        artifact=text,
        provenance=[_prov(stage, Actor.EXPERT.value, model_id, outputs={"text": text})],
        transcript={"stage": stage.id, "label": stage.label, "actor": "expert", "text": text},
    )


def _h_audience_query(r: DeliberationRunner, stage, proto, i) -> StageResult:
    levers = {lv.key: lv for lv in r.domain.levers()}
    queries, model_id = r.actors.audience_query(stage, r.domain.levers())
    for lk, val in (queries or {}).items():
        lever = levers.get(lk)
        if lever is None:
            raise GuardViolation(f"{stage.id}: 미정의 레버 질문 {lk!r}")
        assert_within_whitelist(lever, val)        # 인젝션 방어
    return StageResult(
        artifact=queries,
        provenance=[_prov(stage, Actor.AUDIENCE.value, model_id, outputs={"queries": str(queries)})],
        transcript={"stage": stage.id, "label": stage.label, "actor": "audience",
                    "variable_queries": queries},
    )


def _h_impact_sim(r: DeliberationRunner, stage, proto, i) -> StageResult:
    # A축: engine 결정론 계산 (LLM 아님). ImpactResult 가 단일숫자 차단(G-NUM).
    queries = r.ctx.get("s7a") or {}
    base = r.case.expert_options[0]
    option = base
    for lk, val in queries.items():
        option = option.with_change(lk, val)
    results = r.actors.engine.evaluate(option)      # list[ImpactResult]
    bands = [{"metric": x.metric, "direction": x.direction.value, "band": x.band} for x in results]
    return StageResult(
        artifact=results,
        provenance=[_prov(stage, Actor.ENGINE.value, r.actors.engine.model_id,
                          prompt_key="impact_sim", inputs={"option": option.name},
                          outputs={"results": bands})],
        transcript={"stage": stage.id, "label": stage.label, "actor": "engine",
                    "option": option.name, "impact": bands},
    )


def _h_verify(r: DeliberationRunner, stage, proto, i) -> StageResult:
    revision = r.ctx.get("ai_revision")
    text, model_id = r.actors.audience_verify(stage, revision, r.ctx)
    return StageResult(
        artifact=text,
        provenance=[_prov(stage, Actor.AUDIENCE.value, model_id, outputs={"text": text})],
        transcript={"stage": stage.id, "label": stage.label, "actor": "audience",
                    "verify": text, "of_revision": revision.name if revision else None},
    )


def _h_measure(r: DeliberationRunner, stage, proto, i) -> StageResult:
    names = list(r.votes)
    transitions = {}
    if len(names) >= 2:
        first, last = names[0], names[-1]
        tr = r.ledger.transitions(first, last)
        transitions = {f"{a}->{b}": n for (a, b), n in tr.items()}
        movers = r.ledger.movers(first, last)
        dist_delta = r.ledger.distribution_delta(first, last)
    else:
        movers, dist_delta = [], {}
    measure = {"transitions": transitions, "movers": movers,
               "distribution_delta": dist_delta, "rounds": names}
    return StageResult(
        measure=measure,
        provenance=[_prov(stage, Actor.ALL.value, outputs=measure)],
        transcript={"stage": stage.id, "label": stage.label, "actor": "all",
                    "measure": measure, "note": "개인 전이 ≠ 분포 delta. 표본≠민의."},
    )


def _h_interpret(r: DeliberationRunner, stage, proto, i) -> StageResult:
    text, model_id = r.actors.interpret(stage, r.ctx)
    assert_not_opinion_claim(text)        # 여론 단정 차단
    return StageResult(
        artifact=text,
        # interpret 는 실제 LLM(AI팀) 호출 → provenance actor=AI 로 기록해야 seed/temp/version 채워짐
        # (stage.actor 는 ALL 이지만 호출 주체는 AI). measure(s11m)와 달리 LLM 호출이다.
        provenance=[_prov(stage, Actor.AI.value, model_id, outputs={"text": text})],
        transcript={"stage": stage.id, "label": stage.label, "actor": "all", "text": text},
    )


_REGISTRY = {
    StageType.INTRO: _h_intro,
    StageType.EXPERT_INPUT: _h_expert_input,
    StageType.AI_GENERATE: _h_ai_generate,
    StageType.HUMAN_GATE: _h_human_gate,
    StageType.VOTE: _h_vote,
    StageType.EXPERT_COMMENT: _h_expert_comment,
    StageType.AUDIENCE_QUERY: _h_audience_query,
    StageType.IMPACT_SIM: _h_impact_sim,
    StageType.VERIFY: _h_verify,
    StageType.MEASURE: _h_measure,
    StageType.INTERPRET: _h_interpret,
}


def _ai_model(r: DeliberationRunner) -> str:
    ids = list(r.actors.declared_ai_model_ids())
    return ids[0] if ids else "ai:unknown"


def _render_ctx(r: DeliberationRunner) -> dict:
    """프롬프트 치환용 컨텍스트 — 앞 단계 산출을 문자열로."""
    opts = r.case.expert_options
    return {
        "policy": " / ".join(f"[{o.name}] {o.lever_values}" for o in opts),
        "evidence": "(고정 근거)", "fixed": "(고정 변수)",
        "scenario": str(r.ctx.get("s4", "")),
        "levers": ", ".join(lv.key for lv in r.domain.levers()),
        "variable": str(r.ctx.get("s7a", "")),
        "impact": str(r.ctx.get("s7b", "")),
    }


@dataclass
class RevisionResult:
    """s9 수정안 합성 산출 — structured PolicyOption + 근거 + model."""

    policy_option: object       # PolicyOption (origin="ai_revision")
    rationale: str = ""
    model_id: Optional[str] = None
