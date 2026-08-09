"""Read-only process review backed by a physically isolated synthetic event.

The review endpoint never queries or writes the participant ledger.  Its event,
approved inputs and ten process steps live as append-only rows in a separate
SQLite database and are verified again when read.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timezone
from pathlib import Path


REVIEW_ID = "pension-v4-20260808-r1"
FIXTURE_VERSION = "pension-v4-review-fixture-v1"
SESSION_TOKEN_PREFIX = "aipr1."
_SESSION_PAYLOAD_KEYS = frozenset({
    "v", "review_id", "experiment_id", "participant_token", "iat", "exp",
})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS aipol_process_review_events (
  id TEXT PRIMARY KEY,
  contract_version TEXT NOT NULL,
  cohort_type TEXT NOT NULL CHECK(cohort_type='synthetic_review'),
  participant_count INTEGER NOT NULL CHECK(participant_count > 0),
  notice TEXT NOT NULL,
  forbidden_stages_json TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aipol_process_review_inputs (
  review_id TEXT NOT NULL REFERENCES aipol_process_review_events(id),
  input_key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  PRIMARY KEY(review_id,input_key)
);
CREATE TABLE IF NOT EXISTS aipol_process_review_steps (
  review_id TEXT NOT NULL REFERENCES aipol_process_review_events(id),
  step_number INTEGER NOT NULL CHECK(step_number BETWEEN 1 AND 10),
  payload_json TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  PRIMARY KEY(review_id,step_number)
);
CREATE TABLE IF NOT EXISTS aipol_process_review_bindings (
  review_id TEXT PRIMARY KEY REFERENCES aipol_process_review_events(id),
  fixture_version TEXT NOT NULL,
  fixture_hash TEXT NOT NULL CHECK(length(fixture_hash)=64),
  experiment_id TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS aipol_process_review_events_no_update
BEFORE UPDATE ON aipol_process_review_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_process_review_events_no_delete
BEFORE DELETE ON aipol_process_review_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_process_review_inputs_no_update
BEFORE UPDATE ON aipol_process_review_inputs BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_process_review_inputs_no_delete
BEFORE DELETE ON aipol_process_review_inputs BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_process_review_steps_no_update
BEFORE UPDATE ON aipol_process_review_steps BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_process_review_steps_no_delete
BEFORE DELETE ON aipol_process_review_steps BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_process_review_bindings_no_update
BEFORE UPDATE ON aipol_process_review_bindings BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_process_review_bindings_no_delete
BEFORE DELETE ON aipol_process_review_bindings BEGIN SELECT RAISE(ABORT, 'append-only'); END;
"""


def enabled() -> bool:
    return os.environ.get("AIPOL_PROCESS_REVIEW_ENABLED", "false").lower() == "true"


def database_path() -> Path:
    configured = os.environ.get("AIPOL_PROCESS_REVIEW_DB_PATH", "").strip()
    if configured:
        return Path(configured)
    event_path = Path(os.environ.get("EVENT_DB_PATH", "event.db"))
    return event_path.with_name("aipol-process-review.db")


class ReviewSessionError(ValueError):
    """The review-session capability is missing, invalid, or expired."""


def _session_secret() -> bytes:
    value = os.environ.get("AIPOL_PROCESS_REVIEW_SESSION_SECRET", "")
    if len(value.encode("utf-8")) < 32:
        raise ReviewSessionError("process review session secret is not configured")
    return value.encode("utf-8")


def _session_ttl_limit() -> int:
    try:
        value = int(os.environ.get("AIPOL_PROCESS_REVIEW_SESSION_MAX_TTL_SECONDS", "3600"))
    except ValueError as exc:
        raise ReviewSessionError("process review session TTL is invalid") from exc
    if value < 60 or value > 86_400:
        raise ReviewSessionError("process review session TTL is outside the allowed range")
    return value


def _b64encode(value: bytes) -> str:
    return urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    try:
        padding = "=" * (-len(value) % 4)
        return urlsafe_b64decode((value + padding).encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ReviewSessionError("process review session token is malformed") from exc


def _valid_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and all(character.isalnum() or character in "-_" for character in value)
    )


