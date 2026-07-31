/* 진행자 어드민 — 2단계: (1)행사 목록 → (2)행사 작업공간(좌측 단계 네비).
   숙의 회의과정을 독립 단계로 드러냄. 긴 세로 스크롤 대신 단계별 섹션. */
"use strict";
let TOKEN = sessionStorage.getItem("admtok") || "";
let EVENTS = [];
const WS = { ev: null, section: "overview", roundId: null };

const $ = (id) => document.getElementById(id);
const H = () => ({ "Content-Type": "application/json", "X-Admin-Token": TOKEN });
async function api(path, opt = {}) {
  const r = await fetch(path, { headers: H(), ...opt });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
  return r.status === 204 ? {} : r.json();
}
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STANCE_KO = { accept: "수용", conditional: "조건부", reject: "거부" };
const ST_LABEL = { draft: "준비중", open: "수집중", closed: "마감" };
const setErr = (m) => { $("err").textContent = m || ""; };

// ── 로그인 ──
async function login() {
  const username = $("user").value, pw = $("pw").value, otp = $("otp").value;
  try {
    const response = await fetch("/api/admin/login", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password: pw, otp }) });
    const d = await response.json();
    if (!response.ok) throw 0;
    if (!d.ok) throw 0;
    TOKEN = d.token; sessionStorage.setItem("admtok", TOKEN);
    enterDash();
  } catch (e) { $("login-err").textContent = "아이디 또는 비밀번호를 확인해 주세요"; }
}
$("pw").addEventListener("keydown", (e) => { if (e.key === "Enter") login(); });
async function enterDash() {
  $("login").classList.add("hidden"); $("dash").classList.remove("hidden");
  await loadEvents(); showEventsView();
}
function logout() { sessionStorage.removeItem("admtok"); location.reload(); }

// ── 1단계: 행사 목록 ──
function showEventsView() {
  $("view-workspace").classList.add("hidden");
  $("view-agents").classList.add("hidden");
  $("view-events").classList.remove("hidden");
  WS.ev = null;
}
async function loadEvents() {
  try { EVENTS = await api("/api/admin/events"); }
  catch (e) { logout(); return; }
  const box = $("event-cards"); box.innerHTML = "";
  if (!EVENTS.length) { box.innerHTML = `<p class="hint">아직 행사가 없습니다. 아래에서 만드세요.</p>`; return; }
  EVENTS.forEach((ev) => {
    const nOpen = ev.rounds.filter((r) => r.status === "open").length;
    const card = document.createElement("div");
    card.className = "ev-card";
    card.innerHTML = `
      <div class="ev-main">
        <div class="ev-title">${esc(ev.title)}</div>
        <div class="ev-meta">${ev.rounds.length}개 회차${nOpen ? ` · <b class="live">수집중 ${nOpen}</b>` : ""}${ev.context ? ` · ${esc(ev.context)}` : ""}</div>
      </div>
      <div class="ev-btns">
        <button class="btn-primary" data-act="open">열기 →</button>
        <button class="btn-mini danger" data-act="del">삭제</button>
      </div>`;
    card.querySelector('[data-act="open"]').onclick = () => openWorkspace(ev.id);
    card.querySelector('[data-act="del"]').onclick = async () => {
      if (!confirm(`'${ev.title}' 행사를 삭제할까요? 회차·응답·숙의 결과가 모두 지워집니다(되돌릴 수 없음).`)) return;
      try { await api(`/api/admin/events/${ev.id}`, { method: "DELETE" }); await loadEvents(); }
      catch (e) { setErr(e.message); }
    };
    box.appendChild(card);
  });
}

// ── 2단계: 작업공간 진입 ──
async function openWorkspace(evId) {
  await loadEvents();
  WS.ev = EVENTS.find((e) => e.id === evId);
  if (!WS.ev) { showEventsView(); return; }
  WS.roundId = null;
  $("view-events").classList.add("hidden");
  $("view-agents").classList.add("hidden");
  $("view-workspace").classList.remove("hidden");
  $("ws-title").textContent = WS.ev.title;
  setSection("overview");
}
async function refreshWs() {  // 서버 상태 재조회 후 현재 섹션 재렌더
  await loadEvents();
  WS.ev = EVENTS.find((e) => e.id === WS.ev.id) || WS.ev;
  setSection(WS.section);
}
function setSection(name) {
  WS.section = name;
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.sec === name));
  const c = $("ws-content"); c.innerHTML = "";
  ({ overview: renderOverview, rounds: renderRoundsSec, collect: renderCollectSec,
     delib: renderDelibSec, people: renderPeopleSec, report: renderReportSec }[name] || renderOverview)(c);
}

// 회차 선택 드롭다운(수집·숙의 공용)
function roundPicker(c, onPick, filter) {
  let rounds = (WS.ev.rounds || []);
  if (filter) rounds = rounds.filter(filter);
  if (!rounds.length) { c.innerHTML = `<p class="hint">해당하는 회차가 없습니다. '회차'에서 먼저 준비·공개하세요.</p>`; return null; }
  if (!WS.roundId || !rounds.find((r) => r.id === WS.roundId)) WS.roundId = rounds[rounds.length - 1].id;
  const bar = document.createElement("div"); bar.className = "round-pick";
  bar.innerHTML = `<label>회차</label><select id="rp-sel">${rounds.map((r) =>
    `<option value="${r.id}" ${r.id === WS.roundId ? "selected" : ""}>${r.round_no}차 — ${esc(r.title)} (${ST_LABEL[r.status]})</option>`).join("")}</select>`;
  c.appendChild(bar);
  bar.querySelector("#rp-sel").onchange = (e) => { WS.roundId = e.target.value; onPick(); };
  return rounds.find((r) => r.id === WS.roundId);
}

