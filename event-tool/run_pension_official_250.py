#!/usr/bin/env python3
"""실제 행사 순서와 국내 주권 LLM 3사 계약을 고정한 250명 합성 검증기."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Semaphore
from typing import Any, Callable

import ai_config as CFG
import llm

OPTIONS = ("A", "B", "C")
ACCEPTANCE = ("accept", "conditional_accept", "reject")
PROMPT_VERSION = "pension-official-domestic-v1-20260806"
POLICIES = {
    "A": "보장 강화형: 65세 수급, 안정형 5.5%, 매년 GDP 0.6% 지원",
    "B": "재정 균형형: 68세로 점진 상향, 안정형 5.5%, 2026·2027년 각 50조원과 이후 GDP 0.25% 지원",
    "C": "수익 강화형: 68세로 점진 상향, 적극형 6.0%, 정기 지원 없음(5년마다 평가)",
}
MODEL_ORDER = ("EXAONE", "Solar", "HCX")
UPSTAGE_EXECUTION_MODEL = "solar-pro2"
QUALITATIVE_THEMES = (
    "affordability", "income-adequacy", "retirement-income-gap",
    "fiscal-sustainability", "investment-risk", "public-support",
    "intergenerational-fairness", "predictability",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def digest(value: Any) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_profiles(agents: list[dict]) -> list[dict]:
    ages = ("20대", "30대", "40대", "50대", "60대 이상")
    incomes = (("200만원 미만", 1_800_000), ("200~299만원", 2_500_000), ("300~399만원", 3_500_000), ("400~499만원", 4_500_000), ("500만원 이상", 6_000_000))
    by_label = {a["label"]: a for a in agents}
    ordered = [by_label[label] for label in MODEL_ORDER]
    profiles = []
    serial = 1
    for age_index, age in enumerate(ages):
        for income_index, (income_band, monthly_income) in enumerate(incomes):
            for repeat in range(10):
                agent = ordered[(serial - 1) % len(ordered)]
                profiles.append({
                    "participantId": f"SYN-KR-{serial:03d}",
                    "ageBand": age,
                    "incomeBand": income_band,
                    "monthlyIncome": monthly_income,
                    "contributionYears": min(40, 3 + age_index * 7 + repeat),
                    "preferredRetirementAge": 60 + ((age_index + income_index + repeat) % 8),
                    "assignedModel": {"label": agent["label"], "company": agent["company"], "provider": agent["provider"], "model": agent["model"]},
                })
                serial += 1
    if len(profiles) != 250:
        raise RuntimeError(f"정확히 250명이 아님: {len(profiles)}")
    return profiles


def personal_impacts(profile: dict) -> dict:
    years = min(max(profile["contributionYears"], 0), 40)
    monthly = 0 if years < 10 else round(profile["monthlyIncome"] * 0.43 * years / 40)
    annual_income = profile["monthlyIncome"] * 12
    rows = {}
    for option, start_age, support_per_person, reserve in (("A", 65, 294_000, 8.5), ("B", 68, 123_000, 9.5), ("C", 68, 0, 11.8)):
        rows[option] = {
            "monthlyPensionWon": monthly,
            "incomeGapYears": max(0, start_age - profile["preferredRetirementAge"]),
            "lifetimeBenefitWon": monthly * max(0, (85 - start_age) * 12),
            "annualBurdenRatePercent": round((annual_income * 0.04 + annual_income * 0.065 + support_per_person) / annual_income * 100, 1),
            "reserveMultiple": reserve,
        }
    return rows


class DomesticClient:
    def __init__(self, timeout_seconds: int = 60, attempts: int = 3):
        self.timeout_seconds = timeout_seconds
        self.attempts = attempts
        self._pace_lock = Lock()
        self._last_started: dict[str, float] = {}

    def pace(self, provider: str) -> None:
        minimum_interval = 7.0 if provider == "clova" else 0.0
        if not minimum_interval: return
        with self._pace_lock:
            elapsed = time.monotonic() - self._last_started.get(provider, 0.0)
            if elapsed < minimum_interval: time.sleep(minimum_interval - elapsed)
            self._last_started[provider] = time.monotonic()

    def _post(self, url: str, body: dict, headers: dict, timeout_seconds: int | None = None) -> tuple[dict, dict]:
        request = urllib.request.Request(url, json.dumps(body).encode(), headers)
        with urllib.request.urlopen(request, timeout=timeout_seconds or self.timeout_seconds) as response:
            return json.loads(response.read()), dict(response.headers.items())

    def call(self, agent: dict, phase: str, system: str, payload: dict, validate: Callable[[Any], None], temperature: float = 0.4) -> dict:
        spec = CFG.provider(agent["provider"])
        started_at = utc_now()
        started = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                self.pace(agent["provider"])
                retry_feedback = ""
                if last_error is not None:
                    retry_feedback = ("\n직전 응답은 서버 계약 검증에 실패했다. 오류: "
                                      f"{type(last_error).__name__}: {last_error}. "
                                      "필드명·허용값·배타 규칙을 다시 확인하고 완전히 수정된 JSON만 반환하라.")
                messages = [{"role": "system", "content": system + retry_feedback}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
                if spec["kind"] == "openai":
                    body = {"model": agent["model"], "messages": messages, "temperature": temperature}
                    if agent["provider"] == "upstage" and agent["model"] == "solar-pro4": body["max_completion_tokens"] = 1200
                    else: body["max_tokens"] = min(spec.get("max_tokens", 4000), 1200) if agent["provider"] == "upstage" else spec.get("max_tokens", 4000)
                    body.update(spec.get("extra") or {})
                    response, headers = self._post(spec["base"] + "/chat/completions", body, {"Content-Type": "application/json", "Authorization": f"Bearer {os.environ[spec['env']]}"})
                    message = response["choices"][0]["message"]
                    raw = (message.get("content") or message.get("reasoning_content") or "").strip()
                    usage = response.get("usage") or {}
                elif spec["kind"] == "clova":
                    body = {"messages": messages, "maxTokens": spec.get("max_tokens", 4000), "temperature": temperature, "topP": 0.8}
                    response, headers = self._post(spec["base"] + f"/v3/chat-completions/{agent['model']}", body, {"Authorization": f"Bearer {os.environ[spec['env']]}", "Content-Type": "application/json"})
                    raw = (response.get("result", {}).get("message", {}).get("content") or "").strip()
                    usage = response.get("result", {}).get("usage") or response.get("usage") or {}
                else:
                    raise RuntimeError(f"정식 실행에서 허용하지 않는 provider kind: {spec['kind']}")
                value = llm.extract_json(raw)
                validate(value)
                completed_at = utc_now()
                return {
                    "value": value,
                    "receipt": {
                        "phase": phase,
                        "provider": agent["provider"],
                        "company": agent["company"],
                        "label": agent["label"],
                        "model": agent["model"],
                        "promptVersion": PROMPT_VERSION,
                        "attempt": attempt,
                        "startedAt": started_at,
                        "completedAt": completed_at,
                        "durationMs": round((time.perf_counter() - started) * 1000),
                        "inputHash": digest(payload),
                        "outputHash": digest(value),
                        "requestId": headers.get("x-request-id") or headers.get("request-id") or headers.get("apigw-requestid") or response.get("id"),
                        "usage": usage,
                        "cost": {"value": None, "currency": "USD", "status": "not-returned-by-provider"},
                    },
                }
            except Exception as error:
                last_error = error
                if attempt < self.attempts:
                    time.sleep(max(attempt * 2, 10 if isinstance(error, urllib.error.HTTPError) and error.code == 429 else 0))
        raise RuntimeError(f"{agent['label']} {phase} 실패 폐쇄: {type(last_error).__name__}: {last_error}") from last_error


def chunks(values: list[dict], size: int = 1) -> list[list[dict]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def validate_ids(rows: Any, expected: list[dict]) -> None:
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError("배치 행 수 불일치")
    if len(rows) == 1 and len(expected) == 1:
        expected_id = expected[0]["participantId"]
        returned_id = rows[0].get("participantId")
        if returned_id != expected_id:
            rows[0]["providerParticipantId"] = returned_id
            rows[0]["participantId"] = expected_id
            rows[0]["participantIdBinding"] = "server-session"
        return
    if {row.get("participantId") for row in rows} != {row["participantId"] for row in expected}:
        raise ValueError("참가자 ID 불일치")


def response_rows(value: Any) -> Any:
    """국내 API가 단일 참가자에서 최상위 배열을 반환하는 표현 차이만 정규화한다."""
    if isinstance(value, dict) and "rows" in value: return value.get("rows")
    if isinstance(value, dict) and "participantId" in value: return [value]
    return value


def validate_m1(value: dict, expected: list[dict]) -> None:
    rows = response_rows(value)
    validate_ids(rows, expected)
    for row in rows:
        if row.get("m1") not in OPTIONS or len(str(row.get("m1Reason", "")).strip()) < 5:
            raise ValueError("M1 계약 위반")


def validate_m2(value: dict, expected: list[dict]) -> None:
    rows = response_rows(value)
    validate_ids(rows, expected)
    placeholder_reasons = {"10자 이상", "구체적인 이유 10자 이상", "이유 10자 이상"}
    for row in rows:
        if row.get("m2") not in OPTIONS or row.get("m2Acceptance") not in ACCEPTANCE:
            raise ValueError("M2 선택 계약 위반")
        selected_reason = str(row.get("selectedReason", "")).strip()
        if len(selected_reason) < 10 or selected_reason in placeholder_reasons:
            raise ValueError("M2 선택 사유 누락")
        reasons = row.get("notSelectedReasons") or {}
        if any(
            len(str(reasons.get(option, "")).strip()) < 10
            or str(reasons.get(option, "")).strip() in placeholder_reasons
            for option in OPTIONS if option != row["m2"]
        ):
            raise ValueError("M2 비선택안별 사유 누락")


def validate_m3(value: dict, expected: list[dict]) -> None:
    rows = response_rows(value)
    validate_ids(rows, expected)
    for row in rows:
        if row.get("m3") not in OPTIONS or row.get("dAcceptance") not in ACCEPTANCE:
            raise ValueError("M3/D 계약 위반")
        m3_reason = str(row.get("m3Reason", "")).strip()
        d_reason = str(row.get("dReason", "")).strip()
        placeholder_reasons = {"10자 이상", "구체적인 이유 10자 이상", "이유 10자 이상"}
        if (
            len(m3_reason) < 10
            or len(d_reason) < 10
            or m3_reason in placeholder_reasons
            or d_reason in placeholder_reasons
        ):
            raise ValueError("M3/D 사유 누락")


def validate_m3_v3(value: dict, expected: list[dict]) -> None:
    rows = response_rows(value)
    validate_ids(rows, expected)
    allowed = set(OPTIONS) | {"D_PRIME"}
    placeholder_reasons = {"10자 이상", "구체적인 이유 10자 이상", "이유 10자 이상"}
    for row in rows:
        choice = row.get("m3")
        assessments = row.get("optionAssessments") or {}
        if choice not in allowed or set(assessments) != allowed:
            raise ValueError("v3 M3 4지선다 계약 위반")
        normalizations = []
        for option, assessment in assessments.items():
            original_stance = assessment.get("stance") if isinstance(assessment, dict) else None
            if option != choice and original_stance in ("accept", "conditional_accept"):
                assessment["stance"] = "reject"
                normalizations.append({
                    "field": f"optionAssessments.{option}.stance",
                    "providerValue": original_stance,
                    "normalizedValue": "reject",
                    "rule": "single-choice-nonselected-option",
                })
        if normalizations:
            row["serverNormalizations"] = normalizations
        for option, assessment in assessments.items():
            if not isinstance(assessment, dict) or set(assessment) != {"stance", "reason"}:
                raise ValueError("v3 M3 안별 판단 계약 위반")
            stance = assessment.get("stance")
            reason = str(assessment.get("reason", "")).strip()
            if option == choice and stance not in ("accept", "conditional_accept"):
                raise ValueError("v3 M3 선택안 수용 계약 위반")
            if option != choice and stance != "reject":
                raise ValueError("v3 M3 비선택안 계약 위반")
            if len(reason) < 10 or reason in placeholder_reasons:
                raise ValueError("v3 M3 안별 사유 누락")


def validate_policy(value: dict) -> None:
    for key in ("title", "body", "tradeoffs"):
        if len(str(value.get(key, "")).strip()) < 5:
            raise ValueError(f"D {key} 누락")
    parameters = value.get("parameters") or {}
    if not (0 <= float(parameters.get("contributionRate", -1)) <= 18): raise ValueError("보험료율 범위 위반")
    if float(parameters.get("incomeReplacementRate", -1)) != 43: raise ValueError("소득대체율 고정값 위반")
    if not (5 <= float(parameters.get("returnRate", -1)) <= 7): raise ValueError("수익률 범위 위반")
    if not (65 <= float(parameters.get("retirementAge", -1)) <= 70): raise ValueError("수급연령 범위 위반")
    if not (0 <= float(parameters.get("annualGdpSupportRate", -1)) <= 1): raise ValueError("GDP 지원 범위 위반")


def validate_edits(value: Any) -> None:
    if not isinstance(value, list): raise ValueError("수정제안 배열 아님")


def validate_votes(value: Any) -> None:
    if not isinstance(value, dict): raise ValueError("투표 객체 아님")


def validate_classification(value: dict, expected: list[dict]) -> None:
    rows = response_rows(value)
    validate_ids(rows, expected)
    allowed = set(QUALITATIVE_THEMES)
    for row in rows:
        per_option = row.get("perOptionThemes") or {}
        if set(per_option) != set(OPTIONS):
            raise ValueError("정성 분류 선택지 범위 위반")
        if any(per_option[option] not in allowed for option in OPTIONS):
            raise ValueError("정성 분류 테마 위반")
        priorities = row.get("selectedPriorities")
        if not isinstance(priorities, list) or not (1 <= len(priorities) <= 3) or any(item not in allowed for item in priorities):
            raise ValueError("정성 분류 우선순위 위반")
        if len(str(row.get("vulnerableGroupImpact", "")).strip()) < 10:
            raise ValueError("취약집단 영향 누락")


def validate_classification_summary(value: dict) -> None:
    for key in ("dominantThemes", "conflicts", "vulnerableGroups", "minorityViews", "recommendations"):
        items = value.get(key)
        if not isinstance(items, list) or not items or any(len(str(item).strip()) < 5 for item in items):
            raise ValueError(f"정성 요약 {key} 누락")


def run_batched_phase(output: Path, phase: str, agents: list[dict], profiles: list[dict], client: DomesticClient, resume: bool, payload_for: Callable[[list[dict]], dict], system: str, validator: Callable[[dict, list[dict]], None], allow_domestic_fallback: bool = False) -> tuple[list[dict], list[dict], dict]:
    started_at = utc_now(); started = time.perf_counter()
    by_label = {agent["label"]: [] for agent in agents}
    for profile in profiles: by_label[profile["assignedModel"]["label"]].append(profile)

    batches_by_label = {agent["label"]: chunks(by_label[agent["label"]], 1) for agent in agents}
    provider_limits = {agent["provider"]: Semaphore(1 if agent["provider"] == "clova" else 2 if agent["provider"] == "upstage" else 3) for agent in agents}
    tasks = []
    for batch_index in range(max(len(values) for values in batches_by_label.values())):
        for agent in agents:
            values = batches_by_label[agent["label"]]
            if batch_index < len(values): tasks.append((agent, batch_index + 1, values[batch_index]))

    def run_one(task: tuple[dict, int, list[dict]]) -> dict:
        agent, batch_no, batch = task
        path = output / f"{phase}-{agent['label'].lower()}-{batch_no:03d}.json"
        if resume and path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            validator({"rows": saved["rows"]}, batch)
            return {"value": {"rows": saved["rows"]}, "receipt": saved["receipt"]}
        try:
            with provider_limits[agent["provider"]]:
                result = client.call(agent, f"{phase}-{agent['label']}-{batch_no}", system, payload_for(batch), lambda value: validator(value, batch))
        except RuntimeError as assigned_error:
            if not allow_domestic_fallback:
                raise
            result = None
            fallback_errors = []
            for fallback in agents:
                if fallback["label"] == agent["label"]:
                    continue
                try:
                    with provider_limits[fallback["provider"]]:
                        result = client.call(fallback, f"{phase}-{agent['label']}-{batch_no}-fallback-{fallback['label']}", system,
                                             payload_for(batch), lambda value: validator(value, batch))
                    result["receipt"]["fallback"] = {
                        "assignedLabel": agent["label"],
                        "executedLabel": fallback["label"],
                        "reason": str(assigned_error),
                    }
                    for row in response_rows(result["value"]):
                        row["fallbackExecution"] = {"assignedLabel": agent["label"], "executedLabel": fallback["label"]}
                    break
                except RuntimeError as fallback_error:
                    fallback_errors.append(str(fallback_error))
            if result is None:
                raise RuntimeError(f"{assigned_error}; 국내 대체 모델도 실패: {fallback_errors}") from assigned_error
        normalized_rows = response_rows(result["value"])
        if isinstance(normalized_rows, list): result["value"] = {"rows": normalized_rows}
        write_json(path, {"receipt": result["receipt"], "rows": result["value"]["rows"]})
        return result

    with ThreadPoolExecutor(max_workers=9) as pool:
        calls = list(pool.map(run_one, tasks))
    rows = [row for call in calls for row in call["value"]["rows"]]
    if len(rows) != 250: raise RuntimeError(f"{phase} 정확히 250명 아님")
    timing = {"phase": phase, "startedAt": started_at, "completedAt": utc_now(), "durationMs": round((time.perf_counter() - started) * 1000), "calls": len(calls), "resumed": resume}
    return rows, [call["receipt"] for call in calls], timing


def run_full_qualitative_classification(output: Path, agents: list[dict], profiles: list[dict], m2_rows: list[dict], client: DomesticClient, resume: bool) -> tuple[dict, list[dict], dict]:
    started_at = utc_now(); started = time.perf_counter(); receipts = []
    profile_by_id = {profile["participantId"]: profile for profile in profiles}
    opinions = []
    for row in m2_rows:
        per_option = {
            option: row["selectedReason"] if option == row["m2"] else row["notSelectedReasons"][option]
            for option in OPTIONS
        }
        opinions.append({"participantId": row["participantId"], "selected": row["m2"], "perOptionReasons": per_option})
    by_label = {agent["label"]: [] for agent in agents}
    for opinion in opinions:
        by_label[profile_by_id[opinion["participantId"]]["assignedModel"]["label"]].append(opinion)
    provider_limits = {agent["provider"]: Semaphore(1 if agent["provider"] == "clova" else 2 if agent["provider"] == "upstage" else 3) for agent in agents}
    taxonomy = list(QUALITATIVE_THEMES)
    system = ('시민의 A/B/C 선택 사유를 정해진 정책 테마로 분류한다. 입력 ID를 빠짐없이 한 번씩 유지하고 JSON 객체만 반환한다. '
              '{"rows":[{"participantId":"원문 ID","perOptionThemes":{"A":"theme","B":"theme","C":"theme"},"selectedPriorities":["theme"],"vulnerableGroupImpact":"구체적 한국어 문장"}]} 형식이다. '
              'theme은 제공된 taxonomy 중 하나만 사용한다. selectedPriorities는 1~3개이며 취약집단 영향은 10자 이상의 실제 문장이어야 한다.')
    tasks = []
    for agent in agents:
        batch_size = 1 if agent["provider"] == "upstage" else 12
        for batch_no, batch in enumerate(chunks(by_label[agent["label"]], batch_size), 1):
            tasks.append((agent, batch_no, batch))

    def classify_one(task: tuple[dict, int, list[dict]]) -> tuple[str, dict]:
        agent, batch_no, batch = task
        path = output / f"qclass-{agent['label'].lower()}-{batch_no:03d}.json"
        if resume and path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            validate_classification({"rows": saved["rows"]}, batch)
            return agent["label"], saved
        with provider_limits[agent["provider"]]:
            call = client.call(agent, f"QCLASS-{agent['label']}-{batch_no}", system,
                               {"taxonomy": taxonomy, "opinions": batch},
                               lambda value: validate_classification(value, batch), 0.2)
        normalized = response_rows(call["value"])
        write_json(path, {"receipt": call["receipt"], "rows": normalized})
        return agent["label"], {"receipt": call["receipt"], "rows": normalized}

    with ThreadPoolExecutor(max_workers=9) as pool:
        classified_calls = list(pool.map(classify_one, tasks))
    classified = []
    by_label_classified = {agent["label"]: [] for agent in agents}
    for label, call in classified_calls:
        receipts.append(call["receipt"]); classified.extend(call["rows"]); by_label_classified[label].extend(call["rows"])
    expected_ids = sorted(opinion["participantId"] for opinion in opinions)
    actual_ids = sorted(row["participantId"] for row in classified)
    if actual_ids != expected_ids or len(actual_ids) != 250:
        raise RuntimeError("250명 정성 분류 커버리지 위반")

    summary_system = ('자신에게 배정된 시민 의견과 분류를 빠짐없이 요약한다. JSON 객체 dominantThemes,conflicts,vulnerableGroups,minorityViews,recommendations만 반환하고 각 값은 비어 있지 않은 한국어 문자열 배열이다. 다수 의견과 소수 의견을 구분하고 정책 상충관계를 숨기지 않는다.')
    opinion_by_id = {opinion["participantId"]: opinion for opinion in opinions}
    def summarize_one(agent: dict) -> tuple[str, dict]:
        label = agent["label"]
        rows = by_label_classified[label]
        assigned_opinions = [opinion_by_id[row["participantId"]] for row in rows]
        call = client.call(agent, f"QSUMMARY-{label}", summary_system,
                           {"participantCount": len(rows), "opinions": assigned_opinions, "classifications": rows},
                           validate_classification_summary, 0.2)
        return label, call
    with ThreadPoolExecutor(max_workers=3) as pool:
        summary_calls = list(pool.map(summarize_one, agents))
    summaries = {}
    for label, call in summary_calls:
        summaries[label] = call["value"]; receipts.append(call["receipt"])

    theme_counts = {theme: 0 for theme in QUALITATIVE_THEMES}
    for row in classified:
        for theme in set(row["selectedPriorities"]): theme_counts[theme] += 1
    coverage = {
        "participantCount": 250,
        "reasonTextCount": 750,
        "participantIdsSha256": digest(expected_ids),
        "opinionInputSha256": digest(opinions),
        "modelAssignment": {agent["label"]: len(by_label[agent["label"]]) for agent in agents},
    }
    artifact = {"protocol": "domestic-full-250-qualitative-classification-v1", "coverage": coverage,
                "taxonomy": taxonomy, "themeCounts": theme_counts, "rows": classified,
                "providerSummaries": summaries, "receipts": receipts}
    write_json(output / "qualitative-classification.json", artifact)
    timing = {"phase": "full-qualitative-classification", "startedAt": started_at, "completedAt": utc_now(),
              "durationMs": round((time.perf_counter() - started) * 1000), "calls": len(receipts)}
    return artifact, receipts, timing


def run_domestic_deliberation(output: Path, agents: list[dict], m2_rows: list[dict], client: DomesticClient, qualitative: dict | None = None) -> tuple[dict, list[dict], dict, dict]:
    started_at = utc_now(); started = time.perf_counter(); receipts = []; transcript = {"protocol": "domestic-three-company-six-stage-v2", "stages": []}
    counts = {option: sum(row["m2"] == option for row in m2_rows) for option in OPTIONS}
    reason_sample = [{"selected": row["m2"], "selectedReason": row["selectedReason"], "notSelectedReasons": row["notSelectedReasons"]} for index, row in enumerate(m2_rows) if index % 4 == 0]
    evidence = ({"qualitativeCoverage": qualitative["coverage"], "qualitativeThemeCounts": qualitative["themeCounts"],
                 "qualitativeProviderSummaries": qualitative["providerSummaries"]} if qualitative else {"reasonSample": reason_sample})
    base = {"policies": POLICIES, "m2Counts": counts, "participantCount": 250, **evidence,
            "requiredParameters": {"contributionRateMax": 18, "incomeReplacementRateFixed": 43, "returnRateRange": [5, 7], "retirementAgeRange": [65, 70], "annualGdpSupportRateMax": 1}}
    policy_system = ("너는 한국 연금개혁 정책실험의 국내 독립 정책초안가다. 시민 의견의 반영·미반영·상충관계와 취약집단 영향을 정직하게 밝힌다. "
                     "JSON 객체 title,body,reflects,tradeoffs,unaddressed,parameters만 반환한다. parameters는 contributionRate,incomeReplacementRate,returnRate,retirementAge,annualGdpSupportRate 숫자다. "
                     "정책팀 동결 계약: incomeReplacementRate는 반드시 숫자 43이어야 하며 0.43, 5.5 또는 다른 값은 금지한다. contributionRate는 0~18, returnRate는 5~7, retirementAge는 65~70, annualGdpSupportRate는 0~1 범위다. 이 범위를 바꾸고 싶으면 parameters를 바꾸지 말고 tradeoffs 또는 unaddressed에 남겨라.")

    def parallel_policy(stage: str, payloads: dict[str, dict]) -> dict:
        def one(agent: dict):
            result = client.call(agent, f"D-{stage}-{agent['label']}", policy_system, payloads[agent["label"]], validate_policy)
            return agent["label"], result
        with ThreadPoolExecutor(max_workers=3) as pool: results = list(pool.map(one, agents))
        values = {}
        for label, result in results: values[label] = result["value"]; receipts.append(result["receipt"])
        return values

    drafts = parallel_policy("1-independent", {a["label"]: {**base, "instruction": f"{a['label']}({a['company']})의 독립 D 초안을 작성하라."} for a in agents})
    transcript["stages"].append({"stage": 1, "name": "독립안", "by": drafts})
    revised = parallel_policy("2-cross-revision", {a["label"]: {**base, "ownDraft": drafts[a["label"]], "otherDrafts": {k:v for k,v in drafts.items() if k != a["label"]}, "instruction": "다른 두 안의 강점과 드리프트를 검토해 자기 수정안을 작성하라."} for a in agents})
    transcript["stages"].append({"stage": 2, "name": "교차보강", "by": revised})
    synthesizer = agents[0]
    merged_call = client.call(synthesizer, "D-3-synthesis", policy_system, {**base, "revisedDrafts": revised, "instruction": "세 수정안을 취합하되 누락·미반영·상충관계를 남긴 단일 D안을 작성하라."}, validate_policy)
    receipts.append(merged_call["receipt"]); merged = merged_call["value"]
    transcript["stages"].append({"stage": 3, "name": "취합", "synthesizer": synthesizer["label"], "result": merged})

    edit_system = '통합 D안의 드리프트·누락·취약집단 문제를 검토한다. JSON 배열만 반환한다: [{"what":"수정내용","why":"이유"}]'
    def edit_one(agent: dict): return agent, client.call(agent, f"D-4-edits-{agent['label']}", edit_system, {"merged": merged, "m2Counts": counts, **evidence}, validate_edits)
    with ThreadPoolExecutor(max_workers=3) as pool: edit_calls = list(pool.map(edit_one, agents))
    edits = []
    for agent, call in edit_calls:
        receipts.append(call["receipt"])
        for item in call["value"]: edits.append({"id": f"E{len(edits)+1}", "by": agent["label"], "what": str(item.get("what", "")), "why": str(item.get("why", ""))})
    transcript["stages"].append({"stage": 4, "name": "수정요청", "edits": edits})

    vote_system = '각 수정제안을 반영할지 독립적으로 판단한다. 모든 ID를 포함한 JSON 객체만 반환한다: {"E1":"accept","E2":"reject"}'
    def vote_one(agent: dict): return agent, client.call(agent, f"D-5-vote-{agent['label']}", vote_system, {"merged": merged, "edits": edits}, validate_votes, 0.2)
    with ThreadPoolExecutor(max_workers=3) as pool: vote_calls = list(pool.map(vote_one, agents))
    tally = {edit["id"]: 0 for edit in edits}; ballots = {}
    for agent, call in vote_calls:
        receipts.append(call["receipt"]); ballots[agent["label"]] = call["value"]
        for edit_id in tally:
            if str(call["value"].get(edit_id, "")).lower() == "accept": tally[edit_id] += 1
    accepted = [{**edit, "acceptVotes": tally[edit["id"]]} for edit in edits if tally[edit["id"]] >= 2]
    transcript["stages"].append({"stage": 5, "name": "2/3 투표", "ballots": ballots, "accepted": accepted})

    final_call = client.call(synthesizer, "D-6-final", policy_system, {**base, "merged": merged, "acceptedEdits": accepted, "instruction": "2/3 이상 찬성한 수정만 반영해 최종 D안을 작성하라."}, validate_policy)
    receipts.append(final_call["receipt"]); final = final_call["value"]
    transcript["stages"].append({"stage": 6, "name": "최종반영", "synthesizer": synthesizer["label"], "result": final})
    expert_gate = {"status": "simulation_contract_pass", "humanApproval": False, "note": "정책범위 자동검증만 통과. 실제 행사에서는 사람 전문가 승인·논평이 별도로 필요함.", "facilitatedQA": [
        "보험료 부담과 노후소득 보장 사이의 상충관계는 무엇인가?", "수급연령 조정 시 노동 취약계층의 소득공백을 어떻게 보완하는가?", "기금운용 수익률 가정이 빗나갈 경우 어떤 재검토 장치가 필요한가?"
    ]}
    write_json(output / "domestic-deliberation.json", {"provenance": [{k:a[k] for k in ("label","company","provider","model")} for a in agents], "inputEvidence": {"mode": "full-250-qualitative" if qualitative else "63-participant-sample", **({"coverage": qualitative["coverage"]} if qualitative else {"sampleParticipants": len(reason_sample)})}, "receipts": receipts, "transcript": transcript, "finalD": final, "expertGate": expert_gate})
    timing = {"phase": "domestic-d-deliberation", "startedAt": started_at, "completedAt": utc_now(), "durationMs": round((time.perf_counter() - started) * 1000), "calls": len(receipts)}
    return final, receipts, timing, expert_gate


def run_d_prime_revision(output: Path, agents: list[dict], final_d: dict, client: DomesticClient) -> tuple[dict, list[dict], dict, dict]:
    """합성 전문가 논평과 공개 질의 입력을 반영해 D와 구분되는 D′를 만든다."""
    started_at = utc_now(); started = time.perf_counter(); receipts = []
    expert_commentary = [
        {"role": "pension-actuary-fixture", "comment": "수익률 가정이 빗나갈 때 자동 재검토하는 주기와 재정 안전장치를 정책 본문에 명시해야 한다."},
        {"role": "labor-market-fixture", "comment": "수급연령 상향에 앞서 조기 퇴직자와 육체노동자의 소득공백 보완책을 구체화해야 한다."},
        {"role": "distribution-fixture", "comment": "저소득·불안정 고용층의 보험료 부담과 최소 노후소득 보장을 함께 점검해야 한다."},
    ]
    audience_inputs = [
        {"id": "PUBLIC-Q1", "question": "보험료 부담이 늘 때 저소득 가입자에게 어떤 완충장치가 적용되는가?"},
        {"id": "PUBLIC-Q2", "question": "68세 이전에 일을 그만두는 시민의 소득공백을 어떻게 줄이는가?"},
        {"id": "PUBLIC-Q3", "question": "목표 수익률을 달성하지 못하면 언제 누가 정책을 다시 검토하는가?"},
    ]
    gate = {
        "humanApproval": False,
        "expertCommentaryMode": "synthetic-fixed-fixture",
        "audienceSelectionMode": "synthetic-facilitator-selected-fixture",
        "note": "가상시민 검증용 고정 입력이며 실제 전문가 승인이나 현장 공개 질의를 대체하지 않는다.",
    }
    base = {
        "dPolicy": final_d,
        "expertCommentary": expert_commentary,
        "facilitatorSelectedAudienceInputs": audience_inputs,
        "requiredParameters": {"contributionRateMax": 18, "incomeReplacementRateFixed": 43, "returnRateRange": [5, 7], "retirementAgeRange": [65, 70], "annualGdpSupportRateMax": 1},
    }
    system = ("너는 한국 연금개혁 D안을 전문가 논평과 진행자가 선별한 공개 질의로 보강해 D프라임 수정안을 작성한다. "
              "원 D의 핵심을 숨기지 말고 반영·미반영·상충관계를 밝힌다. JSON 객체 title,body,reflects,tradeoffs,unaddressed,parameters만 반환한다. "
              "parameters의 incomeReplacementRate는 정확히 43, contributionRate는 0~18, returnRate는 5~7, retirementAge는 65~70, annualGdpSupportRate는 0~1 범위다.")

    def revise_one(agent: dict) -> tuple[str, dict]:
        call = client.call(agent, f"DPRIME-1-revision-{agent['label']}", system,
                           {**base, "instruction": f"{agent['label']}의 독립 D프라임 수정안을 작성하라."}, validate_policy, 0.2)
        return agent["label"], call

    with ThreadPoolExecutor(max_workers=3) as pool:
        revisions = list(pool.map(revise_one, agents))
    candidates = {}
    for label, call in revisions:
        candidates[label] = call["value"]; receipts.append(call["receipt"])
    synthesizer = agents[0]
    final_call = client.call(synthesizer, "DPRIME-2-synthesis", system,
                             {**base, "candidateRevisions": candidates,
                              "instruction": "세 독립 수정안의 공통점과 충돌을 검토해 최종 D프라임 하나를 작성하라."},
                             validate_policy, 0.2)
    receipts.append(final_call["receipt"]); final_d_prime = final_call["value"]
    artifact = {
        "protocol": "pension-event-v3-d-prime-v1",
        "dArtifactHash": digest(final_d),
        "expertCommentary": expert_commentary,
        "expertCommentaryHash": digest(expert_commentary),
        "facilitatorSelectedAudienceInputs": audience_inputs,
        "audienceInputHash": digest(audience_inputs),
        "gate": gate,
        "provenance": [{k:a[k] for k in ("label","company","provider","model")} for a in agents],
        "candidateRevisions": candidates,
        "receipts": receipts,
        "finalDPrime": final_d_prime,
    }
    write_json(output / "d-prime.json", artifact)
    timing = {"phase": "d-prime-revision", "startedAt": started_at, "completedAt": utc_now(),
              "durationMs": round((time.perf_counter() - started) * 1000), "calls": len(receipts)}
    return final_d_prime, receipts, timing, artifact


def count(rows: list[dict], key: str, values: tuple[str, ...]) -> dict:
    return {value: sum(row[key] == value for row in rows) for value in values}


def transitions(rows: list[dict], left: str, right: str) -> dict:
    result = {}
    for row in rows: result[f"{row[left]}→{row[right]}"] = result.get(f"{row[left]}→{row[right]}", 0) + 1
    return dict(sorted(result.items()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--full-qualitative", action="store_true")
    parser.add_argument("--event-v3", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", default="pension-official-domestic-250-20260806")
    args = parser.parse_args()
    if not args.execute: raise SystemExit("실제 호출은 --execute가 필요합니다")
    agents = CFG.active_dokpamo()
    agents = [{**agent, "model": UPSTAGE_EXECUTION_MODEL if agent["provider"] == "upstage" else agent["model"]} for agent in agents]
    companies = {agent["company"] for agent in agents}
    if companies != {"LG", "Upstage", "Naver"} or len(agents) != 3:
        raise SystemExit(f"국내 3사 정확히 활성화되지 않아 실패 폐쇄: {sorted(companies)}")
    output = Path(args.output).resolve()
    if output.exists() and not args.resume: raise SystemExit(f"출력 디렉터리가 이미 존재함: {output}")
    output.mkdir(parents=True, exist_ok=args.resume)
    run_started_at = utc_now(); run_started = time.perf_counter(); phases=[]; receipts=[]
    client = DomesticClient()
    profiles = create_profiles(agents)
    by_id = {profile["participantId"]: profile for profile in profiles}
    model_counts = {agent["label"]: sum(p["assignedModel"]["label"] == agent["label"] for p in profiles) for agent in agents}
    write_json(output / "profiles.json", {"synthetic": True, "participants": profiles, "modelCounts": model_counts})

    m1, phase_receipts, timing = run_batched_phase(output, "m1", agents, profiles, client, args.resume,
        lambda batch: {"stage": "전문가 A/B/C 설명 직후, 개인영향을 보기 전 M1", "policies": POLICIES, "profiles": [{k:p[k] for k in ("participantId","ageBand","incomeBand","contributionYears","preferredRetirementAge")} for p in batch]},
        '각 프로필의 처지에서 A/B/C 중 하나를 최초 선택한다. 아직 개인영향 계산이나 다른 참가자 의견은 보지 못했다. 반드시 JSON 객체 {"rows":[{"participantId":"원문 ID","m1":"A 또는 B 또는 C","m1Reason":"해당 시민 관점의 구체적인 한국어 선택 이유 10자 이상"}]}만 반환한다. participantId,m1,m1Reason 세 필드는 모두 필수이며 생략하거나 빈 문자열로 두면 안 된다.', validate_m1)
    receipts += phase_receipts; phases.append(timing); m1_by_id={r["participantId"]:r for r in m1}

    m2, phase_receipts, timing = run_batched_phase(output, "m2", agents, profiles, client, args.resume,
        lambda batch: {"stage": "결정론 개인영향 확인 후 M2", "policies": POLICIES, "profiles": [{**{k:p[k] for k in ("participantId","ageBand","incomeBand","contributionYears","preferredRetirementAge")}, "m1":m1_by_id[p["participantId"]], "personalImpacts":personal_impacts(p)} for p in batch]},
        '같은 프로필의 M1을 기억하고 개인영향 계산을 확인한 뒤 A/B/C 중 M2를 선택한다. 반드시 JSON 객체 {"rows":[{"participantId":"원문 ID","m2":"A","m2Acceptance":"accept","selectedReason":"이 시민의 처지와 선택을 연결한 구체적 한국어 문장","notSelectedReasons":{"A":"A에 대한 구체적 판단","B":"B에 대한 구체적 판단","C":"C에 대한 구체적 판단"}}]}만 반환한다. m2는 문자열 A, B, C 중 정확히 한 글자이고, m2Acceptance는 accept, conditional_accept, reject 중 정확히 하나다. 선택 사유와 두 비선택안 사유는 각각 10자 이상의 실제 이유여야 하며 예시 문구, 글자 수 지시문, 빈 문자열을 그대로 복사하면 안 된다.', validate_m2)
    receipts += phase_receipts; phases.append(timing); m2_by_id={r["participantId"]:r for r in m2}

    qualitative = None
    if args.full_qualitative:
        qualitative_path = output / "qualitative-classification.json"
        if args.resume and qualitative_path.exists():
            qualitative = json.loads(qualitative_path.read_text(encoding="utf-8"))
            phase_receipts = qualitative["receipts"]
            q_started = min(receipt["startedAt"] for receipt in phase_receipts)
            q_completed = max(receipt["completedAt"] for receipt in phase_receipts)
            q_duration = datetime.fromisoformat(q_completed.replace("Z", "+00:00")) - datetime.fromisoformat(q_started.replace("Z", "+00:00"))
            timing = {"phase": "full-qualitative-classification", "startedAt": q_started, "completedAt": q_completed,
                      "durationMs": round(q_duration.total_seconds() * 1000), "calls": len(phase_receipts), "resumed": True}
        else:
            qualitative, phase_receipts, timing = run_full_qualitative_classification(output, agents, profiles, m2, client, args.resume)
        if qualitative["coverage"]["participantCount"] != 250 or qualitative["coverage"]["reasonTextCount"] != 750:
            raise RuntimeError("전체 정성 입력 커버리지 계약 위반")
        receipts += phase_receipts; phases.append(timing)

    deliberation_path = output / "domestic-deliberation.json"
    if args.resume and deliberation_path.exists():
        saved_deliberation = json.loads(deliberation_path.read_text(encoding="utf-8"))
        final_d = saved_deliberation["finalD"]
        phase_receipts = saved_deliberation["receipts"]
        expert_gate = saved_deliberation["expertGate"]
        d_started = min(receipt["startedAt"] for receipt in phase_receipts)
        d_completed = max(receipt["completedAt"] for receipt in phase_receipts)
        d_duration = datetime.fromisoformat(d_completed.replace("Z", "+00:00")) - datetime.fromisoformat(d_started.replace("Z", "+00:00"))
        timing = {"phase": "domestic-d-deliberation", "startedAt": d_started, "completedAt": d_completed, "durationMs": round(d_duration.total_seconds() * 1000), "calls": len(phase_receipts), "resumed": True}
    else:
        final_d, phase_receipts, timing, expert_gate = run_domestic_deliberation(output, agents, m2, client, qualitative)
    receipts += phase_receipts; phases.append(timing)

    d_prime_artifact = None
    final_choice_policy = final_d
    if args.event_v3:
        d_prime_path = output / "d-prime.json"
        if args.resume and d_prime_path.exists():
            d_prime_artifact = json.loads(d_prime_path.read_text(encoding="utf-8"))
            final_choice_policy = d_prime_artifact["finalDPrime"]
            phase_receipts = d_prime_artifact["receipts"]
            dp_started = min(receipt["startedAt"] for receipt in phase_receipts)
            dp_completed = max(receipt["completedAt"] for receipt in phase_receipts)
            dp_duration = datetime.fromisoformat(dp_completed.replace("Z", "+00:00")) - datetime.fromisoformat(dp_started.replace("Z", "+00:00"))
            timing = {"phase": "d-prime-revision", "startedAt": dp_started, "completedAt": dp_completed,
                      "durationMs": round(dp_duration.total_seconds() * 1000), "calls": len(phase_receipts), "resumed": True}
        else:
            final_choice_policy, phase_receipts, timing, d_prime_artifact = run_d_prime_revision(output, agents, final_d, client)
        receipts += phase_receipts; phases.append(timing)

    if args.event_v3:
        def m3_payload(batch: list[dict]) -> dict:
            profile = batch[0]
            option_ids = ["A", "B", "C", "D_PRIME"]
            offset = int(profile["participantId"].rsplit("-", 1)[1]) % len(option_ids)
            option_ids = option_ids[offset:] + option_ids[:offset]
            policy_values = {**POLICIES, "D_PRIME": final_choice_policy}
            return {"stage": "D 이후 합성 전문가 논평·진행자 선별 공개질의·D프라임 뒤 M3 4지선다",
                    "choiceOrder": option_ids,
                    "policies": [{"id": option, "policy": policy_values[option]} for option in option_ids],
                    "dPolicy": final_d, "dPrimePolicy": final_choice_policy,
                    "reviewInputs": {"expertCommentary": d_prime_artifact["expertCommentary"], "facilitatorSelectedAudienceInputs": d_prime_artifact["facilitatorSelectedAudienceInputs"], "humanApproval": False},
                    "profiles": [{**{k:p[k] for k in ("participantId","ageBand","incomeBand","contributionYears","preferredRetirementAge")}, "m1":m1_by_id[p["participantId"]], "m2":m2_by_id[p["participantId"]]} for p in batch]}
        m3_system = ('같은 프로필과 앞선 판단을 유지하고 A/B/C/D_PRIME 중 정확히 하나를 최종 선택한다. choiceOrder는 표시 순서일 뿐 우선순위나 추천이 아니다. '
                     'D_PRIME도 새 안이라는 이유로 우대하지 말고 시민 처지와 정책 내용만으로 네 안을 독립 비교한다. JSON 객체 하나만 반환하며 최상위 키는 rows다. '
                     'rows의 각 항목에는 participantId, m3, optionAssessments만 둔다. m3 허용값은 A, B, C, D_PRIME 중 하나다. '
                     'optionAssessments는 A, B, C, D_PRIME 네 키를 모두 가지며 각 값은 stance와 reason만 가진 객체다. '
                     '핵심 배타 규칙: m3와 같은 한 안의 stance만 accept 또는 conditional_accept이고, m3와 다른 나머지 세 안의 stance 문자열은 장점이나 조건부 호감이 있어도 예외 없이 정확히 reject다. '
                     '비선택안의 장단점과 조건은 reason에 설명하되 stance에는 conditional_accept를 쓰지 않는다. 네 이유 모두 각 10자 이상의 실제 한국어 문장이어야 한다. '
                     '설명용 예시 선택값은 제공되지 않았으며 특정 안을 기본값으로 삼아서는 안 된다.')
        m3_validator = validate_m3_v3
    else:
        m3_payload = lambda batch: {"stage": "D 제시·전문가 게이트 모사·진행자 선별 Q&A 뒤 M3", "policies": POLICIES, "dPolicy": final_d, "expertGate": expert_gate, "profiles": [{**{k:p[k] for k in ("participantId","ageBand","incomeBand","contributionYears","preferredRetirementAge")}, "m1":m1_by_id[p["participantId"]], "m2":m2_by_id[p["participantId"]]} for p in batch]}
        m3_system = '같은 프로필과 앞선 판단을 유지한다. D 설명 단계에는 투표하지 않았다. 최종으로 A/B/C 중 하나만 m3로 선택하고 D는 dAcceptance로 별도 판단한다. 반드시 JSON 객체 {"rows":[{"participantId":"원문 ID","m3":"A","m3Reason":"이 시민의 처지와 선택을 연결한 구체적 한국어 문장","dAcceptance":"accept","dReason":"이 시민의 처지와 D 평가를 연결한 구체적 한국어 문장"}]}만 반환한다. m3는 문자열 A, B, C 중 정확히 한 글자이고 dAcceptance는 accept, conditional_accept, reject 중 정확히 하나다. m3Reason과 dReason은 각각 10자 이상의 실제 이유여야 하며 예시 문구, 글자 수 지시문, 빈 문자열을 그대로 복사하면 안 된다.'
        m3_validator = validate_m3
    m3, phase_receipts, timing = run_batched_phase(output, "m3", agents, profiles, client, args.resume,
        m3_payload, m3_system, m3_validator, allow_domestic_fallback=args.event_v3)
    receipts += phase_receipts; phases.append(timing); m3_by_id={r["participantId"]:r for r in m3}

    rows=[]
    for pid, profile in by_id.items(): rows.append({**profile, **m1_by_id[pid], **m2_by_id[pid], **m3_by_id[pid]})
    for row in rows:
        if row["assignedModel"]["label"] not in MODEL_ORDER: raise RuntimeError("국내 모델 계보 위반")
        if row["m3"] not in (OPTIONS + (("D_PRIME",) if args.event_v3 else ())): raise RuntimeError("M3 선택지 계약 위반")
    m3_options = OPTIONS + (("D_PRIME",) if args.event_v3 else ())
    public = {
        "schemaVersion": 5 if args.event_v3 else 4, "runId": args.run_id, "synthetic": True, "representativeSample": False, "participants": 250,
        "procedure": ["M1", "deterministic-personal-impact", "M2-and-per-option-reasons"] + (["full-250-qualitative-classification"] if qualitative else []) + (["domestic-three-company-D-deliberation", "synthetic-expert-commentary", "synthetic-facilitator-selected-public-input", "domestic-three-company-D-prime-revision", "M3-ABCD-prime-four-option-assessment"] if args.event_v3 else ["domestic-three-company-D-deliberation", "no-vote-D-presentation-and-facilitated-QA", "M3-ABC-and-separate-D-assessment"]),
        "modelAssignment": model_counts,
        "choices": {"M1":count(rows,"m1",OPTIONS), "M2":count(rows,"m2",OPTIONS), "M3":count(rows,"m3",m3_options)},
        "transitions": {"M1toM2":transitions(rows,"m1","m2"), "M2toM3":transitions(rows,"m2","m3"), "M1toM3":transitions(rows,"m1","m3")},
        "dPolicy": final_d,
        "provenance": [{k:a[k] for k in ("label","company","provider","model")} for a in agents],
        "receiptSummary": {"calls":len(receipts), "providerReportedCost":None, "costStatus":"not-returned-by-providers"},
        "qualitativeCoverage": qualitative["coverage"] if qualitative else {"participantCount": 63, "mode": "sample"},
        "limitations": ["가상시민 합성실험이며 실제 여론·대표표본·인과효과가 아니다.", "사람 전문가 승인과 현장 질의는 계약 고정 fixture로 모사했으며 실제 승인을 대체하지 않는다.", "개별 합성 응답은 공개 결과에 포함하지 않는다."],
    }
    if args.event_v3:
        public["dPrimePolicy"] = final_choice_policy
        public["dPrimeInputHashes"] = {"d": d_prime_artifact["dArtifactHash"], "expertCommentary": d_prime_artifact["expertCommentaryHash"], "audienceInput": d_prime_artifact["audienceInputHash"]}
    else:
        public["dAssessment"] = count(rows,"dAcceptance",ACCEPTANCE)
    for key in ("M1","M2","M3"):
        if sum(public["choices"][key].values()) != 250: raise RuntimeError(f"{key} 합계 위반")
    if not args.event_v3 and sum(public["dAssessment"].values()) != 250: raise RuntimeError("D 합계 위반")
    aggregate_started=utc_now(); aggregate_tick=time.perf_counter()
    write_json(output / "private-responses.json", {"runId":args.run_id,"synthetic":True,"rows":rows})
    write_json(output / "public-result.json", public)
    phases.append({"phase":"aggregate-and-validate","startedAt":aggregate_started,"completedAt":utc_now(),"durationMs":round((time.perf_counter()-aggregate_tick)*1000),"calls":0})
    manifest={"runId":args.run_id,"startedAt":run_started_at,"completedAt":utc_now(),"durationMs":round((time.perf_counter()-run_started)*1000),"targetParticipants":250,"modelAssignment":model_counts,"phases":phases,"receipts":receipts,"artifactHashes":{"publicResult":digest(public),"privateResponses":digest(rows)}}
    write_json(output / "run-manifest.json", manifest)
    print(json.dumps({"runId":args.run_id,"participants":250,"models":model_counts,"calls":len(receipts),"durationMs":manifest["durationMs"],"output":str(output)},ensure_ascii=False),flush=True)


if __name__ == "__main__": main()