def issue_session_token(
    review_id: str,
    experiment_id: str,
    participant_token: str,
    *,
    now: int | None = None,
    ttl_seconds: int = 1800,
) -> str:
    """Issue a short-lived capability bound to one approved review experiment."""
    if not enabled() or review_id != REVIEW_ID:
        raise ReviewSessionError("process review session is not available")
    if not _valid_identifier(experiment_id) or not participant_token:
        raise ReviewSessionError("process review session binding is invalid")
    ttl_limit = _session_ttl_limit()
    if not isinstance(ttl_seconds, int) or ttl_seconds < 60 or ttl_seconds > ttl_limit:
        raise ReviewSessionError("process review session TTL is outside the allowed range")
    issued_at = int(time.time()) if now is None else int(now)
    payload = {
        "v": 1,
        "review_id": review_id,
        "experiment_id": experiment_id,
        "participant_token": participant_token,
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
    }
    encoded_payload = _b64encode(_canonical(payload).encode("utf-8"))
    signature = hmac.new(
        _session_secret(), encoded_payload.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{SESSION_TOKEN_PREFIX}{encoded_payload}.{_b64encode(signature)}"


def verify_session_token(token: str, *, now: int | None = None) -> dict:
    """Verify and unpack a review capability without exposing it to stores."""
    if not enabled() or not isinstance(token, str) or not token.startswith(SESSION_TOKEN_PREFIX):
        raise ReviewSessionError("process review session token is invalid")
    parts = token[len(SESSION_TOKEN_PREFIX):].split(".")
    if len(parts) != 2 or not all(parts):
        raise ReviewSessionError("process review session token is malformed")
    encoded_payload, encoded_signature = parts
    expected = hmac.new(
        _session_secret(), encoded_payload.encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected, _b64decode(encoded_signature)):
        raise ReviewSessionError("process review session signature is invalid")
    try:
        payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewSessionError("process review session payload is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != _SESSION_PAYLOAD_KEYS:
        raise ReviewSessionError("process review session payload contract is invalid")
    if (
        payload.get("v") != 1
        or payload.get("review_id") != REVIEW_ID
        or not _valid_identifier(payload.get("experiment_id"))
        or not isinstance(payload.get("participant_token"), str)
        or not payload["participant_token"]
        or not isinstance(payload.get("iat"), int)
        or not isinstance(payload.get("exp"), int)
    ):
        raise ReviewSessionError("process review session binding is invalid")
    current = int(time.time()) if now is None else int(now)
    ttl = payload["exp"] - payload["iat"]
    if ttl < 60 or ttl > _session_ttl_limit() or payload["iat"] > current + 30:
        raise ReviewSessionError("process review session lifetime is invalid")
    if current >= payload["exp"]:
        raise ReviewSessionError("process review session has expired")
    return payload


def _conn() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.environ.get("EVENT_SQLITE_NOLOCK", "false").lower() == "true":
        connection = sqlite3.connect(f"file:{path}?mode=rwc&nolock=1", uri=True, timeout=30)
    else:
        connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _seed_event() -> tuple[dict, dict[str, dict], list[dict]]:
    m1 = {"measurement_id": "M1", "counts": {"A": 12, "B": 18, "C": 10}, "participant_count": 40}
    m2 = {"measurement_id": "M2", "counts": {"A": 10, "B": 20, "C": 10}, "participant_count": 40}
    m3 = {"measurement_id": "M3", "counts": {"A": 9, "B": 21, "C": 10}, "participant_count": 40}
    first_summary = {
        "round": "first",
        "summary": "개인의 노후소득 보장과 보험료 부담을 함께 봐야 하며, 세대별 부담과 재정 지속가능성에 대한 설명이 더 필요하다는 의견이 주로 제시됐다.",
        "source_note": "합성 리뷰 녹음 요약 → 사람 검수 완료",
        "reviewed_by": "process-reviewer",
    }
    second_summary = {
        "round": "second",
        "summary": "타인의 1차 의견 분포와 5개 쟁점을 확인한 뒤 급여 적정성뿐 아니라 세대 간 형평, 국가 책임과 제도 신뢰를 D안에 함께 반영해야 한다는 의견이 모였다.",
        "source_note": "합성 리뷰 녹음 요약 → 사람 검수 완료",
        "reviewed_by": "process-reviewer",
    }
    issues = [
        {"title": "노후소득 보장 수준", "opinion_count": 11},
        {"title": "보험료 부담의 수용 가능성", "opinion_count": 9},
        {"title": "세대 간 형평", "opinion_count": 8},
        {"title": "재정 지속가능성과 국가 책임", "opinion_count": 7},
        {"title": "제도 신뢰와 이행 방식", "opinion_count": 5},
    ]
    inputs = {
        "source_bundle": {"version": "review-v1", "publicity": "public", "material_count": 3},
        "constraints": {
            "version": "review-v1",
            "hard": [{"constraint_id": "hard-no-personal-calculation", "text": "개인 연금 계산을 포함하지 않는다."}],
            "soft": [{"constraint_id": "soft-balance", "text": "보장·부담·형평·지속가능성을 함께 설명한다."}],
        },
        "m1": m1,
        "deliberation_1": first_summary,
        "five_issues": {"issues": issues, "reviewed_by": "process-reviewer"},
        "m2": m2,
        "deliberation_2": second_summary,
    }
    input_hashes = {key: _digest(value) for key, value in inputs.items()}
    d_summary = "시민 숙의에서 확인된 보장성·부담·형평·지속가능성 요구를 함께 반영한 절충 D안"
    expert_review = {
        "before": {"title": "D안 설명", "body": d_summary, "limitations": "세부 시행 가정은 후속 검토"},
        "after": {"title": "D안 전문가 설명", "body": f"{d_summary}. 승인 입력과 AI 협의 근거를 공개한다.", "limitations": "장기 재정 추계 가정과 세부 시행령은 후속 검토가 필요"},
        "field_diff": [
            {"field": "title", "before": "D안 설명", "after": "D안 전문가 설명"},
            {"field": "body", "before": d_summary, "after": f"{d_summary}. 승인 입력과 AI 협의 근거를 공개한다."},
            {"field": "limitations", "before": "세부 시행 가정은 후속 검토", "after": "장기 재정 추계 가정과 세부 시행령은 후속 검토가 필요"},
        ],
        "public_reason": "AI 초안과 전문가 수정의 차이와 남은 한계를 시민이 검증할 수 있도록 보완했습니다.",
        "qna": [{"question": "D안은 네 번째 선택지인가요?", "answer": "아니요. A·B·C 선택과 분리해 수용도만 평가합니다."}],
        "editor_by": "review-editor",
        "drafted_at": "2026-08-08T20:30:00+09:00",
        "approved_by": "review-approver",
        "approved_at": "2026-08-08T20:40:00+09:00",
    }
    steps = [
        {"number": 1, "title": "동의와 제도 안내", "description": "연구 동의 뒤 성별·연령대·소득 구간만 기록합니다. 개인 연금 계산 정보는 수집하지 않습니다.", "gate": "최소 인구통계 3개 구간과 동의 버전만 append-only 저장"},
        {"number": 2, "title": "A·B·C안 설명과 1차 숙의", "description": "전문가가 제도와 개인 중심의 혜택·부담을 설명하고 청중이 의견을 나눕니다.", "gate": "녹음 요약은 사람 검수 뒤에만 D안 입력으로 승인", "deliberation": first_summary},
        {"number": 3, "title": "1차 투표", "description": "A·B·C 중 하나를 선택하고 선택안의 수용 여부와 의견을 기록합니다.", "gate": "선택·수용 여부·의견을 M1 스냅샷으로 고정", "counts": m1["counts"]},
        {"number": 4, "title": "1차 결과 기반 5대 쟁점", "description": "AI가 M1 의견을 쟁점별로 분류해 고유 의견 수를 집계하고, 사람이 검수한 정확히 다섯 쟁점을 공개합니다.", "gate": "M1 집계 해시 일치 + 정확히 5개 + 사람 승인", "issues": issues},
        {"number": 5, "title": "전문가 설명과 2차 숙의", "description": "전문가가 다섯 쟁점을 리딩하고 청중이 타인의 관심과 의견을 바탕으로 다시 숙의합니다.", "gate": "두 번째 요약도 사람 검수 뒤에만 D안 입력으로 승인", "deliberation": second_summary},
        {"number": 6, "title": "2차 투표", "description": "A·B·C를 다시 선택하고 각 안의 수용·조건부 수용·비선택 판단과 이유를 기록합니다.", "gate": "세 안 각각의 판단을 M2 스냅샷으로 고정", "counts": m2["counts"]},
        {"number": 7, "title": "3개 AI 협의 D안 생성", "description": "승인된 공개 출처·제약조건·M1·1차 숙의·5대 쟁점·M2·2차 숙의의 정확히 일곱 입력으로 D안을 만들고 사람이 최종 승인합니다.", "gate": "7개 입력 해시 + 역할이 다른 AI 3개 기록 + 사람 승인", "cohort": {"participant_type": "synthetic_review", "participant_count": 40}, "ai_summary": d_summary, "constraint_verdicts": [{"constraint_id": "hard-no-personal-calculation", "level": "hard", "satisfied": True, "explanation": "개인 계산 단계와 입력을 포함하지 않음"}, {"constraint_id": "soft-balance", "level": "soft", "satisfied": True, "explanation": "보장·부담·형평·지속가능성을 함께 설명함"}], "council": [{"role": "제안", "output": "참가자 의견과 정책 제약을 반영한 D안 초안"}, {"role": "검토", "output": "재정·형평·실행 가능성의 누락과 충돌 검토"}, {"role": "수정", "output": "검토 결과를 반영한 최종 D안과 한계 정리"}]},
        {"number": 8, "title": "전문가의 D안 설명", "description": "AI 협의 과정과 결과, 전문가 수정 전후, 공개 사유와 질의응답을 설명합니다.", "gate": "승인된 D안 해시에 묶인 전문가 초안을 별도 승인한 뒤 노출", "expert_review": expert_review},
        {"number": 9, "title": "3차 투표와 D안 별도 평가", "description": "A·B·C를 재투표합니다. D안은 네 번째 선택지가 아니라 수용도 1~5와 의견을 별도로 기록합니다.", "gate": "M3 choice는 A/B/C만 허용하고 D 응답은 별도 필드에 저장", "counts": m3["counts"], "d_acceptability": {"average": 4.1, "response_count": 40}},
        {"number": 10, "title": "최종 결과와 전문가 논평", "description": "1·2·3차 선택 변화와 D안 수용성을 구분해 보여주고 전문가가 결과의 한계와 의미를 논평합니다.", "gate": "합성 리뷰와 실제 결과를 혼합하지 않고 코호트·cutoff·집계 버전을 표시", "series": {"M1": m1["counts"], "M2": m2["counts"], "M3": m3["counts"]}},
    ]
    event = {
        "schema_version": "aipol-process-review-v2",
        "review_id": REVIEW_ID,
        "contract_version": "4.0",
        "decision_at": "2026-08-08T22:00:00+09:00",
        "cohort": {"kind": "synthetic_review", "read_only": True, "participant_count": 40},
        "notice": "아래 수치는 프로세스 연결을 검토하기 위한 격리된 합성 이벤트이며 실제 투표 결과가 아닙니다.",
        "forbidden_stages": ["개인 연금 계산", "개인 영향", "예상 수령액 산출"],
        "input_hashes": input_hashes,
        "steps": steps,
    }
    return event, inputs, steps


def _fixture_definition(event: dict, inputs: dict[str, dict], steps: list[dict]) -> dict:
    """Return the approved, deterministic material used by the interactive review."""
    issue_content = {
        "title": "1차 결과 기반 5대 핵심 쟁점",
        "body": steps[3]["description"],
        "issues": [
            {"issue_id": f"review-issue-{index}", **issue}
            for index, issue in enumerate(steps[3]["issues"], start=1)
        ],
        "input_hashes": {"m1": event["input_hashes"]["m1"]},
        "human_reviewed": True,
        "reviewed_by": "process-reviewer",
        "synthetic_review": True,
        "data_class": "synthetic_review",
    }
    d_content = {
        "title": "AI 협의 D안",
        "body": steps[6]["ai_summary"],
        "limitations": "장기 재정 추계 가정과 세부 시행령은 후속 검토가 필요합니다.",
        "input_hashes": event["input_hashes"],
        "input_snapshot": inputs,
        "council": steps[6]["council"],
        "constraint_verdicts": steps[6]["constraint_verdicts"],
        "human_reviewed": True,
        "approved_by": "process-review-approver",
        "synthetic_review": True,
        "data_class": "synthetic_review",
    }
    expert = steps[7]["expert_review"]
    expert_content = {
        "title": expert["after"]["title"],
        "body": expert["after"]["body"],
        "limitations": expert["after"]["limitations"],
        "d_artifact_hash": _digest(d_content),
        "before": expert["before"],
        "after": expert["after"],
        "field_diff": expert["field_diff"],
        "public_reason": expert["public_reason"],
        "qna": expert["qna"],
        "human_reviewed": True,
        "synthetic_review": True,
        "data_class": "synthetic_review",
    }
    return {
        "fixture_version": FIXTURE_VERSION,
        "experiment": {
            "title": "연금개혁 AI 숙의민주주의 정책실험 — REVIEW/SYNTHETIC DATA",
            "experiment_version": FIXTURE_VERSION,
            "session_id": REVIEW_ID,
            "consent_version": "pension-review-consent-v1",
            "consent_text": (
                "이 세션은 프로세스 검토용 합성 데이터입니다. 실제 투표 결과가 아니며 "
                "개인 연금 계산 정보는 수집하지 않습니다."
            ),
            "question_id": "pension-policy-choice",
            "question_text": "현재 설명을 기준으로 A·B·C안 중 어느 안을 선택하시겠습니까?",
            "option_set_version": "pension-review-options-v1",
            "policy_options": [
                {"policy_option_id": "A", "label": "A안", "policy_version": "pension-review-options-v1", "source": "approved synthetic review fixture", "approved_by": "process-review-approver", "lever_values": {"balance": "benefit"}},
                {"policy_option_id": "B", "label": "B안", "policy_version": "pension-review-options-v1", "source": "approved synthetic review fixture", "approved_by": "process-review-approver", "lever_values": {"balance": "balanced"}},
                {"policy_option_id": "C", "label": "C안", "policy_version": "pension-review-options-v1", "source": "approved synthetic review fixture", "approved_by": "process-review-approver", "lever_values": {"balance": "sustainability"}},
            ],
            "capacity": 40,
            "created_by": "process-review-editor",
            "procedure_version": "v4",
        },
        "artifacts": {
            "issue_deliberation": issue_content,
            "ai_opinion": d_content,
            "expert_explanation": expert_content,
        },
    }


def _insert_fixture_artifacts(experiment_id: str, fixture: dict) -> None:
    import db

    approved_at = "2026-08-08T11:40:00+00:00"
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = {
            row[0] for row in connection.execute(
                "SELECT kind FROM aipol_artifacts WHERE experiment_id=?", (experiment_id,)
            )
        }
        for kind, content in fixture["artifacts"].items():
            if kind in existing:
                continue
            digest = _digest(content)
            approval_id = f"review-artifact:{REVIEW_ID}:{kind}:v1"
            connection.execute(
                "INSERT INTO aipol_approval_events(id,experiment_id,object_type,object_id,"
                "content_hash,approval_id,editor_by,approver_by,approved_at,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    f"review-approval-{kind}", experiment_id, "artifact", kind, digest,
                    approval_id, "process-review-editor", "process-review-approver",
                    approved_at, time.time(),
                ),
            )
            connection.execute(
                "INSERT INTO aipol_artifacts(id,experiment_id,kind,artifact_id,artifact_version,"
                "content_hash,content,approval_id,approved_by,approved_at,fallback_used,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"review-artifact-row-{kind}", experiment_id, kind,
                    f"review-{kind}-v1", "review-v1", digest, _canonical(content),
                    approval_id, "process-review-approver", approved_at, 0, time.time(),
                ),
            )