// ── 섹션: 개요 ──
async function renderOverview(c) {
  const ev = WS.ev;
  const rounds = ev.rounds || [];
  const cur = rounds.find((r) => r.status === "open") || rounds[rounds.length - 1];
  const step = cur ? (cur.status === "open" ? "수집" : "AI 숙의/승인") : "준비";
  let nParts = "…";
  try { nParts = (await api(`/api/admin/events/${ev.id}/participants`)).length; } catch (e) { nParts = "0"; }
  c.innerHTML = `
    <div class="timeline big">
      ${["준비", "수집", "AI 숙의", "승인", "보고서"].map((s, i) =>
        `<span class="step ${s === step || (step==="AI 숙의/승인" && (s==="AI 숙의"||s==="승인")) ? "done" : ""}">${s}</span>`
        + (i < 4 ? `<span class="sep">→</span>` : "")).join("")}
    </div>
    <div class="ov-cards">
      <div class="ov-card"><div class="ov-n">${rounds.length}</div><div class="ov-l">회차</div></div>
      <div class="ov-card"><div class="ov-n">${nParts}</div><div class="ov-l">응답자</div></div>
      <div class="ov-card"><div class="ov-n">${step}</div><div class="ov-l">지금 단계</div></div>
    </div>
    <div class="ov-guide">
      <b>다음 할 일</b>
      <p class="hint">${cur ? (cur.status === "draft" ? "‘회차’에서 안을 준비하고 공개하세요."
        : cur.status === "open" ? "‘수집 현황’에서 응답을 지켜보고, 충분하면 마감 후 ‘AI 숙의’를 실행하세요."
        : "‘AI 숙의’에서 통합안을 검토·승인하고 다음 회차로 넘기세요.")
        : "‘회차’에서 1차 회차를 만들어 시작하세요."}</p>
    </div>
    <div class="ov-edit">
      <button class="btn-mini" id="ev-edit-toggle">✎ 행사 이름·맥락 수정</button>
      <div id="ev-edit-form" class="hidden">
        <div class="f-row"><label>행사 제목</label><input type="text" id="ev-e-title" value="${esc(ev.title)}"></div>
        <div class="f-row"><label>맥락(선택)</label><input type="text" id="ev-e-ctx" value="${esc(ev.context || "")}"></div>
        <div class="form-actions"><button class="btn-primary" id="ev-e-save">저장</button>
          <button class="btn-secondary" id="ev-e-cancel">취소</button></div>
      </div>
    </div>`;
  $("ev-edit-toggle").onclick = () => $("ev-edit-form").classList.toggle("hidden");
  $("ev-e-cancel").onclick = () => $("ev-edit-form").classList.add("hidden");
  $("ev-e-save").onclick = async () => {
    try { await api(`/api/admin/events/${ev.id}`, { method: "PATCH",
      body: JSON.stringify({ title: $("ev-e-title").value, context: $("ev-e-ctx").value }) });
      await loadEvents(); WS.ev = EVENTS.find((e) => e.id === ev.id) || WS.ev;
      $("ws-title").textContent = WS.ev.title; setSection("overview"); }
    catch (e) { setErr(e.message); }
  };
}

// ── 섹션: 회차 (준비/편집/공개/마감/삭제) ──
function renderRoundsSec(c) {
  const ev = WS.ev;
  const list = document.createElement("div"); list.className = "round-list"; c.appendChild(list);
  ev.rounds.forEach((rd) => {
    const div = document.createElement("div"); div.className = "rd-row";
    div.innerHTML = `<span class="t">${rd.round_no}회차 — ${esc(rd.title)}</span>
      <span class="hint">안 ${rd.proposals.length}</span>
      <span class="pill ${rd.status}">${ST_LABEL[rd.status]}</span>
      <span class="rd-actions">
        <button class="btn-mini" data-act="edit">${rd.status === "draft" ? "준비/편집" : "내용"}</button>
        ${rd.status === "draft" ? `<button class="btn-mini" data-act="open">공개(수집 시작)</button>` : ""}
        ${rd.status === "open" ? `<button class="btn-mini danger" data-act="close">마감</button>` : ""}
        <button class="btn-mini danger" data-act="del">삭제</button>
      </span>`;
    div.querySelector('[data-act="edit"]').onclick = () => openForm(rd);
    const ob = div.querySelector('[data-act="open"]'); if (ob) ob.onclick = () => setStatus(rd, "open");
    const cb = div.querySelector('[data-act="close"]'); if (cb) cb.onclick = async () => {
      if (!confirm(`${rd.round_no}회차 수집을 마감할까요? 시민이 더 응답할 수 없습니다.`)) return;
      setStatus(rd, "closed");
    };
    div.querySelector('[data-act="del"]').onclick = async () => {
      if (!confirm(`${rd.round_no}회차를 삭제할까요? 응답·숙의가 함께 지워집니다.`)) return;
      try { await api(`/api/admin/rounds/${rd.id}`, { method: "DELETE" }); await refreshWs(); }
      catch (e) { setErr(e.message); }
    };
    list.appendChild(div);
  });
  const add = document.createElement("button"); add.className = "btn-secondary"; add.textContent = "+ 회차 추가";
  add.onclick = () => openForm({ new: true, round_no: ev.rounds.length + 1 });
  c.appendChild(add);
  const formBox = document.createElement("div"); formBox.id = "prep-form"; formBox.className = "hidden"; c.appendChild(formBox);
}
async function setStatus(rd, status) {
  try { await api(`/api/admin/rounds/${rd.id}/status`, { method: "POST", body: JSON.stringify({ status }) }); await refreshWs(); }
  catch (e) { setErr(e.message); }
}

