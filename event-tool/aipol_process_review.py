"""Read-only, isolated mock snapshot for the v4 process review.

The review fixture is deliberately stored outside the participant/measurement
ledger.  It can only be seeded and served when the explicit environment flag is
enabled, and its table is append-only so a reviewed URL always resolves to the
same content hash.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


REVIEW_ID = "pension-v4-20260808-r1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS aipol_process_review_snapshots (
  id TEXT PRIMARY KEY,
  contract_version TEXT NOT NULL,
  fixture_kind TEXT NOT NULL CHECK(fixture_kind='mock'),
  snapshot_json TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS aipol_process_review_snapshots_no_update
BEFORE UPDATE ON aipol_process_review_snapshots BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_process_review_snapshots_no_delete
BEFORE DELETE ON aipol_process_review_snapshots BEGIN SELECT RAISE(ABORT, 'append-only'); END;
"""


def enabled() -> bool:
    return os.environ.get("AIPOL_PROCESS_REVIEW_ENABLED", "false").lower() == "true"


def database_path() -> Path:
    configured = os.environ.get("AIPOL_PROCESS_REVIEW_DB_PATH", "").strip()
    if configured:
        return Path(configured)
    event_path = Path(os.environ.get("EVENT_DB_PATH", "event.db"))
    return event_path.with_name("aipol-process-review.db")