def _validate_interactive_fixture(experiment_id: str, fixture: dict) -> None:
    import aipol_store

    experiment = aipol_store.get_experiment(experiment_id)
    manifest = experiment.get("freeze_manifest") or {}
    if (
        experiment.get("experiment_version") != FIXTURE_VERSION
        or experiment.get("session_id") != REVIEW_ID
        or experiment.get("procedure_config", {}).get("version")
        != "aipol-pension-deliberation-v4"
        or manifest.get("status") != "frozen"
        or manifest.get("collection_enabled") is not False
    ):
        raise RuntimeError("process review experiment fixture mismatch")
    for kind, expected_content in fixture["artifacts"].items():
        artifact = aipol_store.artifact_public(experiment_id, kind, include_content=True)
        if (
            not artifact
            or artifact.get("content_hash") != _digest(expected_content)
            or artifact.get("content") != expected_content
        ):
            raise RuntimeError(f"process review artifact fixture mismatch: {kind}")


def _ensure_interactive_fixture(event: dict, inputs: dict[str, dict], steps: list[dict]) -> None:
    import aipol_store
    import db

    review_path = database_path().resolve()
    if review_path == db.DB_PATH.resolve():
        raise RuntimeError("process review database must be physically isolated")
    fixture = _fixture_definition(event, inputs, steps)
    fixture_hash = _digest(fixture)
    with db.use_database(review_path):
        db.init()
        aipol_store.init()
        with db._conn() as connection:
            binding = connection.execute(
                "SELECT * FROM aipol_process_review_bindings WHERE review_id=?", (REVIEW_ID,)
            ).fetchone()
            experiment_row = connection.execute(
                "SELECT id FROM aipol_experiments WHERE experiment_version=? AND session_id=?",
                (FIXTURE_VERSION, REVIEW_ID),
            ).fetchone()
        if binding:
            if (
                binding["fixture_version"] != FIXTURE_VERSION
                or binding["fixture_hash"] != fixture_hash
                or not experiment_row
                or binding["experiment_id"] != experiment_row["id"]
            ):
                raise RuntimeError("process review fixture binding mismatch")
            experiment_id = binding["experiment_id"]
        else:
            if experiment_row:
                experiment_id = experiment_row["id"]
            else:
                experiment_id = aipol_store.create_experiment(**fixture["experiment"])["id"]
            experiment = aipol_store.get_experiment(experiment_id)
            if not experiment["freeze_manifest"]:
                aipol_store.set_freeze_manifest(
                    experiment_id,
                    {
                        "manifest_id": "pension-review-freeze-v1",
                        "experiment_version": experiment["experiment_version"],
                        "option_set_version": experiment["measurement_spec"]["option_set_version"],
                        "measurement_spec_hash": experiment["measurement_spec_hash"],
                        "status": "frozen",
                        "collection_enabled": False,
                        "approvals": [],
                    },
                    approved_by="process-review-approver",
                )
            _insert_fixture_artifacts(experiment_id, fixture)
            with db._conn() as connection:
                connection.execute(
                    "INSERT INTO aipol_process_review_bindings "
                    "(review_id,fixture_version,fixture_hash,experiment_id,created_at) "
                    "VALUES(?,?,?,?,?)",
                    (
                        REVIEW_ID, FIXTURE_VERSION, fixture_hash, experiment_id,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
        _validate_interactive_fixture(experiment_id, fixture)


def issue_review_session(review_id: str) -> dict:
    """Register a synthetic participant against the server-owned fixture only."""
    import aipol_store
    import db

    if not enabled() or review_id != REVIEW_ID:
        raise KeyError(review_id)
    review_path = database_path().resolve()
    if review_path == db.DB_PATH.resolve():
        raise RuntimeError("process review database must be physically isolated")
    # Validate every signing input before creating a participant so a bad
    # deployment cannot leave an unusable synthetic session behind.
    _session_secret()
    ttl_seconds = min(1800, _session_ttl_limit())
    with db.use_database(review_path):
        with db._conn() as connection:
            binding = connection.execute(
                "SELECT experiment_id FROM aipol_process_review_bindings WHERE review_id=?",
                (review_id,),
            ).fetchone()
        if not binding:
            raise KeyError(review_id)
        registration = aipol_store.register_participant(
            binding["experiment_id"], "synthetic", audit_actor="server:process-review-session"
        )
    issued_at = int(time.time())
    token = issue_session_token(
        review_id,
        binding["experiment_id"],
        registration["participant_token"],
        now=issued_at,
        ttl_seconds=ttl_seconds,
    )
    return {
        "review_id": review_id,
        "experiment_id": binding["experiment_id"],
        "participant_token": token,
        "expires_at": datetime.fromtimestamp(
            issued_at + ttl_seconds, timezone.utc
        ).isoformat(),
        "synthetic_review": True,
        "data_class": "synthetic_review",
    }


def init() -> None:
    if not enabled():
        return
    event, inputs, steps = _seed_event()
    with _conn() as connection:
        connection.executescript(_SCHEMA)
        connection.execute(
            "INSERT OR IGNORE INTO aipol_process_review_events "
            "(id,contract_version,cohort_type,participant_count,notice,forbidden_stages_json,content_hash,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (REVIEW_ID, event["contract_version"], event["cohort"]["kind"], event["cohort"]["participant_count"], event["notice"], _canonical(event["forbidden_stages"]), _digest(event), datetime.now(timezone.utc).isoformat()),
        )
        connection.executemany(
            "INSERT OR IGNORE INTO aipol_process_review_inputs (review_id,input_key,payload_json,content_hash) VALUES(?,?,?,?)",
            [(REVIEW_ID, key, _canonical(value), _digest(value)) for key, value in inputs.items()],
        )
        connection.executemany(
            "INSERT OR IGNORE INTO aipol_process_review_steps (review_id,step_number,payload_json,content_hash) VALUES(?,?,?,?)",
            [(REVIEW_ID, step["number"], _canonical(step), _digest(step)) for step in steps],
        )
    _ensure_interactive_fixture(event, inputs, steps)


def get(review_id: str) -> dict:
    if not enabled():
        raise KeyError("process review is disabled")
    with _conn() as connection:
        event_row = connection.execute("SELECT * FROM aipol_process_review_events WHERE id=? AND cohort_type='synthetic_review'", (review_id,)).fetchone()
        input_rows = connection.execute("SELECT * FROM aipol_process_review_inputs WHERE review_id=? ORDER BY input_key", (review_id,)).fetchall()
        step_rows = connection.execute("SELECT * FROM aipol_process_review_steps WHERE review_id=? ORDER BY step_number", (review_id,)).fetchall()
    if not event_row or len(input_rows) != 7 or len(step_rows) != 10:
        raise KeyError("process review not found")
    inputs = {}
    for row in input_rows:
        payload = json.loads(row["payload_json"])
        if _digest(payload) != row["content_hash"]:
            raise RuntimeError("process review input hash mismatch")
        inputs[row["input_key"]] = payload
    steps = []
    for row in step_rows:
        payload = json.loads(row["payload_json"])
        if payload.get("number") != row["step_number"] or _digest(payload) != row["content_hash"]:
            raise RuntimeError("process review step hash mismatch")
        steps.append(payload)
    snapshot = {
        "schema_version": "aipol-process-review-v2",
        "review_id": event_row["id"],
        "contract_version": event_row["contract_version"],
        "decision_at": "2026-08-08T22:00:00+09:00",
        "cohort": {"kind": event_row["cohort_type"], "read_only": True, "participant_count": event_row["participant_count"]},
        "notice": event_row["notice"],
        "forbidden_stages": json.loads(event_row["forbidden_stages_json"]),
        "input_hashes": {row["input_key"]: row["content_hash"] for row in input_rows},
        "steps": steps,
    }
    if _digest(snapshot) != event_row["content_hash"]:
        raise RuntimeError("process review event hash mismatch")
    return {**snapshot, "content_hash": event_row["content_hash"], "stored_at": event_row["created_at"]}
