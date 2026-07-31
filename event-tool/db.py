"""경량 저장 — SQLite 파일 기반 개발·연구 환경.

P1: 행사(event)·회차(round) 준비 저장. 회차 내용(서문·첨부·안·프로필)은 JSON 컬럼(도메인 중립).
P2에서 응답(response)·중복차단 UNIQUE(round,참여자) 추가 예정.
"""
from __future__ import annotations

import json
import hashlib
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

DB_PATH = Path(os.environ.get("EVENT_DB_PATH", Path(__file__).parent / "event.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, context TEXT DEFAULT '',
  active_round_id TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS rounds (
  id TEXT PRIMARY KEY, event_id TEXT NOT NULL, round_no INTEGER NOT NULL,
  title TEXT NOT NULL, intro TEXT DEFAULT '[]', attachments TEXT DEFAULT '[]',
  proposals TEXT DEFAULT '[]', profile_fields TEXT DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'draft',   -- draft | open | closed
  created_at REAL,
  UNIQUE(event_id, round_no),
  FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
);
-- 참여자: 행사 단위, 1인 1참여코드(중복투표 차단 + 회차 간 이동 연결 키)
CREATE TABLE IF NOT EXISTS participants (
  id TEXT PRIMARY KEY, event_id TEXT NOT NULL, code TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'human',   -- human | virtual
  profile TEXT DEFAULT '{}', created_at REAL,
  UNIQUE(event_id, code),
  FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
);
-- 응답: 참여자 × 회차. UNIQUE(round, participant)=같은 회차 중복 제출 차단.
CREATE TABLE IF NOT EXISTS responses (
  id TEXT PRIMARY KEY, round_id TEXT NOT NULL, participant_id TEXT NOT NULL,
  answers TEXT NOT NULL, segment TEXT DEFAULT '', created_at REAL,
  UNIQUE(round_id, participant_id),
  FOREIGN KEY(round_id) REFERENCES rounds(id) ON DELETE CASCADE,
  FOREIGN KEY(participant_id) REFERENCES participants(id) ON DELETE CASCADE
);
-- 숙의 잡: 서버측 장시간 작업(진행/취소/실패). 브라우저 세션에 안 묶임(R2).
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, round_id TEXT NOT NULL, kind TEXT DEFAULT 'deliberate',
  status TEXT NOT NULL DEFAULT 'running',   -- running | done | failed | cancelled
  progress TEXT DEFAULT '', error TEXT DEFAULT '', cancel INTEGER DEFAULT 0,
  created_at REAL, updated_at REAL
);
-- 숙의 결과(AI정책안): 원안·현재본·수정이력·승인 + 과정 기록·provenance. P4 승인·P5 →설문이 이걸 씀.
CREATE TABLE IF NOT EXISTS deliberations (
  id TEXT PRIMARY KEY, round_id TEXT NOT NULL, job_id TEXT,
  ai_original TEXT, current TEXT, revisions TEXT DEFAULT '[]',
  transcript TEXT DEFAULT '{}', provenance TEXT DEFAULT '[]',
  approved_by TEXT, approved_at REAL, created_at REAL,
  FOREIGN KEY(round_id) REFERENCES rounds(id) ON DELETE CASCADE
);
-- 운영 관리자 TOTP replay 방지 상태. 프로세스 재시작 뒤에도 마지막 counter를 보존한다.
CREATE TABLE IF NOT EXISTS admin_auth_totp_counters (
  username TEXT PRIMARY KEY,
  last_counter INTEGER NOT NULL,
  updated_at REAL NOT NULL
);
"""


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Azure Files(SMB)는 POSIX byte-range lock을 지원하지 않는다. ACA를 반드시 1 replica로
    # 고정한 운영 환경에서만 nolock URI를 명시적으로 켠다. 일반 로컬 환경은 표준 잠금을 쓴다.
    if os.environ.get("EVENT_SQLITE_NOLOCK", "false").lower() == "true":
        c = sqlite3.connect(f"file:{DB_PATH}?mode=rwc&nolock=1", uri=True, timeout=30)
    else:
        c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=30000")
    return c


def init():
    with _conn() as c:
        c.executescript(_SCHEMA)


def fail_interrupted_jobs() -> int:
    """프로세스 재시작으로 끊긴 인메모리 작업을 실행 중으로 남기지 않는다."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE jobs SET status='failed', error=?, updated_at=? WHERE status='running'",
            ("서버가 재시작되어 작업이 중단됐습니다. 다시 실행해 주세요.", time.time()),
        )
    return cur.rowcount