def _conn() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Azure Files uses the same explicitly reviewed single-writer/no-lock
    # contract as the participant database. The process-review DB remains a
    # physically separate file; this only selects the compatible SQLite URI.
    if os.environ.get("EVENT_SQLITE_NOLOCK", "false").lower() == "true":
        connection = sqlite3.connect(f"file:{path}?mode=rwc&nolock=1", uri=True, timeout=30)
    else:
        connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _snapshot() -> dict:
    m1 = {"A": 12, "B": 18, "C": 10}
    m2 = {"A": 10, "B": 20, "C": 10}
    m3 = {"A": 9, "B": 21, "C": 10}
    first_summary = {
        "round": "first",
        "summary": "개인의 노후소득 보장과 보험료 부담을 함께 봐야 하며, 세대별 부담과 재정 지속가능성에 대한 설명이 더 필요하다는 의견이 주로 제시됐다.",
        "source_note": "목업 녹음 요약 → 사람 검수 완료",
        "reviewed_by": "process-reviewer",
    }
    second_summary = {
        "round": "second",
        "summary": "타인의 1차 의견 분포와 5개 쟁점을 확인한 뒤 급여 적정성뿐 아니라 세대 간 형평, 국가 책임과 제도 신뢰를 D안에 함께 반영해야 한다는 의견이 모였다.",
        "source_note": "목업 녹음 요약 → 사람 검수 완료",
        "reviewed_by": "process-reviewer",
    }
    hashes = {
        "m1": _digest({"measurement_id": "M1", "counts": m1, "participant_count": 40}),
        "deliberation_1": _digest(first_summary),
        "m2": _digest({"measurement_id": "M2", "counts": m2, "participant_count": 40}),
        "deliberation_2": _digest(second_summary),
    }
    issues = [
        {"title": "노후소득 보장 수준", "opinion_count": 11},
        {"title": "보험료 부담의 수용 가능성", "opinion_count": 9},
        {"title": "세대 간 형평", "opinion_count": 8},
        {"title": "재정 지속가능성과 국가 책임", "opinion_count": 7},
        {"title": "제도 신뢰와 이행 방식", "opinion_count": 5},
    ]
    return {
        "schema_version": "aipol-process-review-v1",
        "review_id": REVIEW_ID,
        "contract_version": "4.0",
        "decision_at": "2026-08-08T22:00:00+09:00",
        "fixture": {"kind": "mock", "read_only": True, "participant_count": 40},
        "notice": "아래 수치는 프로세스 연결을 검토하기 위한 목업 DB 데이터이며 실제 투표 결과가 아닙니다.",
        "forbidden_stages": ["개인 연금 계산", "개인 영향", "예상 수령액 산출"],
        "input_hashes": hashes,
        "steps": [
            {
                "number": 1,
                "title": "동의와 제도 안내",
                "description": "연구 동의 뒤 성별·연령대·소득 구간만 기록합니다. 개인 연금 계산 정보는 수집하지 않습니다.",
                "gate": "최소 인구통계 3개 구간과 동의 버전만 append-only 저장",
            },
            {
                "number": 2,
                "title": "A·B·C안 설명과 1차 숙의",
                "description": "전문가가 제도와 개인 중심의 혜택·부담을 설명하고 청중이 의견을 나눕니다.",
                "gate": "녹음 요약은 사람 검수 뒤에만 D안 입력으로 승인",
                "deliberation": first_summary,
            },
            {
                "number": 3,
                "title": "1차 투표",
                "description": "A·B·C 중 하나를 선택하고 선택안의 수용 여부와 의견을 기록합니다.",
                "gate": "선택·수용 여부·의견을 M1 스냅샷으로 고정",
                "counts": m1,
            },
            {
                "number": 4,
                "title": "1차 결과 기반 5대 쟁점",
                "description": "AI가 M1 의견을 쟁점별로 분류해 고유 의견 수를 집계하고, 사람이 검수한 정확히 다섯 쟁점을 공개합니다.",
                "gate": "M1 집계 해시 일치 + 정확히 5개 + 사람 승인",
                "issues": issues,
            },
            {
                "number": 5,
                "title": "전문가 설명과 2차 숙의",
                "description": "전문가가 다섯 쟁점을 리딩하고 청중이 타인의 관심과 의견을 바탕으로 다시 숙의합니다.",
                "gate": "두 번째 요약도 사람 검수 뒤에만 D안 입력으로 승인",
                "deliberation": second_summary,
            },
            {
                "number": 6,
                "title": "2차 투표",
                "description": "A·B·C를 다시 선택하고 각 안의 수용·조건부 수용·비선택 판단과 이유를 기록합니다.",
                "gate": "세 안 각각의 판단을 M2 스냅샷으로 고정",
                "counts": m2,
            },
            {
                "number": 7,
                "title": "3개 AI 협의 D안 생성",
                "description": "검수된 두 숙의 요약과 M1·M2 투표 결과를 승인 입력으로 사용해 D안을 만들고 사람이 최종 승인합니다.",
                "gate": "4개 입력 해시 + 역할이 다른 AI 3개 기록 + 사람 승인",
                "council": [
                    {"role": "제안", "output": "참가자 의견과 정책 제약을 반영한 D안 초안"},
                    {"role": "검토", "output": "재정·형평·실행 가능성의 누락과 충돌 검토"},
                    {"role": "수정", "output": "검토 결과를 반영한 최종 D안과 한계 정리"},
                ],
            },
            {
                "number": 8,
                "title": "전문가의 D안 설명",
                "description": "AI 협의 과정과 결과, A·B·C와의 차이, 의의와 한계를 설명하고 간단한 질의응답을 진행합니다.",
                "gate": "사람 승인된 동일 D안 콘텐츠 해시만 노출",
            },
            {
                "number": 9,
                "title": "3차 투표와 D안 별도 평가",
                "description": "A·B·C를 재투표합니다. D안은 네 번째 선택지가 아니라 수용도 1~5와 의견을 별도로 기록합니다.",
                "gate": "M3 choice는 A/B/C만 허용하고 D 응답은 별도 필드에 저장",
                "counts": m3,
                "d_acceptability": {"average": 4.1, "response_count": 40},
            },
            {
                "number": 10,
                "title": "최종 결과와 전문가 논평",
                "description": "1·2·3차 선택 변화와 D안 수용성을 구분해 보여주고 전문가가 결과의 한계와 의미를 논평합니다.",
                "gate": "목업과 실제 결과를 혼합하지 않고 코호트·cutoff·집계 버전을 표시",
                "series": {"M1": m1, "M2": m2, "M3": m3},
            },
        ],
    }


def init() -> None:
    if not enabled():
        return
    with _conn() as connection:
        connection.executescript(_SCHEMA)
        snapshot = _snapshot()
        snapshot_json = _canonical(snapshot)
        connection.execute(
            "INSERT OR IGNORE INTO aipol_process_review_snapshots "
            "(id,contract_version,fixture_kind,snapshot_json,content_hash,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                REVIEW_ID,
                snapshot["contract_version"],
                "mock",
                snapshot_json,
                hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get(review_id: str) -> dict:
    if not enabled():
        raise KeyError("process review is disabled")
    with _conn() as connection:
        row = connection.execute(
            "SELECT * FROM aipol_process_review_snapshots WHERE id=? AND fixture_kind='mock'",
            (review_id,),
        ).fetchone()
    if not row:
        raise KeyError("process review not found")
    calculated = hashlib.sha256(row["snapshot_json"].encode("utf-8")).hexdigest()
    if calculated != row["content_hash"]:
        raise RuntimeError("process review snapshot hash mismatch")
    snapshot = json.loads(row["snapshot_json"])
    return {**snapshot, "content_hash": row["content_hash"], "stored_at": row["created_at"]}
