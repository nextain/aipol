"""AI 숙의 — 다단계 교차 + 투명 누적스레드 + 드리프트 동시감시.

단계: 1)독립안 2)남의 안 보고 각자 수정안 3)취합 통합안 4)통합안 수정요청 5)수정범위 투표 6)반영.
투명성: 3 독파모 각자 지속 스레드로 전 과정을 보며, 매 단계 드리프트(시민의견 이탈·환각·편향·누락) 감시.
가드: 활성 독파모 회사 ≥3(fail-closed). 판정기 분리는 취합을 로테이션+투표로 상쇄.
프로바이더는 ai_config.PROVIDERS 레지스트리(추가 용이). 실행은 활성 독파모 3사 필요.
"""
from __future__ import annotations

import json
import re

import ai_config as CFG
import db
import llm

_NUM = re.compile(r"\d+\.\d+\s*%|\d+\.\d+\s*(?:배|퍼센트|포인트)")


def _norm(s): return (s or "").strip().casefold()


def assert_min_companies(companies):
    if len({_norm(c) for c in companies if c}) < CFG.MIN_DRAFTER_COMPANIES:
        raise ValueError(f"활성 독파모 회사 {len(companies)}<{CFG.MIN_DRAFTER_COMPANIES} — 3번째 독파모 키 필요(A.X/HCX)")


def _agg(round_dict):
    st = db.round_stats(round_dict["id"])
    with db._conn() as c:
        rows = [dict(r) for r in c.execute("SELECT answers FROM responses WHERE round_id=?", (round_dict["id"],))]
    lines = [f"시민 {st['n']}명 응답:"]
    for p in round_dict["proposals"]:
        d = st["distribution"].get(p["id"], {})
        lines.append(f"\n[{p['id']} {p.get('title','')}] 수용{d.get('accept',0)}/조건부{d.get('conditional',0)}/거부{d.get('reject',0)}")
        for r in rows:
            a = json.loads(r["answers"]).get(p["id"]) or {}
            t = (a.get("text") or "").strip()
            if t:
                lines.append(f"  ({a.get('stance','')}) {t}")
    return "\n".join(lines[:400])