def claim_totp_counter(username: str, counter: int) -> bool:
    """Atomically accept only a strictly newer TOTP counter for an account."""
    with _conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT last_counter FROM admin_auth_totp_counters WHERE username=?",
            (username,),
        ).fetchone()
        if current is not None and int(current["last_counter"]) >= counter:
            return False
        connection.execute(
            """INSERT INTO admin_auth_totp_counters(username,last_counter,updated_at)
               VALUES(?,?,?)
               ON CONFLICT(username) DO UPDATE SET
                 last_counter=excluded.last_counter,
                 updated_at=excluded.updated_at""",
            (username, counter, time.time()),
        )
    return True


def _id(p): return f"{p}-{uuid.uuid4().hex[:8]}"
_J = ("intro", "attachments", "proposals", "profile_fields")


def _round_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    for k in _J:
        d[k] = json.loads(d.get(k) or "[]")
    return d


# ── 행사 ────────────────────────────────────────────────────────────────
def create_event(title: str, context: str = "") -> dict:
    if not title.strip():
        raise ValueError("행사 제목이 필요합니다")
    eid = _id("ev")
    with _conn() as c:
        c.execute("INSERT INTO events(id,title,context,created_at) VALUES(?,?,?,?)",
                  (eid, title.strip(), context, time.time()))
    return get_event(eid)


def get_event(eid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
        return dict(r) if r else None


def list_events() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM events ORDER BY created_at DESC")]


# ── 회차 ────────────────────────────────────────────────────────────────
def create_round(event_id: str, *, round_no: int, title: str, intro=None, attachments=None,
                 proposals=None, profile_fields=None) -> dict:
    if not get_event(event_id):
        raise ValueError("행사가 없습니다")
    rid = _id("rd")
    with _conn() as c:
        try:
            c.execute("INSERT INTO rounds(id,event_id,round_no,title,intro,attachments,proposals,"
                      "profile_fields,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (rid, event_id, int(round_no), title.strip(), json.dumps(intro or []),
                       json.dumps(attachments or []), json.dumps(proposals or []),
                       json.dumps(profile_fields or []), time.time()))
        except sqlite3.IntegrityError:
            raise ValueError(f"{round_no}회차가 이미 있습니다")
    return get_round(rid)


def update_round(rid: str, **fields) -> dict:
    r = get_round(rid)
    if not r:
        raise KeyError(rid)
    allowed = {"title", "intro", "attachments", "proposals", "profile_fields", "status"}
    sets, vals = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k}=?")
        vals.append(json.dumps(v) if k in _J else v)
    if sets:
        with _conn() as c:
            c.execute(f"UPDATE rounds SET {','.join(sets)} WHERE id=?", vals + [rid])
    return get_round(rid)


