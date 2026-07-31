/* 시민 응답 화면 로직. 계약: 모든 안 입장 필수 + 조건부는 의견 필수. 로컬 초안 저장. */
"use strict";
const STANCES = [["accept", "수용"], ["conditional", "조건부"], ["reject", "거부"]];
let SURVEY = null;
const answers = {};   // { propId: {stance, text} }
const profile = {};
let DRAFT_KEY = "draft:unknown";

const $ = (id) => document.getElementById(id);
function show(state) {
  ["loading", "error", "empty", "survey", "done"].forEach((s) =>
    $("state-" + s).classList.toggle("hidden", s !== state));
}

async function load() {
  show("loading");
  try {
    const r = await fetch("/api/citizen/current");
    if (!r.ok) throw new Error("bad status");
    const data = await r.json();
    if (!data.open || !data.survey) { show("empty"); return; }
    SURVEY = data.survey;
    DRAFT_KEY = `draft:${SURVEY.event_title}:${SURVEY.round}`;
    restoreDraft();
    render();
    show("survey");
  } catch (e) { show("error"); }
}

function restoreDraft() {
  try {
    const d = JSON.parse(localStorage.getItem(DRAFT_KEY) || "{}");
    Object.assign(answers, d.answers || {});
    Object.assign(profile, d.profile || {});
  } catch (e) {}
}
function saveDraft() {
  try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ answers, profile })); } catch (e) {}
}

function render() {
  $("event-title").textContent = `${SURVEY.event_title} · ${SURVEY.round}회차`;
  $("survey-title").textContent = SURVEY.title;
  // 서문(데이터): 문자열 또는 문단 배열 모두 지원
  const intro = Array.isArray(SURVEY.intro) ? SURVEY.intro : (SURVEY.intro ? [SURVEY.intro] : []);
  $("survey-intro").innerHTML = intro.map((p) => `<p>${escapeHtml(p)}</p>`).join("");
  // 첨부 자료(데이터)
  const att = SURVEY.attachments || [];
  $("attachments").innerHTML = att.length ? `<div class="att-label">함께 보기</div>` + att.map((a) =>
    `<a class="att" href="${escapeHtml(a.url || "#")}" target="_blank" rel="noopener">
       <span class="att-ico">${a.type === "pdf" ? "📄" : "🔗"}</span>${escapeHtml(a.name)}</a>`).join("") : "";
  $("prop-total").textContent = SURVEY.proposals.length;
  $("progress-total").textContent = SURVEY.proposals.length;

  const wrap = $("proposals");
  wrap.innerHTML = "";
  SURVEY.proposals.forEach((p, i) => {
    const cur = answers[p.id] || {};
    const card = document.createElement("section");
    card.className = "card proposal";
    card.id = "card-" + p.id;
    card.innerHTML = `
      <div class="prop-num">${p.id}${p.origin === "ai" ? " · AI 제안" : ""}${p.human_revised ? " · 사람이 수정함" : ""}</div>
      <h2>${escapeHtml(p.title || p.id)}</h2>
      <p class="desc">${escapeHtml(p.body || "")}</p>
      <div class="stances" role="group" aria-label="${escapeHtml(p.title || p.id)} 입장">
        ${STANCES.map(([v, lab]) => `
          <button type="button" class="stance ${v}" data-p="${p.id}" data-v="${v}"
                  aria-pressed="${cur.stance === v}">${lab}</button>`).join("")}
      </div>
      <label class="opinion-label" for="op-${p.id}">의견<span class="req" data-req="${p.id}" ${cur.stance === "conditional" ? "" : "hidden"}> — 조건부는 필수</span></label>
      <textarea id="op-${p.id}" data-p="${p.id}" placeholder="이유나 조건을 자유롭게 적어주세요">${escapeHtml(cur.text || "")}</textarea>
    `;
    wrap.appendChild(card);
  });

  const pf = $("profile-fields");
  pf.innerHTML = "";
  (SURVEY.profile_fields || []).forEach((f) => {
    const div = document.createElement("div");
    div.className = "field";
    if (f.type === "select") {
      div.innerHTML = `<label for="pf-${f.key}">${escapeHtml(f.label)}</label>
        <select id="pf-${f.key}" data-k="${f.key}"><option value="">선택 안 함</option>
        ${(f.options || []).map((o) => `<option ${profile[f.key] === o ? "selected" : ""}>${escapeHtml(o)}</option>`).join("")}</select>`;
    } else {
      div.innerHTML = `<label for="pf-${f.key}">${escapeHtml(f.label)}</label>
        <input id="pf-${f.key}" data-k="${f.key}" value="${escapeHtml(profile[f.key] || "")}" />`;
    }
    pf.appendChild(div);
  });
  updateProgress();
}