// ── 섹션: 수집 현황 ──
async function renderCollectSec(c) {
  c.innerHTML = "";
  const rd = roundPicker(c, () => renderCollectSec($("ws-content")), (r) => r.status !== "draft");
  if (!rd) return;
  const panel = document.createElement("div"); panel.className = "collect-panel"; c.appendChild(panel);
  panel.innerHTML = `<p class="hint">불러오는 중…</p>`;
  let s;
  try { s = await api(`/api/admin/rounds/${rd.id}/stats`); }
  catch (e) { panel.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  if (!panel.isConnected) return;  // 전환됨 → stale 폐기
  const bar = (d) => { const t = d.accept + d.conditional + d.reject || 1;
    const seg = (n, cls) => n ? `<span class="seg ${cls}" style="width:${(n / t * 100).toFixed(1)}%">${n}</span>` : "";
    return `<div class="dist">${seg(d.accept, "a")}${seg(d.conditional, "c")}${seg(d.reject, "r")}</div>`; };
  panel.innerHTML = `
    <div class="stats-head"><b>${rd.round_no}회차 수집 현황</b>
      <span class="pill ${rd.status}">${ST_LABEL[rd.status]}</span>
      <span class="big-n">${s.n}<span class="hint"> 명 응답</span></span>
      <button class="btn-mini" id="stats-refresh">새로고침</button></div>
    ${s.n === 0 ? `<p class="hint">아직 응답이 없습니다.</p>` : `
    <div class="legend"><span class="dot a"></span>수용 <span class="dot c"></span>조건부 <span class="dot r"></span>거부</div>
    ${(rd.proposals || []).map((p) => `<div class="dist-row"><div class="dist-label">${esc(p.title || p.id)}</div>
       ${bar(s.distribution[p.id] || { accept: 0, conditional: 0, reject: 0 })}</div>`).join("")}
    <div class="seg-summary"><b>연령대</b> ${Object.entries(s.by_segment).map(([k, v]) => `${esc(k)} ${v}`).join(" · ") || "—"}</div>`}
    ${rd.status === "open" ? `<div class="mt"><button class="btn-mini danger" id="close-here">이 회차 마감</button>
      <span class="hint">마감 후 ‘AI 숙의’ 단계로.</span></div>` : ""}`;
  $("stats-refresh").onclick = () => renderCollectSec($("ws-content"));
  if ($("close-here")) $("close-here").onclick = async () => { if (confirm("마감할까요?")) setStatus(rd, "closed"); };
}

// ── 섹션: AI 숙의 (회의 과정을 메인으로) ──
async function renderDelibSec(c) {
  c.innerHTML = "";
  const rd = roundPicker(c, () => renderDelibSec($("ws-content")), (r) => r.status !== "draft");
  if (!rd) return;
  const panel = document.createElement("div"); panel.id = "delib-panel"; c.appendChild(panel);
  panel.innerHTML = `<p class="hint">불러오는 중…</p>`;
  let dls = [];
  try { dls = await api(`/api/admin/rounds/${rd.id}/deliberations`); } catch (e) {}
  if ($("delib-panel") !== panel) return;  // 회차 빠르게 전환됨 → stale 렌더 폐기
  if (!dls.length) {
    panel.innerHTML = `<div class="delib-empty">
      <p>이 회차는 아직 AI 숙의를 실행하지 않았습니다.</p>
      <p class="hint">독파모 3사(EXAONE·Solar·HCX)가 시민 의견을 놓고 6단계 회의(독립안→각자수정안→취합→수정요청→투표→최종)를 거쳐 통합안을 만듭니다.</p>
      <button class="btn-primary" id="run-delib">AI 숙의 실행</button></div>`;
    $("run-delib").onclick = () => runDeliberation(rd);
    return;
  }
  renderDeliberation(dls[0], rd);
}
async function runDeliberation(rd) {
  const panel = $("delib-panel");
  panel.innerHTML = `<div class="job-run"><span class="spinner-sm"></span><span id="job-prog">숙의 시작…</span>
    <button class="btn-mini danger" id="job-cancel">취소</button></div>
    <p class="hint">6단계 회의가 순차로 진행됩니다(수 분 소요).</p>`;
  let job;
  try { job = await api(`/api/admin/rounds/${rd.id}/deliberate`, { method: "POST" }); }
  catch (e) { panel.innerHTML = `<p class="err">${esc(e.message)}</p><button class="btn-secondary" id="retry-delib">다시</button>`;
    $("retry-delib").onclick = () => runDeliberation(rd); return; }
  $("job-cancel").onclick = () => api(`/api/admin/jobs/${job.id}/cancel`, { method: "POST" }).catch(() => {});
  pollDelib(job.id, rd);
}
async function pollDelib(jid, rd) {
  let j; try { j = await api(`/api/admin/jobs/${jid}`); } catch (e) { return; }
  if (j.status === "running") { const p = $("job-prog"); if (p) p.textContent = j.progress || "진행 중…"; setTimeout(() => pollDelib(jid, rd), 2000); return; }
  if (j.status === "failed") { $("delib-panel").innerHTML = `<p class="err">숙의 실패: ${esc(j.error)}</p><button class="btn-secondary" id="retry-delib">다시 시도</button>`; $("retry-delib").onclick = () => runDeliberation(rd); return; }
  if (j.status === "cancelled") { renderDelibSec($("ws-content")); return; }
  if (j.status === "done") renderDelibSec($("ws-content"));
}

function renderDeliberation(dl, rd) {
  const cur = dl.current || {};
  const list = (arr) => (arr && arr.length) ? arr.map((x) => `<li>${esc(typeof x === "string" ? x : (x.text || JSON.stringify(x)))}</li>`).join("") : "<li class='hint'>—</li>";
  const prov = (dl.provenance || []).map((p) => `${esc(p.model)}${p.company ? `(${esc(p.company)})` : ""}${p.role ? "·취합" : ""}`).join(" · ");
  const revised = (dl.revisions || []).length > 0;
  const approved = !!dl.approved_by;
  $("delib-panel").innerHTML = `
    <div class="delib-wrap">
      <h3 class="sec-h">이 숙의가 거친 회의 (독파모 3사, 6단계)</h3>
      <p class="hint">참여 AI: ${esc(prov)}</p>
      <div class="tr-flow">${renderTranscript(dl.transcript)}</div>

      <h3 class="sec-h">결과 — AI 통합 추가 안</h3>
      <div class="ai-card">
        ${cur._guard_warning ? `<div class="guard-warn">⚠ ${esc(cur._guard_warning)}</div>` : ""}
        <div class="ai-status">
          ${revised ? `<span class="badge-rev">사람이 수정함 (${dl.revisions.length}회)</span>` : ""}
          ${approved ? `<span class="badge-ok">✔ 승인: ${esc(dl.approved_by)}</span>` : `<span class="badge-pend">미승인 — 검토 필요</span>`}
        </div>
        <h3>${esc(cur.title || "제목 없음")}</h3>
        <p>${esc(cur.body || "")}</p>
        <div class="grounds">
          <div><b class="g-a">반영한 의견</b><ul>${list(cur.reflects)}</ul></div>
          <div><b class="g-c">감수한 트레이드오프</b><ul>${list(cur.tradeoffs)}</ul></div>
          <div><b class="g-r">반영 못 한 의견(정직)</b><ul>${list(cur.unaddressed)}</ul></div>
        </div>
        <div class="ai-actions">
          <button class="btn-secondary" id="revise-btn">✎ 사람 수정 / 전문가회의 보강</button>
          ${!approved ? `<button class="btn-primary" id="approve-btn">승인</button>`
            : `<button class="btn-primary" id="tonext-btn">→ 이 안을 다음 회차 설문으로</button>`}
        </div>
        <div id="revise-form" class="hidden"></div>
      </div>
    </div>`;
  $("revise-btn").onclick = () => openReviseForm(dl, rd);
  if ($("approve-btn")) $("approve-btn").onclick = async () => {
    try { await api(`/api/admin/deliberations/${dl.id}/approve`, { method: "POST" }); await refreshWs(); }
    catch (e) { setErr(e.message); }
  };
  if ($("tonext-btn")) $("tonext-btn").onclick = async () => {
    const nextNo = (Math.max(...WS.ev.rounds.map((r) => r.round_no)) || 1) + 1;
    if (!confirm(`${nextNo}차 설문을 만들까요? 원안 + 승인된 AI안이 함께 들어갑니다.`)) return;
    try { await api(`/api/admin/deliberations/${dl.id}/to_next_round`, { method: "POST", body: JSON.stringify({ next_round_no: nextNo }) });
      await loadEvents(); WS.ev = EVENTS.find((e) => e.id === WS.ev.id); WS.roundId = null; setSection("rounds");
      alert(`${nextNo}차 설문이 만들어졌습니다. ‘회차’에서 공개하세요.`); }
    catch (e) { setErr(e.message); }
  };
}

function openReviseForm(dl) {
  const cur = dl.current || {};
  const f = $("revise-form"); f.classList.remove("hidden");
  f.innerHTML = `
    <div class="rev-box">
      <b>사람 수정 / 전문가회의 보강</b> <span class="hint">저장 시 수정이력 기록 + 승인 무효화(재승인 필요)</span>
      <div class="row2">
        <div class="f-row"><label>수정자</label><span class="hint">로그인한 개인 계정으로 자동 기록</span></div>
        <div class="f-row"><label>구분</label><select id="rv-source"><option>개인수정</option><option>전문가회의</option></select></div>
      </div>
      <div class="f-row"><label>사유</label><input type="text" id="rv-reason" placeholder="왜 수정하는지"></div>
      <div id="rv-meeting" class="hidden">
        <div class="row2"><div class="f-row"><label>회의 참석자</label><input type="text" id="rv-att"></div>
        <div class="f-row"><label>승인자</label><input type="text" id="rv-appr"></div></div>
        <div class="f-row"><label>회의 근거</label><input type="text" id="rv-basis"></div>
      </div>
      <div class="f-row"><label>제목</label><input type="text" id="rv-title" value="${esc(cur.title || "")}"></div>
      <div class="f-row"><label>본문</label><textarea id="rv-body">${esc(cur.body || "")}</textarea></div>
      <div class="form-actions"><button class="btn-primary" id="rv-save">수정 저장</button>
        <button class="btn-secondary" id="rv-cancel">취소</button></div>
    </div>`;
  $("rv-source").onchange = (e) => $("rv-meeting").classList.toggle("hidden", e.target.value !== "전문가회의");
  $("rv-cancel").onclick = () => f.classList.add("hidden");
  $("rv-save").onclick = async () => {
    const src = $("rv-source").value;
    const payload = { source: src, reason: $("rv-reason").value,
      title: $("rv-title").value, body: $("rv-body").value };
    if (src === "전문가회의") payload.meeting = { attendees: $("rv-att").value, approver: $("rv-appr").value, basis: $("rv-basis").value };
    try { await api(`/api/admin/deliberations/${dl.id}/revise`, { method: "POST", body: JSON.stringify(payload) }); await refreshWs(); }
    catch (e) { setErr(e.message); }
  };
}

// 숙의 6단계 회의 과정을 사람이 읽는 형태로
function renderTranscript(tr) {
  if (!tr || !tr.stages || !tr.stages.length) return `<p class="hint">과정 기록 없음</p>`;
  const prop = (p) => {
    if (!p || typeof p !== "object") return `<span class="hint">—</span>`;
    const cnt = (a) => (a && a.length) ? a.length : 0;
    return `<div class="tr-prop"><b>${esc(p.title || "제목 없음")}</b><p>${esc(p.body || "")}</p>
      <span class="hint">반영 ${cnt(p.reflects)} · 트레이드오프 ${cnt(p.tradeoffs)} · 미반영 ${cnt(p.unaddressed)}</span></div>`;
  };
  const step = { "독립안": "1", "각자수정안": "2", "통합안(취합)": "3", "수정제안": "4", "투표": "5" };
  const label = { "독립안": "독립안 — 3사가 각자 작성", "각자수정안": "각자 수정안 — 다른 안 보고 보강",
    "통합안(취합)": "취합 통합안", "수정제안": "수정 요청 — 고칠 부분", "투표": "수정범위 투표 (3중 2 수용)" };
  return tr.stages.map((s) => {
    const n = step[s.stage] || "";
    let inner = "";
    if (s.by) inner = Object.entries(s.by).map(([who, p]) => `<div class="tr-agent"><span class="tr-who">${esc(who)}</span>${prop(p)}</div>`).join("");
    else if (s.stage === "통합안(취합)") inner = `<p class="hint">취합자: ${esc(s.synthesizer)}</p>${prop(s.result)}`;
    else if (s.stage === "수정제안") inner = (s.edits || []).length
      ? `<ul class="tr-edits">${s.edits.map((e) => `<li><span class="tr-who">${esc(e.by || "")}</span> ${esc(e.what || "")}${e.why ? ` <span class="hint">— ${esc(e.why)}</span>` : ""}</li>`).join("")}</ul>`
      : `<p class="hint">수정 제안 없음</p>`;
    else if (s.stage === "투표") inner = (s.accepted || []).length
      ? `<ul class="tr-edits">${s.accepted.map((e) => `<li>✔ <b>${esc(e.id || "")}</b> (${e.votes_accept}표 찬성) ${esc(e.what || "")}</li>`).join("")}</ul>`
      : `<p class="hint">과반 수용된 수정 없음</p>`;
    return `<div class="tr-stage"><div class="tr-head"><span class="tr-n">${n}</span>${esc(label[s.stage] || s.stage)}</div>${inner}</div>`;
  }).join("") + `<div class="tr-stage final"><div class="tr-head"><span class="tr-n">6</span>최종 반영 — 투표 수용분을 반영해 아래 통합안 확정</div></div>`;
}

// ── 섹션: 응답자 ──
async function renderPeopleSec(c) {
  c.innerHTML = `<p class="hint">불러오는 중…</p>`;
  let list;
  try { list = await api(`/api/admin/events/${WS.ev.id}/participants`); }
  catch (e) { c.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  if (!list.length) { c.innerHTML = `<p class="hint">아직 응답자가 없습니다.</p>`; return; }
  c.innerHTML = `<p class="hint">${list.length}명 — 이름을 누르면 이 사람의 회차별 입장·이유·이동이 펼쳐집니다. 가상 응답자는 개인정보=페르소나 전문.</p>
    <div class="people-list">${list.map((p) => {
      const pr = p.profile || {};
      const who = p.kind === "virtual"
        ? `${esc(pr.persona_id || p.code)} <span class="hint">${esc(pr.age || "")} · 생성 ${esc(pr.gen_model || "?")}</span>`
        : `참여자 ${esc(String(p.id).slice(-6))} <span class="hint">${esc(pr.age || "")}</span>`;
      return `<div class="person-row" data-pid="${esc(p.id)}">
        <span class="p-kind ${p.kind}">${p.kind === "virtual" ? "가상" : "실제"}</span>
        <span class="p-who">${who}</span><span class="hint">${p.n_responses}개 회차</span>
        <div class="person-detail hidden" id="pd-${esc(p.id)}"></div></div>`;
    }).join("")}</div>`;
  c.querySelectorAll(".person-row").forEach((row) => {
    const t = () => togglePerson(row.dataset.pid);
    row.querySelector(".p-who").onclick = t; row.querySelector(".p-kind").onclick = t;
  });
}
async function togglePerson(pid) {
  const box = $(`pd-${pid}`); if (!box) return;
  if (!box.classList.contains("hidden")) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden"); box.innerHTML = `<p class="hint">불러오는 중…</p>`;
  let d; try { d = await api(`/api/admin/participants/${pid}`); } catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  const pr = d.profile || {};
  const personaBlock = pr.persona ? `<div class="persona-info"><b>개인정보(페르소나)</b><p>${esc(pr.persona)}</p></div>`
    : (d.kind === "virtual" ? `<p class="hint">페르소나 전문이 저장되지 않았습니다(구 데이터).</p>` : "");
  const rounds = d.responses || [];
  const allIds = []; rounds.forEach((r) => (r.proposals || []).forEach((p) => { if (!allIds.includes(p.id)) allIds.push(p.id); }));
  const cell = (r, pid2) => { const a = (r.answers || {})[pid2];
    if (!a) return `<td class="hint">—</td>`;
    return `<td class="st-${a.stance}"><b>${STANCE_KO[a.stance] || a.stance}</b>${a.text ? `<div class="st-text">${esc(a.text)}</div>` : ""}</td>`; };
  box.innerHTML = `${personaBlock}
    <table class="move-table"><thead><tr><th>안</th>${rounds.map((r) => `<th>${r.round_no}차</th>`).join("")}</tr></thead>
    <tbody>${allIds.map((pid2) => `<tr><th>${esc(pid2)}</th>${rounds.map((r) => cell(r, pid2)).join("")}</tr>`).join("")}</tbody></table>
    ${rounds.length < 2 ? `<p class="hint">이동(회차 간 변화)을 보려면 2개 회차 응답이 필요합니다.</p>` : ""}`;
}

// ── 섹션: 보고서 ──
async function renderReportSec(c) {
  c.innerHTML = `<p class="hint">불러오는 중…</p>`;
  let rep; try { rep = await api(`/api/admin/events/${WS.ev.id}/report`); }
  catch (e) { c.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  const cc = rep.composition;
  const bar = (d) => { const t = d.accept + d.conditional + d.reject || 1; const s = (n, cls) => n ? `<span class="seg ${cls}" style="width:${(n / t * 100).toFixed(1)}%">${n}</span>` : ""; return `<div class="dist">${s(d.accept, "a")}${s(d.conditional, "c")}${s(d.reject, "r")}</div>`; };
  const li = (a) => (a && a.length) ? a.map((x) => `<li>${esc(typeof x === "string" ? x : (x.text || JSON.stringify(x)))}</li>`).join("") : "<li class='hint'>—</li>";
  c.innerHTML = `<div class="report">
      <div class="notice">${esc(rep.non_representative_notice)}</div>
      <h3>${esc(rep.event_title)}</h3>
      <p class="rep-lead">${esc(rep.conclusion)}</p>
      <div class="rep-comp"><b>참여자</b> 실제 ${cc.human}명 · 가상 ${cc.virtual}명(검증용, 대표성 제외) · 합계 ${cc.total}명</div>
      <h4>회차별 수용도</h4>
      ${Object.entries(rep.per_round).map(([no, pr]) => `<div class="rep-round"><b>${no}차 ${esc(pr.title)}</b> (${pr.n}명)
        ${Object.entries(pr.distribution).map(([pid, d]) => `<div class="dist-row"><div class="dist-label">${esc(pid)}</div>${bar(d)}</div>`).join("")}</div>`).join("")}
      <h4>이동 (회차 간 입장 변화)</h4>
      ${Object.keys(rep.movement).length ? Object.entries(rep.movement).map(([pid, m]) =>
        `<div><b>${esc(pid)}</b>: ${Object.entries(m.transitions).map(([k, v]) => `${esc(k)} ${v}`).join(" · ")} <span class="hint">(바꿈 ${m.moved}명)</span></div>`).join("") : `<p class="hint">2개 이상 회차 응답 필요.</p>`}
      <h4>AI 숙의 근거 (반영 · 미반영)</h4>
      ${rep.deliberations.length ? rep.deliberations.map((d) => `<div class="rep-delib">
        <b>${d.round}차: ${esc(d.title)}</b> ${d.human_revised ? `<span class="badge-rev">사람 수정</span>` : ""} ${d.approved_by ? `<span class="badge-ok">✔ 승인</span>` : `<span class="badge-pend">미승인</span>`}
        <div class="rep-grounds"><div><b class="g-a">반영</b><ul>${li(d.reflects)}</ul></div>
          <div><b class="g-r">미반영(정직)</b><ul>${li(d.unaddressed)}</ul></div></div>
        <p class="hint">참여 AI: ${esc((d.provenance || []).join(" · "))}</p></div>`).join("") : `<p class="hint">아직 AI 숙의 결과 없음</p>`}
    </div>`;
}

// ── 준비 폼 (회차 섹션 내) ──
let PROPS = [];
function openForm(rd) {
  const isNew = !!rd.new;
  const intro = (rd.intro || []).join("\n");
  const proposals = rd.proposals && rd.proposals.length ? rd.proposals : [{ id: "1안", title: "", body: "" }];
  const atts = rd.attachments || [];
  const askAge = (rd.profile_fields || []).some((f) => f.key === "age");
  const f = $("prep-form"); f.classList.remove("hidden");
  f.innerHTML = `
    <div class="prep-card">
    <div class="row2">
      <div class="f-row"><label>회차 번호</label><input type="number" id="f-no" value="${rd.round_no || 1}" ${isNew ? "" : "disabled"}></div>
      <div class="f-row" style="flex:3"><label>회차 제목</label><input type="text" id="f-title" value="${esc(rd.title || "")}" placeholder="예: 1차 의견수렴"></div>
    </div>
    <div class="f-row"><label>서문 <span class="hint">(한 줄에 한 문단)</span></label>
      <textarea id="f-intro" placeholder="이 설문의 취지·안내">${esc(intro)}</textarea></div>
    <div class="f-row"><label>첨부 자료 <span class="hint">(선택 — 이름 + 링크)</span></label>
      <div id="att-items"></div><button type="button" class="btn-secondary" id="add-att">+ 자료 추가</button></div>
    <div class="f-row"><label>전문가 안(제안) <span class="hint">— 번호·제목·설명</span></label>
      <div id="prop-items"></div><button type="button" class="btn-secondary" id="add-prop">+ 안 추가</button></div>
    <div class="f-row"><label><input type="checkbox" id="f-age" ${askAge ? "checked" : ""}> 참여자에게 연령대 물어보기(세그먼트 분석용)</label></div>
    <div class="form-actions">
      <button class="btn-primary" id="f-save">${isNew ? "회차 만들기" : "저장"}</button>
      ${!isNew && rd.status === "draft" ? `<button class="btn-secondary" id="f-open">저장하고 공개</button>` : ""}
      <button class="btn-secondary" id="f-cancel">취소</button>
    </div></div>`;
  renderAtts(atts); renderProps(proposals);
  $("add-att").onclick = () => { atts.push({ name: "", url: "", type: "link" }); renderAtts(atts); };
  $("add-prop").onclick = () => addPropRow();
  $("f-cancel").onclick = () => f.classList.add("hidden");
  $("f-save").onclick = () => save(rd, false);
  if ($("f-open")) $("f-open").onclick = () => save(rd, true);
  f.scrollIntoView({ behavior: "smooth", block: "start" });
}
function renderAtts(atts) {
  const box = $("att-items"); box.innerHTML = "";
  atts.forEach((a, i) => { const d = document.createElement("div"); d.className = "item";
    d.innerHTML = `<div class="row2">
      <input type="text" data-att="${i}" data-k="name" value="${esc(a.name)}" placeholder="자료 이름">
      <input type="text" data-att="${i}" data-k="url" value="${esc(a.url)}" placeholder="링크(URL)"></div>
      <div class="item-head" style="margin-top:6px"><span class="hint">링크/PDF</span>
      <button type="button" class="icon-btn" data-rm-att="${i}">삭제</button></div>`;
    box.appendChild(d); });
  box.oninput = (e) => { const t = e.target; if (t.dataset.att != null) atts[+t.dataset.att][t.dataset.k] = t.value; };
  box.onclick = (e) => { const i = e.target.dataset.rmAtt; if (i != null) { atts.splice(+i, 1); renderAtts(atts); } };
  box._atts = atts;
}
function renderProps(props) {
  PROPS = props.map((p) => ({ ...p }));
  const box = $("prop-items"); box.innerHTML = "";
  PROPS.forEach((p, i) => box.appendChild(propRow(p, i)));
}
function addPropRow() { PROPS.push({ id: `${PROPS.length + 1}안`, title: "", body: "" });
  $("prop-items").appendChild(propRow(PROPS[PROPS.length - 1], PROPS.length - 1)); }
function propRow(p, i) {
  const d = document.createElement("div"); d.className = "item";
  d.innerHTML = `<div class="item-head"><b>안 ${i + 1}</b><button type="button" class="icon-btn" data-rmp="${i}">삭제</button></div>
    <div class="row2">
      <input type="text" data-p="${i}" data-k="id" value="${esc(p.id)}" placeholder="번호(예: 1안)" style="flex:.5">
      <input type="text" data-p="${i}" data-k="title" value="${esc(p.title)}" placeholder="안 제목" style="flex:2"></div>
    <textarea data-p="${i}" data-k="body" placeholder="안 설명(시민이 읽을 내용)" style="margin-top:8px">${esc(p.body)}</textarea>`;
  d.oninput = (e) => { const t = e.target; if (t.dataset.p != null) PROPS[+t.dataset.p][t.dataset.k] = t.value; };
  d.onclick = (e) => { const i2 = e.target.dataset.rmp; if (i2 != null) { PROPS.splice(+i2, 1); renderProps(PROPS); } };
  return d;
}
async function save(rd, open) {
  setErr("");
  const intro = $("f-intro").value.split("\n").map((s) => s.trim()).filter(Boolean);
  const atts = ($("att-items")._atts || []).filter((a) => a.name && a.url);
  const props = PROPS.filter((p) => (p.id || "").trim() && (p.title || "").trim());
  const profile_fields = $("f-age").checked
    ? [{ key: "age", label: "연령대", type: "select", options: ["20대", "30대", "40대", "50대", "60대", "70대 이상"] }] : [];
  const title = $("f-title").value.trim();
  if (!title) { setErr("회차 제목을 입력하세요"); return; }
  if (!props.length) { setErr("안을 최소 1개 입력하세요(번호+제목)"); return; }
  try {
    let rid;
    if (rd.new) {
      const created = await api(`/api/admin/events/${WS.ev.id}/rounds`, { method: "POST",
        body: JSON.stringify({ round_no: +$("f-no").value, title, intro, attachments: atts, proposals: props, profile_fields }) });
      rid = created.id;
    } else {
      rid = rd.id;
      await api(`/api/admin/rounds/${rid}`, { method: "PATCH",
        body: JSON.stringify({ title, intro, attachments: atts, proposals: props, profile_fields }) });
    }
    if (open) await api(`/api/admin/rounds/${rid}/status`, { method: "POST", body: JSON.stringify({ status: "open" }) });
    await refreshWs();
  } catch (e) { setErr("저장 실패: " + e.message); }
}

// ── AI 에이전트(독파모) 관리 화면 ──
function showAgentsView() {
  $("view-events").classList.add("hidden");
  $("view-workspace").classList.add("hidden");
  $("view-agents").classList.remove("hidden");
  renderAgents();
}
async function renderAgents() {
  const c = $("agents-body"); c.innerHTML = `<p class="hint">불러오는 중…</p>`;
  let v; try { v = await api("/api/admin/agents"); } catch (e) { c.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  const ok = v.active_companies.length >= v.min_companies;
  const provOpts = v.providers.map((p) => `<option value="${esc(p.name)}">${esc(p.name)}</option>`).join("");
  c.innerHTML = `
    <div class="guard-line ${ok ? "ok" : "bad"}">활성 회사 ${v.active_companies.length}/${v.min_companies}
      ${ok ? "✔ 숙의 가능" : "✖ 3사 미만 — 숙의 거부됨"} <span class="hint">(${v.active_companies.join(" · ") || "없음"})</span></div>

    <h3 class="sec-h">독파모 (초안가 모델)</h3>
    <div class="agent-list">${v.dokpamo.map((m) => `
      <div class="agent-row">
        <span class="p-kind ${m.enabled ? "human" : "virtual"}">${m.enabled ? "활성" : "키없음"}</span>
        <b>${esc(m.label)}</b> <span class="hint">${esc(m.company)} · ${esc(m.provider)} · ${esc(m.model)}</span>
        <span class="row-btns"><button class="btn-mini danger" data-del-dok="${esc(m.label)}">삭제</button></span>
      </div>`).join("") || `<p class="hint">독파모 없음</p>`}</div>
    <details class="add-box"><summary>+ 독파모 추가</summary>
      <div class="row2"><input id="dk-label" placeholder="표시명(예: A.X)"><input id="dk-company" placeholder="회사(예: SKT)"></div>
      <div class="row2"><select id="dk-provider">${provOpts}</select><input id="dk-model" placeholder="모델명(예: ax4)"></div>
      <button class="btn-primary" id="dk-add">독파모 추가</button></details>

    <h3 class="sec-h">프로바이더 (엔드포인트)</h3>
    <div class="agent-list">${v.providers.map((p) => `
      <div class="agent-row">
        <span class="p-kind ${p.key_present && !p.disabled ? "human" : "virtual"}">${p.disabled ? "비활성" : (p.key_present ? "키있음" : "키없음")}</span>
        <b>${esc(p.name)}</b> <span class="hint">${esc(p.kind)} · ${esc(p.base)} · env:${esc(p.env || "없음")}</span>
        <span class="row-btns"><button class="btn-mini danger" data-del-prov="${esc(p.name)}">삭제</button></span>
      </div>`).join("")}</div>
    <details class="add-box"><summary>+ 프로바이더 추가/수정</summary>
      <p class="hint">키는 서버 <code>.env</code>에 <b>env 이름</b>으로 넣으세요(예: <code>ADOTX_API_KEY=...</code>). 여기선 그 이름만 지정.</p>
      <div class="row2"><input id="pv-name" placeholder="이름(예: sktax)"><select id="pv-kind"><option>openai</option><option>clova</option><option>ollama</option></select></div>
      <input id="pv-base" placeholder="base URL(예: https://api.sktax.chat/v1)" style="width:100%;margin:6px 0">
      <div class="row2"><input id="pv-env" placeholder="env 이름(예: ADOTX_API_KEY)"><input id="pv-max" type="number" placeholder="max_tokens" value="4000"></div>
      <button class="btn-primary" id="pv-add">프로바이더 저장</button></details>`;

  c.querySelectorAll("[data-del-dok]").forEach((b) => b.onclick = async () => {
    if (!confirm(`독파모 '${b.dataset.delDok}' 삭제?`)) return;
    try { await api(`/api/admin/agents/dokpamo/${encodeURIComponent(b.dataset.delDok)}`, { method: "DELETE" }); renderAgents(); }
    catch (e) { setErr(e.message); }
  });
  c.querySelectorAll("[data-del-prov]").forEach((b) => b.onclick = async () => {
    if (!confirm(`프로바이더 '${b.dataset.delProv}' 삭제?`)) return;
    try { await api(`/api/admin/agents/providers/${encodeURIComponent(b.dataset.delProv)}`, { method: "DELETE" }); renderAgents(); }
    catch (e) { setErr(e.message); }
  });
  $("dk-add").onclick = async () => {
    try { await api("/api/admin/agents/dokpamo", { method: "POST", body: JSON.stringify({
      label: $("dk-label").value, company: $("dk-company").value, provider: $("dk-provider").value, model: $("dk-model").value }) });
      renderAgents(); } catch (e) { setErr(e.message); }
  };
  $("pv-add").onclick = async () => {
    try { await api("/api/admin/agents/providers", { method: "POST", body: JSON.stringify({
      name: $("pv-name").value, kind: $("pv-kind").value, base: $("pv-base").value,
      env: $("pv-env").value || null, max_tokens: +$("pv-max").value || 4000 }) });
      renderAgents(); } catch (e) { setErr(e.message); }
  };
}

// ── 바인딩 ──
$("manage-agents").onclick = showAgentsView;
$("back-from-agents").onclick = () => { loadEvents().then(showEventsView); };
$("login-btn").onclick = login;
$("pw").addEventListener("keydown", (e) => { if (e.key === "Enter") login(); });
$("back-to-events").onclick = () => { loadEvents().then(showEventsView); };
document.querySelectorAll(".nav-item").forEach((b) => b.onclick = () => setSection(b.dataset.sec));
$("new-ev-btn").onclick = async () => {
  const title = $("new-ev-title").value.trim(); if (!title) return;
  try { const ev = await api("/api/admin/events", { method: "POST", body: JSON.stringify({ title, context: $("new-ev-context").value }) });
    $("new-ev-title").value = ""; $("new-ev-context").value = ""; await loadEvents(); openWorkspace(ev.id); }
  catch (e) { setErr(e.message); }
};

if (TOKEN) enterDash();