def get_round(rid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM rounds WHERE id=?", (rid,)).fetchone()
        return _round_row(r) if r else None


def list_rounds(event_id: str) -> list[dict]:
    with _conn() as c:
        return [_round_row(r) for r in
                c.execute("SELECT * FROM rounds WHERE event_id=? ORDER BY round_no", (event_id,))]


def update_event(eid: str, *, title: str | None = None, context: str | None = None) -> dict:
    """행사(정책) 이름·맥락 편집."""
    sets, vals = [], []
    if title is not None:
        if not title.strip():
            raise ValueError("행사 제목이 필요합니다")
        sets.append("title=?"); vals.append(title.strip())
    if context is not None:
        sets.append("context=?"); vals.append(context)
    if sets:
        with _conn() as c:
            c.execute(f"UPDATE events SET {','.join(sets)} WHERE id=?", vals + [eid])
    return get_event(eid)


def delete_event(eid: str) -> None:
    """행사 삭제 — 회차·참여자·응답·잡·숙의까지 cascade(운영자 되돌리기·정리용)."""
    with _conn() as c:
        c.execute("DELETE FROM events WHERE id=?", (eid,))


def delete_round(rid: str) -> None:
    """회차 삭제 — 응답·잡·숙의 cascade."""
    with _conn() as c:
        c.execute("DELETE FROM rounds WHERE id=?", (rid,))


def set_active_round(event_id: str, round_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE events SET active_round_id=? WHERE id=?", (round_id, event_id))


# ── 참여자 · 응답 (P2) ────────────────────────────────────────────────────
def _code_hash(code: str) -> str:
    return "sha256:" + hashlib.sha256(code.encode("utf-8")).hexdigest()


def get_or_create_participant(event_id: str, code: str | None, profile: dict, kind: str = "human") -> dict:
    """참여코드로 조회-or-생성. 코드 = 중복투표 차단 + 회차 간 이동 연결 키."""
    with _conn() as c:
        if code:
            # 신규 데이터는 원문 참여 코드를 저장하지 않는다. 기존 로컬 데이터는 호환 조회한다.
            stored_code = _code_hash(code)
            r = c.execute("SELECT * FROM participants WHERE event_id=? AND code IN (?,?)",
                          (event_id, stored_code, code)).fetchone()
            if r:
                if profile:  # 프로필 누적
                    merged = {**json.loads(r["profile"] or "{}"), **profile}
                    c.execute("UPDATE participants SET profile=? WHERE id=?", (json.dumps(merged), r["id"]))
                return {**dict(r), "code": code, "profile": json.loads(r["profile"] or "{}")}
        pid = _id("pt")
        new_code = code or f"C{secrets.token_hex(16).upper()}"
        c.execute("INSERT INTO participants(id,event_id,code,kind,profile,created_at) VALUES(?,?,?,?,?,?)",
                  (pid, event_id, _code_hash(new_code), kind, json.dumps(profile or {}), time.time()))
    return {"id": pid, "event_id": event_id, "code": new_code, "kind": kind, "profile": profile or {}}


def save_response(round_id: str, code: str | None, profile: dict, answers: dict,
                  segment_key: str = "", kind: str = "human") -> dict:
    """계약 통과(앱 계층)한 응답 저장. UNIQUE(round,참여자)로 중복 제출 차단."""
    rd = get_round(round_id)
    if not rd:
        raise KeyError(round_id)
    seg = str(profile.get(segment_key)) if segment_key and profile.get(segment_key) else ""
    p = get_or_create_participant(rd["event_id"], code, profile, kind)
    with _conn() as c:
        try:
            c.execute("INSERT INTO responses(id,round_id,participant_id,answers,segment,created_at) VALUES(?,?,?,?,?,?)",
                      (_id("rs"), round_id, p["id"], json.dumps(answers), seg, time.time()))
        except sqlite3.IntegrityError:
            raise ValueError("이미 이 회차에 응답하셨습니다(중복 제출 불가)")
    return {"code": p["code"], "segment": seg}


def round_stats(round_id: str) -> dict:
    """진행자 수집 현황 — 응답 수 + 안별 수용/조건부/거부 분포 + 세그먼트별."""
    rd = get_round(round_id)
    if not rd:
        raise KeyError(round_id)
    with _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM responses WHERE round_id=?", (round_id,))]
    dist = {p["id"]: {"accept": 0, "conditional": 0, "reject": 0} for p in rd["proposals"]}
    seg = {}
    for r in rows:
        ans = json.loads(r["answers"])
        for pid, a in ans.items():
            if pid in dist and a.get("stance") in dist[pid]:
                dist[pid][a["stance"]] += 1
        g = r.get("segment") or "미표기"
        seg[g] = seg.get(g, 0) + 1
    return {"n": len(rows), "distribution": dist, "by_segment": seg}


# ── 숙의 잡 · 결과 (P3) ────────────────────────────────────────────────────
_DJ = ("ai_original", "current", "revisions", "transcript", "provenance")


def create_job(round_id: str) -> dict:
    jid = _id("job")
    with _conn() as c:
        c.execute("INSERT INTO jobs(id,round_id,status,progress,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                  (jid, round_id, "running", "시작", time.time(), time.time()))
    return get_job(jid)


def update_job(jid: str, **f):
    if not f:
        return
    sets, vals = [], []
    for k, v in f.items():
        sets.append(f"{k}=?"); vals.append(v)
    sets.append("updated_at=?"); vals.append(time.time())
    with _conn() as c:
        c.execute(f"UPDATE jobs SET {','.join(sets)} WHERE id=?", vals + [jid])


def get_job(jid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return dict(r) if r else None


def job_cancelled(jid: str) -> bool:
    j = get_job(jid)
    return bool(j and j["cancel"])


def save_deliberation(round_id: str, job_id: str, *, ai_original, current, transcript, provenance) -> dict:
    did = _id("dl")
    with _conn() as c:
        c.execute("INSERT INTO deliberations(id,round_id,job_id,ai_original,current,revisions,"
                  "transcript,provenance,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (did, round_id, job_id, json.dumps(ai_original), json.dumps(current), "[]",
                   json.dumps(transcript), json.dumps(provenance), time.time()))
    return get_deliberation(did)


def get_deliberation(did: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM deliberations WHERE id=?", (did,)).fetchone()
    if not r:
        return None
    d = dict(r)
    for k in _DJ:
        d[k] = json.loads(d.get(k) or ("[]" if k in ("revisions", "provenance") else "{}"))
    return d


def deliberations_for_round(round_id: str) -> list[dict]:
    with _conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM deliberations WHERE round_id=? ORDER BY created_at DESC", (round_id,))]
    return [get_deliberation(i) for i in ids]


def revise_deliberation(did: str, *, editor: str, title: str, body: str, reason: str,
                        source: str = "개인수정", meeting: dict | None = None) -> dict:
    """AI안 사람수정/전문가회의 보강. 수정이력 append + 승인 무효화(재승인 필요=human_gate 무결성)."""
    from datetime import datetime, timezone
    d = get_deliberation(did)
    if not d:
        raise KeyError(did)
    after = {**(d["current"] or {}), "title": title, "body": body}
    rev = {"editor": editor, "before": d["current"], "after": after, "reason": reason,
           "source": source, "ts": datetime.now(timezone.utc).isoformat()}
    if meeting:  # 전문가회의: 참석자·승인자·근거
        rev["meeting"] = {"attendees": meeting.get("attendees", ""), "approver": meeting.get("approver", ""),
                          "basis": meeting.get("basis", "")}
    revs = (d["revisions"] or []) + [rev]
    with _conn() as c:  # current 변경 → 승인 무효화
        c.execute("UPDATE deliberations SET current=?, revisions=?, approved_by=NULL, approved_at=NULL WHERE id=?",
                  (json.dumps(after), json.dumps(revs), did))
    return get_deliberation(did)


def to_next_round(did: str, next_round_no: int) -> dict:
    """승인된 AI안을 다음 회차 설문으로(원안 + AI안). 미승인은 차단(human_gate 불변식)."""
    d = get_deliberation(did)
    if not d:
        raise KeyError(did)
    if not d.get("approved_by"):
        raise ValueError("미승인 안은 다음 회차로 내보낼 수 없습니다 — 먼저 승인하세요")
    rd = get_round(d["round_id"])
    cur = d["current"] or {}
    ai_prop = {"id": "ai안", "title": cur.get("title", "AI 통합안"), "body": cur.get("body", ""),
               "origin": "ai", "human_revised": bool(d.get("revisions"))}
    return create_round(rd["event_id"], round_no=next_round_no,
                        title=f"{next_round_no}차 (AI안 포함)", intro=rd["intro"],
                        attachments=rd["attachments"], proposals=list(rd["proposals"]) + [ai_prop],
                        profile_fields=rd["profile_fields"])


def approve_deliberation(did: str, approver: str) -> dict:
    """human_gate 승인 — 승인 후에만 다음 회차 설문화 가능(상태머신 불변식)."""
    d = get_deliberation(did)
    if not d:
        raise KeyError(did)
    import time as _t
    with _conn() as c:
        c.execute("UPDATE deliberations SET approved_by=?, approved_at=? WHERE id=?", (approver, _t.time(), did))
    return get_deliberation(did)


def list_participants(event_id: str) -> list[dict]:
    """행사 참여자 목록 + 프로필(가상은 페르소나 전문 포함) + 응답 회차 수."""
    with _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM participants WHERE event_id=? ORDER BY code", (event_id,))]
        cnt = {r["participant_id"]: r["n"] for r in
               c.execute("SELECT participant_id, COUNT(*) n FROM responses r "
                         "JOIN rounds rd ON r.round_id=rd.id WHERE rd.event_id=? GROUP BY participant_id", (event_id,))}
    for r in rows:
        r["profile"] = json.loads(r["profile"] or "{}")
        r["n_responses"] = cnt.get(r["id"], 0)
    return rows


def participant_detail(pid: str) -> dict | None:
    """참여자 1명 — 프로필(누구인지) + 회차별 개인 응답(입장·의견). 이동 대조용."""
    with _conn() as c:
        p = c.execute("SELECT * FROM participants WHERE id=?", (pid,)).fetchone()
        if not p:
            return None
        p = dict(p); p["profile"] = json.loads(p["profile"] or "{}")
        resp = []
        for r in c.execute("SELECT r.answers, r.segment, rd.round_no, rd.title, rd.proposals "
                           "FROM responses r JOIN rounds rd ON r.round_id=rd.id "
                           "WHERE r.participant_id=? ORDER BY rd.round_no", (pid,)):
            d = dict(r); d["answers"] = json.loads(d["answers"])
            d["proposals"] = json.loads(d["proposals"] or "[]")
            resp.append(d)
    p["responses"] = resp
    return p


def final_report(event_id: str) -> dict:
    """종합 보고서 — 참여 구성(human/virtual 분리)·회차별 수용도·정성의견·이동·AI근거·정직한계.

    비대표성 고지(G8)는 스키마 필수 요소(누락 불가). 이동=같은 참여자 코드 연결.
    """
    ev = get_event(event_id)
    if not ev:
        raise KeyError(event_id)
    rounds = list_rounds(event_id)
    with _conn() as c:
        parts = [dict(r) for r in c.execute("SELECT * FROM participants WHERE event_id=?", (event_id,))]
        pid_kind = {p["id"]: p["kind"] for p in parts}
    composition = {"human": sum(1 for p in parts if p["kind"] == "human"),
                   "virtual": sum(1 for p in parts if p["kind"] == "virtual"), "total": len(parts)}

    per_round, resp_by_round = {}, {}
    for rd in rounds:
        with _conn() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM responses WHERE round_id=?", (rd["id"],))]
        resp_by_round[rd["round_no"]] = rows
        dist, by_kind, qual, seg = {}, {"human": {}, "virtual": {}}, {}, {}
        for p in rd["proposals"]:
            dd = {"accept": 0, "conditional": 0, "reject": 0}
            for r in rows:
                a = json.loads(r["answers"]).get(p["id"]) or {}
                if a.get("stance") in dd:
                    dd[a["stance"]] += 1
                    k = pid_kind.get(r["participant_id"], "human")
                    kk = by_kind[k if k in by_kind else "human"].setdefault(p["id"], {"accept": 0, "conditional": 0, "reject": 0})
                    kk[a["stance"]] += 1
                    t = (a.get("text") or "").strip()
                    if t:
                        qual.setdefault(p["id"], []).append({"stance": a["stance"], "text": t, "seg": r.get("segment") or ""})
            dist[p["id"]] = dd
        for r in rows:
            g = r.get("segment") or "미표기"
            seg[g] = seg.get(g, 0) + 1
        per_round[rd["round_no"]] = {"title": rd["title"], "n": len(rows), "distribution": dist,
                                     "by_kind": by_kind, "by_segment": seg,
                                     "qualitative": {k: v[:20] for k, v in qual.items()}}

    # 이동: 같은 참여자(참여자 id)로 첫↔마지막 회차 응답한 사람의 안별 입장 변화(공유 안)
    movement = {}
    nums = sorted(per_round.keys())
    if len(nums) >= 2:
        r0, r1 = resp_by_round[nums[0]], resp_by_round[nums[-1]]
        m0 = {r["participant_id"]: json.loads(r["answers"]) for r in r0}
        m1 = {r["participant_id"]: json.loads(r["answers"]) for r in r1}
        shared_pids = set.intersection(*[{p["id"] for p in rd["proposals"]} for rd in rounds]) if rounds else set()
        for prop in shared_pids:
            trans, moved = {}, 0
            for pt in set(m0) & set(m1):
                s0 = (m0[pt].get(prop) or {}).get("stance"); s1 = (m1[pt].get(prop) or {}).get("stance")
                if s0 and s1:
                    trans[f"{s0}->{s1}"] = trans.get(f"{s0}->{s1}", 0) + 1
                    if s0 != s1:
                        moved += 1
            if trans:
                movement[prop] = {"transitions": trans, "moved": moved}

    delibs = []
    for rd in rounds:
        for d in deliberations_for_round(rd["id"]):
            cur = d["current"] or {}
            delibs.append({"round": rd["round_no"], "title": cur.get("title"),
                           "reflects": cur.get("reflects", []), "tradeoffs": cur.get("tradeoffs", []),
                           "unaddressed": cur.get("unaddressed", []), "human_revised": bool(d.get("revisions")),
                           "approved_by": d.get("approved_by"),
                           "provenance": [f"{p.get('model')}({p.get('company')})" for p in d.get("provenance", [])],
                           "ai_original": d.get("ai_original")})

    # 비대표성 고지(G8) — 필수 요소, 제거 불가
    notice = (f"이 결과는 오늘 이 자리에 참여한 {composition['total']}명의 응답 패턴이며, "
              "확률표본이 아니어서 전체 국민의 여론(민의)을 대표하지 않습니다. "
              "가상 참여자는 엔진 검증용으로 별도 표기하며 대표성 판단에서 제외합니다.")
    moved_total = sum(m["moved"] for m in movement.values())
    conclusion = (f"참여자 {composition['total']}명(실제 {composition['human']}·가상 {composition['virtual']})이 "
                  f"{len(rounds)}개 회차에 응답했고, 회차 간 입장을 바꾼 연결은 {moved_total}건 관측됐습니다. "
                  f"AI 숙의로 {len(delibs)}개 추가 안이 생성·검토됐습니다.")
    return {"event_title": ev["title"], "composition": composition, "per_round": per_round,
            "movement": movement, "deliberations": delibs, "conclusion": conclusion,
            "non_representative_notice": notice}


def active_survey() -> dict | None:
    """진행 중(open)인 활성 회차를 시민 화면용 설문 형태로. 없으면 None."""
    with _conn() as c:
        ev = c.execute("SELECT * FROM events WHERE active_round_id IS NOT NULL "
                       "ORDER BY created_at DESC LIMIT 1").fetchone()
        if not ev:
            return None
        r = c.execute("SELECT * FROM rounds WHERE id=? AND status='open'", (ev["active_round_id"],)).fetchone()
        if not r:
            return None
        rd = _round_row(r)
    seg_key = next((f["key"] for f in rd["profile_fields"] if f.get("key") == "age"),
                   (rd["profile_fields"][0]["key"] if rd["profile_fields"] else ""))
    return {"round_id": rd["id"], "event_id": ev["id"], "segment_key": seg_key,
            "event_title": ev["title"], "round": rd["round_no"], "title": rd["title"],
            "intro": rd["intro"], "attachments": rd["attachments"],
            "proposals": rd["proposals"], "profile_fields": rd["profile_fields"]}
