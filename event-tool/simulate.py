"""합성 응답자 2회차 누적 스레드 검증 도구.

공개 합성 검증 설정:
- 합성 예제 프로필을 활성 모델에 배정해 1차 응답 생성
- 누적 스레드: 각 페르소나는 자기 대화 세션에서 진행(1차 입장 기억)
- 2차 = 동일 페르소나·동일 모델·동일 세션에 AI안 제시 후 재투표 → 동일인 유지
설계 §4 가상 응답자(검증용, 실제 여론 아님).
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
from pathlib import Path

import ai_config as CFG
import db
import deliberate as DELIB
import llm


def _gen_retry(model: dict, messages: list, tries: int = 5) -> str:
    """429/5xx rate-limit 대비 백오프 재시도."""
    for k in range(tries):
        try:
            return llm.chat(model, messages)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and k < tries - 1:
                time.sleep(5 * (k + 1)); continue
            raise
    raise RuntimeError("재시도 소진")


def _answer(model: dict, messages: list, ids: list[str], attempts: int = 4):
    """생성·JSON 추출·stance 검증까지 재시도하고 (raw, ans)를 반환."""
    last = None
    for k in range(attempts):
        try:
            raw = _gen_retry(model, messages)
            return raw, _fix(llm.extract_json(raw), ids)
        except Exception as e:  # 파싱 실패/stance 무효 → 재생성(온도로 변주)
            last = e; time.sleep(1)
    raise last or RuntimeError("응답 생성 실패")

BASE = Path(__file__).parent
PERSONAS = Path(os.environ.get("AIPOL_SYNTHETIC_PERSONAS_PATH", BASE / "fixtures" / "personas.example.json"))
# THREE(활성 독파모)는 main()에서 _load_env() 뒤에 계산 — 키 로드 후여야 정확.

PROPOSALS = json.loads((BASE / "fixtures" / "demo.json").read_text(encoding="utf-8"))["proposals"]
_SEG_AGE = {"youth": "20-30대", "middle": "40-50대", "senior": "60대+"}
_STANCES = ("accept", "conditional", "reject")


def _load_env():
    f = BASE / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _fix(ans: dict, ids: list[str]) -> dict:
    """응답 정규화. stance 미상/누락은 조용히 채우지 않고 실패시킴(분포·이동 조작 방지)."""
    out = {}
    for pid in ids:
        a = ans.get(pid) or {}
        st = str(a.get("stance", "")).strip().lower()
        if st not in _STANCES:
            raise ValueError(f"{pid} stance 무효: {st!r} — 제외(조용한 conditional 금지)")
        out[pid] = {"stance": st, "text": str(a.get("text", "")).strip()}
    return out


def _system(persona: dict) -> dict:
    return {"role": "system", "content":
            f"너는 국민연금 개혁 공론화에 참여한 다음 시민이다. 이 사람의 처지·이해관계에서만 판단하고, "
            f"안의 장점만이 아니라 네 입장에서의 단점·불신·부담도 솔직히 반영하라. 남들과 같게 답하지 말고 "
            f"네 상황에 맞게 갈라라.\n[프로필] {persona['profile']}"}


_STANCE_RULE = ("stance는 반드시 accept/conditional/reject 중 하나로 채워라(절대 비우지 말 것). "
                "text에는 그 입장의 짧은 이유.")


def _round1_user() -> dict:
    props = "\n".join(f"- {p['id']} {p['title']}: {p['body']}" for p in PROPOSALS)
    return {"role": "user", "content":
            f"[1차 의견수렴] 국민연금 개혁 전문가 안:\n{props}\n\n" + _STANCE_RULE + " "
            'JSON으로만(예시 형식): {"1안":{"stance":"conditional","text":"이유"},'
            '"2안":{"stance":"reject","text":"이유"},"3안":{"stance":"accept","text":"이유"}}'}


def _round2_user(ai_prop: dict) -> dict:
    return {"role": "user", "content":
            f"[2차 의견수렴] 1차 시민 의견을 모아 AI가 다음 통합 추가 안을 냈다:\n"
            f"■ ai안 {ai_prop.get('title','')}: {ai_prop.get('body','')}\n\n"
            "너는 1차에서 냈던 네 입장을 기억한다. 이제 원안 3개와 이 AI안까지 4개에 다시 입장을 정하라. "
            "1차와 달라졌으면 왜 바뀌었는지 이유에 적어라(안 바뀌어도 됨). " + _STANCE_RULE + " "
            'JSON으로만(예시 형식): {"1안":{"stance":"conditional","text":"이유"},"2안":{"stance":"reject","text":"이유"},'
            '"3안":{"stance":"accept","text":"이유"},"ai안":{"stance":"accept","text":"이유"}}'}


def main():
    _load_env()
    global THREE
    THREE = CFG.active_dokpamo()
    if len(THREE) < CFG.MIN_DRAFTER_COMPANIES:
        print(f"활성 독파모 {len(THREE)}<{CFG.MIN_DRAFTER_COMPANIES} — 3번째 독파모(A.X/HCX) 키 필요. 중단.", flush=True)
        return
    personas = json.loads(PERSONAS.read_text(encoding="utf-8"))
    if isinstance(personas, dict):
        personas = personas.get("personas", [])
    ev = db.create_event("공개 합성 정책 의견수렴 예제", "합성 프로필 누적 스레드 — 실제 여론 아님")
    rd1 = db.create_round(ev["id"], round_no=1, title="1차 의견수렴", proposals=PROPOSALS,
                          profile_fields=[{"key": "age", "label": "연령대", "type": "select"}])
    db.update_round(rd1["id"], status="open"); db.set_active_round(ev["id"], rd1["id"])
    print(f"행사={ev['id']} 1차={rd1['id']} 페르소나={len(personas)}", flush=True)

    # ── 1차: 독파모 3사 랜덤, 누적 스레드 시작 ──
    state = {}  # pid -> {code, model, messages}
    ok = 0
    for i, p in enumerate(personas, 1):
        # 랜덤 배정 + 폴백: 배정 모델 실패 시 다른 활성 모델로 시도
        order = random.sample(THREE, len(THREE))
        saved = False
        for m in order:
            msgs = [_system(p), _round1_user()]
            try:
                raw, ans = _answer(m, msgs, ["1안", "2안", "3안"])
            except Exception as e:
                print(f"  [1차 {i}] {p.get('id')} {m['label']} 실패({type(e).__name__}) → 폴백", flush=True)
                continue
            profile = {"age": _SEG_AGE.get(p.get("segment", "middle"), "40-50대"),
                       "persona_id": p.get("id"), "gen_model": f"{m['label']}({m['company']})",
                       "persona": p.get("profile", "")}  # AI의 '개인정보'=페르소나 전문(누가·어떻게 움직였나)
            out = db.save_response(rd1["id"], None, profile, ans, segment_key="age", kind="virtual")
            msgs.append({"role": "assistant", "content": raw})
            state[p["id"]] = {"code": out["code"], "model": m, "messages": msgs, "profile": profile}
            ok += 1; saved = True
            break
        if not saved:
            print(f"  [1차 {i}] {p.get('id')} 전 독파모 실패 — 제외", flush=True)
        if i % 20 == 0:
            print(f"  1차 진행 {i}/{len(personas)} (성공 {ok})", flush=True)
    print(f"1차 완료: 성공 {ok}", flush=True)

    # ── 마감 → AI 숙의 → 승인 → 2차 설문(원안+AI안) ──
    db.update_round(rd1["id"], status="closed")
    print("AI 숙의 실행(독파모 교차)…", flush=True)
    job = db.create_job(rd1["id"])
    DELIB.run_job(job["id"], rd1["id"])
    dls = db.deliberations_for_round(rd1["id"])
    if not dls:
        print("숙의 실패 — 중단"); return
    dl = dls[0]
    db.approve_deliberation(dl["id"], "운영자")
    rd2 = db.to_next_round(dl["id"], 2)
    db.update_round(rd2["id"], status="open"); db.set_active_round(ev["id"], rd2["id"])
    ai_prop = next((p for p in rd2["proposals"] if p["id"] == "ai안"), {})
    print(f"2차={rd2['id']} AI안='{ai_prop.get('title','')}'", flush=True)

    # ── 2차: 동일 페르소나·동일 모델·동일 세션(누적 스레드) 재투표 ──
    ok2 = 0
    ids2 = ["1안", "2안", "3안", "ai안"]
    for i, p in enumerate(personas, 1):
        s = state.get(p["id"])
        if not s:
            continue  # 1차 실패자는 2차도 제외(동일인 유지)
        s["messages"].append(_round2_user(ai_prop))
        try:
            raw, ans = _answer(s["model"], s["messages"], ids2, attempts=6)  # 동일모델 유지·재시도 강화
            db.save_response(rd2["id"], s["code"], s["profile"], ans, segment_key="age", kind="virtual")
            s["messages"].append({"role": "assistant", "content": raw})
            ok2 += 1
        except Exception as e:
            print(f"  [2차 {i}] {p.get('id')} 실패: {type(e).__name__}", flush=True)
        if i % 20 == 0:
            print(f"  2차 진행 {i}/{len(personas)} (성공 {ok2})", flush=True)
    print(f"2차 완료: 성공 {ok2} / event={ev['id']} 1차={rd1['id']} 2차={rd2['id']}", flush=True)
    # 스레드 보존(감사·재현)
    (BASE / "sim_threads.json").write_text(
        json.dumps({pid: {"code": s["code"], "model": s["model"]["label"], "messages": s["messages"]}
                    for pid, s in state.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("스레드 저장: sim_threads.json", flush=True)


if __name__ == "__main__":
    main()
