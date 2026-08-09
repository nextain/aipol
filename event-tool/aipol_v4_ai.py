"""Server-side AI execution for the pension v4 issue and D-generation gates."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import ai_config as CFG
import llm
from policy_lab.domains.pension.experiment import ExperimentError

from aipol_store import content_hash


ISSUE_PROMPT_VERSION = "aipol-pension-v4-issues-2026-08-08-r1"
COUNCIL_PROMPT_VERSION = "aipol-pension-v4-council-2026-08-08-r2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _active_unique_company_models() -> list[dict]:
    selected: list[dict] = []
    companies: set[str] = set()
    for model in CFG.active_dokpamo():
        company = str(model.get("company") or "").strip()
        if not company or company in companies:
            continue
        companies.add(company)
        selected.append(dict(model))
    if len(selected) < CFG.MIN_DRAFTER_COMPANIES:
        raise ExperimentError(
            f"실제 호출 가능한 독립 AI 회사가 {CFG.MIN_DRAFTER_COMPANIES}곳보다 적어 실행을 중단했습니다"
        )
    return selected[:3]


def _json_call(model: dict, *, system: str, payload: dict, temperature: float) -> dict:
    try:
        raw = llm.ask(
            model,
            system,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            temperature=temperature,
        )
        parsed = llm.extract_json(raw)
    except Exception as exc:
        label = str(model.get("label") or model.get("company") or "AI")
        raise ExperimentError(f"{label} 모델 호출 또는 JSON 검증에 실패했습니다") from exc
    if not isinstance(parsed, dict):
        raise ExperimentError("AI가 JSON 객체가 아닌 결과를 반환했습니다")
    return parsed


def generate_issue_classification(source: dict) -> dict:
    models = CFG.active_dokpamo()
    if not models:
        raise ExperimentError("실제 호출 가능한 쟁점 분류 AI가 없어 실행을 중단했습니다")
    model = dict(models[0])
    system = (
        "너는 국민연금 공론장의 의견 분류자다. 제공된 M1 참가자 의견만 근거로 정확히 5개 핵심 "
        "정책 쟁점을 도출하라. 각 참가자는 가장 핵심적인 쟁점 하나에 정확히 한 번 배정한다. "
        "찬반이나 선택지를 새로 만들지 말고, 의견 수는 계산하지 말라(서버가 고유 참가자를 센다). "
        "개인 연금 계산이나 개인별 예상 수령액을 만들지 말라. JSON 객체만 반환하라: "
        '{"issues":[{"issue_id":"issue-1","title":"...","summary":"...",'
        '"expert_prompt":"..."}],"assignments":[{"participant":"원문 pseudonym",'
        '"issue_id":"issue-1","rationale":"원문에 근거한 짧은 분류 이유"}]}'
    )
    output = _json_call(
        model,
        system=system,
        payload={
            "prompt_version": ISSUE_PROMPT_VERSION,
            "m1_aggregate": source["m1_aggregate"],
            "opinions": source["opinions"],
        },
        temperature=0.2,
    )
    return {
        "m1_aggregate_hash": source["m1_aggregate"]["aggregate_hash"],
        "prompt_version": ISSUE_PROMPT_VERSION,
        "model": str(model["model"]),
        "provider": str(model["provider"]),
        "deployment": str(model.get("deployment") or model["model"]),
        "generated_at": _now(),
        "issues": output.get("issues"),
        "assignments": output.get("assignments"),
    }


def generate_council(source: dict) -> dict:
    models = _active_unique_company_models()
    base_hash = source["input_hash"]
    shared_rule = (
        "제공된 승인 출처 묶음, 승인된 5대 쟁점, M1·M2 실제 의견, 사람이 검수한 1·2차 "
        "숙의 요약만 근거로 사용한다. 승인된 하드 제약은 모두 충족하고 소프트 제약은 가능한 "
        "범위에서 충족한다. 최종안은 모든 제약을 constraint_id별로 판정하고 근거를 설명한다. "
        "A/B/C와 구분되는 D안을 만들되 개인 연금 계산·개인 예상 수령액을 만들지 않는다. "
        "반영한 의견, 트레이드오프, 미반영 의견과 한계를 숨기지 않는다. JSON 객체만 반환한다."
    )
    proposal = _json_call(
        models[0],
        system=(
            "너는 3-AI 협의의 제안 담당이다. " + shared_rule +
            ' 형식: {"title":"...","body":"...","limitations":"...",'
            '"reflection_map":["..."],"tradeoffs":["..."],"unaddressed":["..."],'
            '"constraint_verdicts":[{"constraint_id":"...","level":"hard|soft",'
            '"satisfied":true,"explanation":"..."}]}'
        ),
        payload={"prompt_version": COUNCIL_PROMPT_VERSION, "phase": "proposal", "source": source},
        temperature=0.35,
    )
    proposal_hash = content_hash(proposal)
    review_input_hash = content_hash({"council_input_hash": base_hash, "proposal": proposal_hash})
    review = _json_call(
        models[1],
        system=(
            "너는 3-AI 협의의 독립 상호검토 담당이다. 제안이 원장의 시민 의견과 숙의 요약을 "
            "왜곡·누락했는지, 정책 트레이드오프와 실행 한계를 숨겼는지 검토하라. " + shared_rule +
            ' 형식: {"findings":["..."],"required_revisions":["..."],'
            '"preserve":["..."],"remaining_risks":["..."]}'
        ),
        payload={
            "prompt_version": COUNCIL_PROMPT_VERSION,
            "phase": "cross_review",
            "source": source,
            "proposal": proposal,
        },
        temperature=0.25,
    )
    review_hash = content_hash(review)
    revision_input_hash = content_hash({
        "council_input_hash": base_hash,
        "proposal": proposal_hash,
        "cross_review": review_hash,
    })
    revision = _json_call(
        models[2],
        system=(
            "너는 3-AI 협의의 최종 수정 담당이다. 제안과 상호검토를 대조해 검토 요구를 반영한 "
            "최종 D안을 작성하라. 근거 없는 수치를 추가하지 말고, 한계와 의의를 전문가가 설명할 수 "
            "있게 명시하라. " + shared_rule +
            ' 형식: {"title":"...","body":"...","limitations":"...",'
            '"reflection_map":["..."],"tradeoffs":["..."],"unaddressed":["..."],'
            '"constraint_verdicts":[{"constraint_id":"...","level":"hard|soft",'
            '"satisfied":true,"explanation":"..."}]}'
        ),
        payload={
            "prompt_version": COUNCIL_PROMPT_VERSION,
            "phase": "revision",
            "source": source,
            "proposal": proposal,
            "cross_review": review,
        },
        temperature=0.25,
    )
    generated_at = _now()
    phase_values = (
        ("proposal", "D안 제안", models[0], base_hash, proposal),
        ("cross_review", "독립 상호검토", models[1], review_input_hash, review),
        ("revision", "검토 반영 최종 수정", models[2], revision_input_hash, revision),
    )
    steps = []
    for phase, role, model, input_hash, output in phase_values:
        steps.append({
            "phase": phase,
            "role": role,
            "model": str(model["model"]),
            "company": str(model["company"]),
            "provider": str(model["provider"]),
            "deployment": str(model.get("deployment") or model["model"]),
            "prompt_version": f"{COUNCIL_PROMPT_VERSION}:{phase}",
            "input_hash": input_hash,
            "output": output,
            "output_hash": content_hash(output),
            "generated_at": generated_at,
        })
    return {
        "input_hashes": source["input_hashes"],
        "prompt_version": COUNCIL_PROMPT_VERSION,
        "generated_at": generated_at,
        "steps": steps,
        "final_content": revision,
    }