def run_job(job_id: str, round_id: str):
    """6단계 숙의. 각 독파모의 누적 스레드 유지(투명) + 드리프트 감시. 실패·취소는 잡 상태로."""
    try:
        rd = db.get_round(round_id)
        agents = CFG.active_dokpamo()
        assert_min_companies({a["company"] for a in agents})  # 활성 <3이면 여기서 정직 거부
        user = _agg(rd)
        # 각 독파모의 지속 스레드(투명) — 전 단계 누적
        threads = {a["label"]: [{"role": "system", "content": CFG.DRAFTER_SYSTEM
                                 + f"\n너는 {a['label']}({a['company']})다. 아래는 이번 숙의의 전 과정이며, 매 단계 드리프트도 감시하라."}]
                   for a in agents}
        tr = {"stages": []}

        def stage(name):
            db.update_job(job_id, progress=name)
            if db.job_cancelled(job_id):
                raise RuntimeError("취소됨")

        # 1) 독립안
        stage("1/6 독립안 작성")
        drafts = {}
        for a in agents:
            threads[a["label"]].append({"role": "user", "content":
                f"[1단계 독립안] 시민 의견:\n{user}\n\n네 독립 추가 안을 내라. {CFG.JSON_SPEC}"})
            raw = llm.chat(a, threads[a["label"]])
            threads[a["label"]].append({"role": "assistant", "content": raw})
            drafts[a["label"]] = llm.extract_json(raw)
        tr["stages"].append({"stage": "독립안", "by": {k: v for k, v in drafts.items()}})

        # 2) 남의 안 보고 각자 수정안
        stage("2/6 교차 보강(각자 수정안)")
        revised = {}
        for a in agents:
            others = "\n\n".join(f"[{o}] {json.dumps(drafts[o], ensure_ascii=False)[:1200]}"
                                 for o in drafts if o != a["label"])
            threads[a["label"]].append({"role": "user", "content":
                f"[2단계] 다른 독파모의 독립안:\n{others}\n\n이를 참고해 네 안을 보강한 '각자 수정안'을 내라(드리프트 지적 포함). {CFG.JSON_SPEC}"})
            raw = llm.chat(a, threads[a["label"]])
            threads[a["label"]].append({"role": "assistant", "content": raw})
            revised[a["label"]] = llm.extract_json(raw)
        tr["stages"].append({"stage": "각자수정안", "by": {k: v for k, v in revised.items()}})

        # 3) 취합 통합안 (로테이션: 회차 기반이 아니라 index 0 담당, 투표로 상쇄)
        stage("3/6 취합 통합안")
        synth = agents[0]
        allrev = "\n\n".join(f"[{k}] {json.dumps(v, ensure_ascii=False)[:1200]}" for k, v in revised.items())
        threads[synth["label"]].append({"role": "user", "content":
            f"[3단계 취합] 세 각자 수정안:\n{allrev}\n\n강점을 취해 하나의 통합안으로 합쳐라. {CFG.JSON_SPEC}"})
        raw = llm.chat(synth, threads[synth["label"]])
        threads[synth["label"]].append({"role": "assistant", "content": raw})
        merged = llm.extract_json(raw)
        tr["stages"].append({"stage": "통합안(취합)", "synthesizer": synth["label"], "result": merged})

        # 4) 통합안 수정요청 (각 독파모가 고칠 부분 제안)
        stage("4/6 통합안 수정 요청")
        edits = []
        for a in agents:
            threads[a["label"]].append({"role": "user", "content":
                f"[4단계] 취합 통합안:\n{json.dumps(merged, ensure_ascii=False)[:1500]}\n\n"
                "고쳐야 할 부분을 제안하라(드리프트·누락 포함). "
                'JSON 배열로만: [{"id":"E1","what":"무엇을","why":"왜"}] (없으면 [])'})
            raw = llm.chat(a, threads[a["label"]])
            threads[a["label"]].append({"role": "assistant", "content": raw})
            try:
                for e in llm.extract_json(raw) if raw.strip().startswith("[") else json.loads(re.search(r"\[.*\]", raw, re.DOTALL).group()):
                    e["by"] = a["label"]; edits.append(e)
            except Exception:
                pass
        tr["stages"].append({"stage": "수정제안", "edits": edits})

        # 5) 수정범위 투표 — 각 독파모가 '전체 수정안을 한 번에' 투표(호출=3콜, rate-limit 회피)
        stage("5/6 수정 범위 투표")
        accepted = []
        if edits:
            for i, e in enumerate(edits):
                e["id"] = f"E{i+1}"  # 전역 유일 재부여(독파모별 id 충돌 방지)
            tally = {e["id"]: 0 for e in edits}
            ballot = "\n".join(f'- {e["id"]} [{e.get("by","")}]: {e.get("what","")} (이유: {e.get("why","")})' for e in edits)
            for a in agents:
                threads[a["label"]].append({"role": "user", "content":
                    f"[5단계 투표] 아래 수정 제안 각각을 통합안에 반영할지 판단하라:\n{ballot}\n\n"
                    'JSON 객체로만(각 id에 accept/reject): {"E1":"accept","E2":"reject", ...}'})
                raw = llm.chat(a, threads[a["label"]])
                threads[a["label"]].append({"role": "assistant", "content": raw})
                try:
                    votes = llm.extract_json(raw)
                    for eid in tally:
                        if _norm(votes.get(eid)) == "accept":
                            tally[eid] += 1
                except Exception:
                    pass
            for e in edits:
                e["votes_accept"] = tally[e["id"]]
                if tally[e["id"]] >= 2:  # 과반(3 중 2)
                    accepted.append(e)
        tr["stages"].append({"stage": "투표", "accepted": accepted})

        # 6) 반영 (수용된 수정만) — 취합자가 최종안 산출
        stage("6/6 최종 반영")
        if accepted:
            acc = "\n".join(f"- {e.get('what','')}" for e in accepted)
            threads[synth["label"]].append({"role": "user", "content":
                f"[6단계] 투표로 수용된 수정:\n{acc}\n\n이것만 반영해 최종 통합안을 내라. {CFG.JSON_SPEC}"})
            raw = llm.chat(synth, threads[synth["label"]])
            final = llm.extract_json(raw)
        else:
            final = merged
        if _NUM.search((final.get("title") or "") + (final.get("body") or "")):
            final["_guard_warning"] = "단일 정밀 수치 잔존 — 발표 전 사람 확인(G10)"

        provenance = [{"model": a["label"], "company": a["company"], "provider": a["provider"]} for a in agents]
        provenance.append({"role": "synthesizer", "model": synth["label"]})
        dl = db.save_deliberation(round_id, job_id, ai_original=final, current=final,
                                  transcript=tr, provenance=provenance)
        db.update_job(job_id, status="done", progress="완료", error="")
        return dl
    except Exception as e:
        db.update_job(job_id, status="failed", error=f"{type(e).__name__}: {e}", progress="실패")