function updateProgress() {
  const n = SURVEY.proposals.filter((p) => (answers[p.id] || {}).stance).length;
  $("progress-count").textContent = n;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// 이벤트 위임
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".stance");
  if (btn) {
    const pid = btn.dataset.p, v = btn.dataset.v;
    answers[pid] = answers[pid] || { text: "" };
    answers[pid].stance = v;
    // 같은 그룹 버튼 토글
    document.querySelectorAll(`.stance[data-p="${pid}"]`).forEach((b) =>
      b.setAttribute("aria-pressed", b.dataset.v === v));
    // 조건부면 의견 필수 표시
    const req = document.querySelector(`[data-req="${pid}"]`);
    if (req) req.hidden = v !== "conditional";
    document.getElementById("card-" + pid).classList.remove("missing");
    updateProgress(); saveDraft();
  }
});
document.addEventListener("input", (e) => {
  const ta = e.target.closest("textarea[data-p]");
  if (ta) { const pid = ta.dataset.p; answers[pid] = answers[pid] || {}; answers[pid].text = ta.value; saveDraft(); return; }
  const pf = e.target.closest("[data-k]");
  if (pf) { profile[pf.dataset.k] = pf.value; saveDraft(); }
});
document.addEventListener("change", (e) => {
  const pf = e.target.closest("select[data-k]");
  if (pf) { profile[pf.dataset.k] = pf.value; saveDraft(); }
});

$("retry").addEventListener("click", load);
$("submit").addEventListener("click", submit);

async function submit() {
  const err = $("submit-error");
  err.classList.add("hidden");
  document.querySelectorAll(".card.missing").forEach((c) => c.classList.remove("missing"));
  // 1차 검증: 모든 안 입장 + 조건부 의견
  let firstBad = null;
  for (const p of SURVEY.proposals) {
    const a = answers[p.id] || {};
    if (!a.stance) { firstBad = firstBad || { id: p.id, msg: "모든 안에 입장을 선택해 주세요" }; markMissing(p.id); }
    else if (a.stance === "conditional" && !(a.text || "").trim()) {
      firstBad = firstBad || { id: p.id, msg: "조건부를 고른 안에는 조건을 적어주세요" }; markMissing(p.id);
    }
  }
  if (firstBad) {
    err.textContent = firstBad.msg;
    err.classList.remove("hidden");
    document.getElementById("card-" + firstBad.id).scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  // 서버 제출: 계약 재검증 + 저장 + 중복차단. 참여코드(이동 연결) 전송/저장.
  try {
    const codeKey = `code:${SURVEY.event_title}`;
    const savedCode = localStorage.getItem(codeKey) || null;
    const r = await fetch("/api/citizen/submit", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers, profile, code: savedCode }),
    });
    const d = await r.json();
    if (!d.ok) { err.textContent = d.error || "제출 실패"; err.classList.remove("hidden"); return; }
    if (d.code) localStorage.setItem(codeKey, d.code);
    localStorage.removeItem(DRAFT_KEY);
    $("done-note").innerHTML = (d.note ? escapeHtml(d.note) + "<br>" : "") +
      (d.code && d.code !== "DEMO" ? `다음 회차에 이 기기로 다시 들어오면 이어집니다.<br>참여 코드(백업): <b>${escapeHtml(d.code)}</b>` : "");
    show("done");
  } catch (e) {
    err.textContent = "제출 중 오류가 발생했습니다. 다시 시도해 주세요."; err.classList.remove("hidden");
  }
}
function markMissing(pid) { document.getElementById("card-" + pid).classList.add("missing"); }

load();
