"use strict";
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const experimentId = params.get("experiment");
const reviewEventId = params.get("review");
const queryConflict = Boolean(experimentId && reviewEventId);
const eventId = reviewEventId || experimentId;
const tokenKey = eventId ? `aipol:participant:${eventId}` : "aipol:participant:missing";
const registrationNonceKey = `aipol:registration-nonce:${eventId}`;
const registrationIdempotencyKey = `aipol:registration-idempotency:${eventId}`;
const reviewToken = new URLSearchParams(location.hash.slice(1)).get("review_token");
let reviewTokenError = "";
let pendingReviewToken = "";
if (location.hash) history.replaceState(null, "", `${location.pathname}${location.search}`);
if (reviewToken !== null) {
  if (reviewEventId && !queryConflict && /^S[A-F0-9]{32}$/.test(reviewToken)) pendingReviewToken = reviewToken;
  else reviewTokenError = "합성 검토 링크가 올바르지 않습니다.";
}
let storedParticipantToken = localStorage.getItem(tokenKey) || "";
let participantToken = pendingReviewToken || storedParticipantToken;
let current = null;
let calculatorReceipt = null;
let stopCalculatorHandshake = null;
let calculatorFallbackTimer = null;
let pendingRecoveryCode = "";
let reviewIntroPending = Boolean(pendingReviewToken);

const POLICY_LEVER_COLUMNS = [
  {label:"수급개시연령", keys:["benefit_start_age","수급개시연령","수급연령"]},
  {label:"기금운용전략(수익률)", keys:["fund_management_strategy","fund_strategy","기금운용전략(운용수익률)","기금운용전략(운영수익률)","기금운용전략","운용수익률"]},
  {label:"국고투입(지원) 수준", keys:["government_support","treasury_support","국고투입(지원) 수준","국고투입","국고지원"]},
];

function clearCalculatorIntegration() {
  if (stopCalculatorHandshake) stopCalculatorHandshake();
  if (calculatorFallbackTimer) clearTimeout(calculatorFallbackTimer);
  stopCalculatorHandshake = null;
  calculatorFallbackTimer = null;
  calculatorReceipt = null;
}

function resetParticipant() {
  clearCalculatorIntegration();
  localStorage.removeItem(tokenKey);
  localStorage.removeItem(registrationNonceKey);
  localStorage.removeItem(registrationIdempotencyKey);
  for (let i = localStorage.length - 1; i >= 0; i -= 1) {
    const key = localStorage.key(i);
    if (key && key.startsWith(`aipol:idem:${eventId}:`)) localStorage.removeItem(key);
  }
  participantToken = "";
  storedParticipantToken = "";
  pendingReviewToken = "";
  current = null;
  $("admission-code").value = "";
  $("recovery-code").value = "";
  $("recovery-kit-code").value = "";
  pendingRecoveryCode = "";
  $("register-error").textContent = "";
  $("reset-error").classList.add("hidden");
  show("start");
}

function esc(value) { return String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function show(name) { ["loading","error","start","recovery","review-intro","step","done","withdrawn"].forEach((state) => $("state-" + state).classList.toggle("hidden", state !== name)); }
function updateParticipationScope() {
  const banner = $("participation-scope");
  banner.className = "scope-banner " + (current?.synthetic_review === true ? "scope-synthetic" : current?.participant_type === "real" ? "scope-real" : "scope-unknown");
  banner.textContent = current?.synthetic_review === true
    ? "합성 검토 전용 · 실제 참가자 응답이나 여론이 아니며 실제 수집은 닫혀 있습니다."
    : current?.participant_type === "real"
      ? "실제 참가 범위 · 이 행사에서 제출한 응답이 append-only 원장에 기록됩니다."
      : "참여 전 안내 · 인증 후 합성 검토 또는 실제 참가 범위를 표시합니다.";
}
function actionKey(stage, revision) {
  const key = `aipol:idem:${eventId}:${stage}:${revision}`;
  let value = localStorage.getItem(key);
  if (!value) { value = crypto.randomUUID(); localStorage.setItem(key, value); }
  return { key, value };
}
async function api(path, options={}) {
  const headers = {"Content-Type":"application/json", ...(options.headers || {})};
  if (participantToken) headers["X-Participant-Token"] = participantToken;
  const response = await fetch(path, {...options, headers});
  let body = {}; try { body = await response.json(); } catch (_) {}
  if (!response.ok) { const error = new Error(body.detail || "요청을 처리하지 못했습니다."); error.status = response.status; throw error; }
  return body;
}
async function load() {
  if (queryConflict) { $("error-message").textContent = "experiment와 review를 함께 지정할 수 없습니다."; show("error"); return; }
  if (!eventId) { $("error-message").textContent = "행사 링크에 experiment 또는 review 값이 없습니다."; show("error"); return; }
  if (reviewEventId && !pendingReviewToken && !storedParticipantToken) { $("error-message").textContent = "검토 링크에는 review_token이 필요합니다."; show("error"); return; }
  if (reviewTokenError) { $("error-message").textContent = reviewTokenError; show("error"); return; }
  show("loading");
  if (!participantToken) { show("start"); return; }
  try {
    current = await api(`/api/aipol/experiments/${encodeURIComponent(eventId)}/current`);
    if (reviewEventId && (current.event_kind !== "review" || current.synthetic_review !== true)) {
      const error = new Error("검토 행사가 아니거나 합성 검토가 활성화되지 않았습니다.");
      error.status = 401;
      throw error;
    }
    if (current.procedure_version === "aipol-pension-3-measurements-v3") {
      $("procedure-summary").textContent = "전문가 A/B/C안, 개인 영향 비교, 세 번의 선택, 전문가·청중 논평과 AI 수정 의견 D′를 차례로 확인합니다.";
    }
    if (isV4()) {
      $("procedure-summary").textContent = "취지와 동의, 구간 정보와 정책안 비교, 1차 선택, 공개 결과, 2차 선택, 숙의 자료, 3차 선택과 마무리의 9단계 흐름을 확인합니다.";
    }
    if (pendingReviewToken) {
      if (current.event_kind !== "review" || current.participant_type !== "synthetic" || current.synthetic_review !== true) {
        const error = new Error("합성 검토 링크가 이 실험의 검토 권한과 일치하지 않습니다.");
        error.status = 401;
        throw error;
      }
      localStorage.setItem(tokenKey, pendingReviewToken);
      storedParticipantToken = pendingReviewToken;
      pendingReviewToken = "";
    }
    updateParticipationScope();
    if (["E1a","E1b","E2","E3"].includes(current.stage) && current.artifact) {
      const opened=actionKey(`${current.stage}-open`,current.state_revision);
      await api(`/api/aipol/experiments/${encodeURIComponent(eventId)}/exposures/${current.stage}/open`,{method:"POST",body:JSON.stringify({expected_revision:current.state_revision,idempotency_key:opened.value})});
    }
    render();
  }
  catch (error) {
    if (pendingReviewToken) {
      pendingReviewToken = "";
      participantToken = storedParticipantToken;
      $("error-message").textContent = "합성 검토 링크가 만료되었거나 유효하지 않습니다. 기존 참여 정보는 유지했습니다.";
      $("reset-error").classList.add("hidden");
      show("error");
      return;
    }
    if (error.status === 401) {
      $("error-message").textContent = "이 기기에 저장된 참여 토큰을 확인할 수 없습니다.";
      $("reset-error").classList.remove("hidden");
      show("error");
      return;
    }
    $("error-message").textContent = error.message; show("error");
  }
}
async function register() {
  try {
    const admissionCode=$("admission-code").value.trim();if(!admissionCode){$("register-error").textContent="참여코드를 입력해 주세요.";return;}
    let nonce=localStorage.getItem(registrationNonceKey);if(!nonce){nonce=crypto.randomUUID();localStorage.setItem(registrationNonceKey,nonce);}
    let idempotency=localStorage.getItem(registrationIdempotencyKey);if(!idempotency){idempotency=crypto.randomUUID();localStorage.setItem(registrationIdempotencyKey,idempotency);}
    const result = await api(`/api/aipol/experiments/${encodeURIComponent(eventId)}/participants`, {method:"POST", body:JSON.stringify({admission_code:admissionCode,registration_nonce:nonce,idempotency_key:idempotency})});
    participantToken = result.participant_token; storedParticipantToken = participantToken; localStorage.setItem(tokenKey, participantToken);
    if (result.recovery_code) showRecoveryKit(result.recovery_code); else await load();
  } catch (error) { $("error-message").textContent = error.status === 423 ? "아직 실제 참가자 수집이 열리지 않았습니다. 진행자의 안내를 기다려 주세요." : error.message; show("error"); }
}
function showRecoveryKit(code) {
  pendingRecoveryCode = code;
  $("recovery-kit-code").value = code;
  show("recovery");
}
async function recoverParticipant() {
  const recoveryCode = $("recovery-code").value.trim();
  if (!recoveryCode) { $("recovery-error").textContent = "저장한 일회용 복구 코드를 입력해 주세요."; return; }
  $("recover").disabled = true;
  try {
    const result = await api(`/api/aipol/experiments/${encodeURIComponent(eventId)}/participants/recover`, {method:"POST", body:JSON.stringify({recovery_code:recoveryCode})});
    participantToken = result.participant_token;
    storedParticipantToken = participantToken;
    localStorage.setItem(tokenKey, participantToken);
    $("recovery-code").value = "";
    showRecoveryKit(result.recovery_code);
  } catch (error) {
    $("recovery-error").textContent = error.message;
  } finally { $("recover").disabled = false; }
}
function downloadRecoveryKit() {
  if (!pendingRecoveryCode) return;
  const blob = new Blob([`AIPOL participant recovery kit\nEvent: ${eventId}\nOne-time recovery code: ${pendingRecoveryCode}\n`], {type:"text/plain;charset=utf-8"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `aipol-recovery-${eventId}.txt`;
  link.click();
  URL.revokeObjectURL(link.href);
}
async function continueAfterRecovery() {
  pendingRecoveryCode = "";
  $("recovery-kit-code").value = "";
  await load();
}
function render() {
  if (reviewIntroPending && current.synthetic_review === true) {
    if (isV4()) renderV4ReviewIntro();
    show("review-intro"); return;
  }
  if (current.stage === "complete") { show("done"); return; }
  if (current.stage === "withdrawn") { show("withdrawn"); return; }
  show("step");
  const labels = {consent:"동의", E0:"정책전문가안 비교", M1:"1차 선택", T3:"1차 결과", E1a:"개인 조건 비교", M2:"2차 선택", T5:"1·2차 결과", T6:"조건별 분석", E2:"잠정 의견 D", E1b:"전문가 논평", A1:"공개 청중 의견", E3:"수정 의견 D′", M3:"3차 선택", T10:"최종 결과"};
  $("step-line").textContent = `${labels[current.interstitial_stage || current.stage] || current.stage} · 기록 버전 ${current.state_revision}`;
  if (["T3","T5","T10"].includes(current.stage)) renderPublicResult();
  else if (current.interstitial_stage === "T6") renderT6Result();
  else if ((current.stage === "E2" && current.waiting_for_e2_release) || (current.stage === "E3" && current.waiting_for_e3_release)) renderWaiting();
  else if (current.stage === "consent") renderConsent();
  else if (current.stage === "E0") renderPolicyOptions();
  else if (current.stage === "E1a" && current.research_profile_required) renderResearchProfile();
  else if (["E1a","E1b","E2","E3"].includes(current.stage)) renderExposure();
  else if (current.stage === "A1") renderAudienceDiscussion();
  else renderMeasurement();
  const heading=document.querySelector("#step-content h2");if(heading){heading.tabIndex=-1;heading.focus();}
}

function renderV4ReviewIntro() {
  const list = document.querySelector(".review-procedure-list");
  if (!list) return;
  const stages = [
    "취지·절차·정책전문가팀·AI팀 안내",
    "연구 참여 동의",
    "구간 정보 제출 후 정책전문가 A·B·C안 비교",
    "1차 선택과 공개 결과",
    "2차 선택과 공개 결과",
    "공개 AI 숙의 요약·쟁점·제약 자료 확인",
    "전문가 승인 diff·사유·출처 확인",
    "A·B·C 또는 A·B·C·D 3차 선택",
    "패널 총평과 마무리",
  ];
  list.innerHTML = stages.map((stage) => `<li>${esc(stage)}</li>`).join("");
  $("review-procedure-title").textContent = "9단계 개요";
  const teams = $("review-teams-title")?.parentElement;
  if (teams) teams.querySelectorAll("p")[1].innerHTML = "<strong>AI팀</strong>은 승인된 근거와 시민 의견을 바탕으로 공개 숙의 자료를 정리하며, 사람 승인 전에는 공개하지 않습니다.";
}

function policyLeverValue(option, column) {
  const values = option?.lever_values || {};
  for (const key of column.keys) {
    if (Object.prototype.hasOwnProperty.call(values, key) && String(values[key]).trim()) return values[key];
  }
  return null;
}
function renderPolicyComparison(options, caption="정책안 핵심값 비교") {
  const header = POLICY_LEVER_COLUMNS.map((column) => `<th scope="col">${esc(column.label)}</th>`).join("");
  const rows = (options || []).map((option) => `<tr><th scope="row">${esc(option.policy_option_id === "D_PRIME" ? "D′" : option.policy_option_id)}</th>${POLICY_LEVER_COLUMNS.map((column) => { const value=policyLeverValue(option,column); return `<td class="${value == null ? "missing-value" : ""}">${esc(value ?? "확정값 없음")}</td>`; }).join("")}</tr>`).join("");
  return `<div class="table-wrap"><table class="policy-table"><caption>${esc(caption)}</caption><thead><tr><th scope="col">정책안</th>${header}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
const RESEARCH_BAND_LABELS = {
  age_20_29:"20~29세", age_30_39:"30~39세", age_40_49:"40~49세", age_50_59:"50~59세", age_60_69:"60~69세", age_70_plus:"70세 이상",
  monthly_personal_income_lt_200:"월 200만원 미만", monthly_personal_income_200_399:"월 200~399만원", monthly_personal_income_400_599:"월 400~599만원", monthly_personal_income_600_799:"월 600~799만원", monthly_personal_income_800_plus:"월 800만원 이상",
  expected_contribution_years_lt_10:"10년 미만", expected_contribution_years_10_19:"10~19년", expected_contribution_years_20_29:"20~29년", expected_contribution_years_30_39:"30~39년", expected_contribution_years_40_plus:"40년 이상",
  expected_retirement_age_le_59:"59세 이하", expected_retirement_age_60_64:"60~64세", expected_retirement_age_65_67:"65~67세", expected_retirement_age_68_plus:"68세 이상",
};
const RESEARCH_FIELD_LABELS = {
  age_band_id:"연령대", monthly_personal_income_band_id:"월 개인소득 구간",
  expected_contribution_years_band_id:"예상 총 가입기간", expected_retirement_age_band_id:"예상 은퇴연령",
};
const REASON_TOPIC_LABELS = {
  benefit_adequacy:"급여 적정성", contribution_burden:"보험료 부담", fiscal_sustainability:"재정 지속가능성",
  intergenerational_fairness:"세대 간 형평", retirement_timing:"은퇴 시점", trust_and_governance:"신뢰와 거버넌스",
};
function renderResearchProfile() {
  const contract = current.research_profile_contract || {};
  const fields = contract.fields || {};
  const controls = Object.entries(fields).map(([field, values]) => `<label class="field-label" for="research-${esc(field)}">${esc(RESEARCH_FIELD_LABELS[field] || field)}</label><select id="research-${esc(field)}" class="field-input research-band"><option value="">구간을 선택해 주세요</option>${values.map((value) => `<option value="${esc(value)}">${esc(RESEARCH_BAND_LABELS[value] || value)}</option>`).join("")}</select>`).join("");
  $("step-content").innerHTML = `<section class="step-card"><h2>조건별 연구 분석 구간</h2><p>${esc(contract.consent_text || "")}</p><p class="stage-note">개인 계산에 입력하는 정확한 값은 이 서버로 전송하거나 저장하지 않습니다. 동의 여부는 행사 참여와 개인 비교 진행에 영향을 주지 않습니다.</p>${controls}<label class="option-choice"><input id="research-profile-consent" type="checkbox"><span>정확한 원값이 아닌 위 네 구간 ID 저장에 동의합니다.</span></label><p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="research-profile-decline" class="external-link" type="button">동의하지 않고 계속</button><button id="step-submit" class="btn-primary">동의하고 개인 비교로</button></div></section>`;
  bindActions(() => {
    const profile = Object.fromEntries(Object.keys(fields).map((field) => [field, $(`research-${field}`).value]));
    return submitAction("research-profile", {profile, consented:true, consent_version:contract.rules_version}, () => {
      if (Object.values(profile).some((value) => !value)) return "네 항목의 구간을 모두 선택해 주세요.";
      return $("research-profile-consent").checked || "연구 구간 저장 동의가 필요합니다.";
    });
  });
  $("research-profile-decline").onclick = () => submitAction(
    "research-profile",
    {profile:null, consented:false, consent_version:contract.rules_version},
    () => true,
  );
}
function suppressedCount(value) { return value == null ? "비공개" : String(value); }
function resultCount(value) { return value == null ? "—" : String(value); }
function provenanceItems(value) {
  const items = [];
  if (value.generated_at) items.push(`생성 시각 ${esc(value.generated_at)}`);
  if (value.approved_by) items.push(`승인자 ${esc(value.approved_by)}`);
  if (value.approved_at) items.push(`승인 시각 ${esc(value.approved_at)}`);
  if (Object.prototype.hasOwnProperty.call(value, "fallback_used")) {
    items.push(`대체안 ${value.fallback_used ? "사용" : "미사용"}`);
  }
  return items.join(" · ");
}
function renderT6Result() {
  const snapshot = current.result_snapshot || {};
  const projection = snapshot.projection || {};
  const segments = projection.segments || [];
  const rows = segments.map((segment) => {
    const profile = Object.values(segment.profile || {}).map((value) => RESEARCH_BAND_LABELS[value] || value).join(" · ");
    return `<section class="step-card"><h3>${esc(profile)}</h3>${["A","B","C"].map((optionId) => { const option=segment.options?.[optionId] || {}; const stance=option.stance_counts || {}; const reasons=Object.entries(option.reason_topic_counts || {}).filter(([,count]) => count != null).map(([code,count]) => `${REASON_TOPIC_LABELS[code] || code} ${count}`).join(", ") || "공개 가능한 주제 없음"; return `<h4>${esc(optionId)}안</h4><p>수용 ${esc(suppressedCount(stance.accept))} · 조건부 ${esc(suppressedCount(stance.conditional))} · 비선택 ${esc(suppressedCount(stance.reject))}</p><p class="artifact-meta">승인 주제: ${esc(reasons)}</p>`; }).join("")}</section>`;
  }).join("") || `<p class="stage-note">현재 최소 공개 기준을 충족한 조건 조합이 없어 세부 수치를 공개하지 않습니다.</p>`;
  const analysis = snapshot.analysis_narrative || {};
  const candidate = snapshot.d_candidate_provenance || {};
  const candidateReview = provenanceItems(candidate);
  const candidateProvenance = Object.keys(candidate).length ? `<section><h3>잠정 의견 D 생성·승인 출처</h3><p class="artifact-meta">모델 ${esc(candidate.model || "-")} · 배포 ${esc(candidate.deployment || "-")} · 프롬프트 ${esc(candidate.prompt_version || "-")} · 승인 ${esc(candidate.approval_id || "-")}<br>근거 ${esc((candidate.evidence_refs || []).join(", ") || "-")} · D 해시 ${esc(candidate.content_hash || "-")}${candidateReview ? `<br>${candidateReview}` : ""}</p></section>` : "";
  $("step-content").innerHTML = `<section class="step-card"><h2>조건별 2차 판단 분석</h2><p>오늘 이 자리의 응답만 분석했으며, 작은 집단과 역산 가능한 수치는 숨겼습니다. 합계와 자유서술 원문은 공개하지 않습니다.</p>${rows}<section><h3>규칙 기반 분석 설명</h3><p>${esc(analysis.text || "설명 자료가 없습니다.")}</p><p class="artifact-meta">분석 유형 ${esc(analysis.analysis_type || "-")} · 집계 규칙 ${esc(analysis.rules_version || snapshot.rules_version || "-")}<br>M2 집계 해시 ${esc(analysis.m2_aggregate_hash || snapshot.m2_aggregate_hash || "-")}</p></section>${candidateProvenance}<p class="artifact-meta">집계 규칙 ${esc(snapshot.rules_version)} · 결과 해시 ${esc(snapshot.content_hash)}</p><label class="option-choice"><input id="t6-result-check" type="checkbox"><span>조건별 분석과 비공개 기준을 확인했습니다.</span></label><p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">확인하고 잠정 의견 D로</button></div></section>`;
  bindActions(() => submitAction("t6-ack", {content_hash:snapshot.content_hash}, () => $("t6-result-check").checked || "조건별 분석 확인이 필요합니다."));
}
function resultRate(value) {
  return value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
}
function choiceResultTable(distribution, title) {
  if (!distribution) return "";
  const rows = (distribution.options || []).map((row) => `<tr><th scope="row">${esc(row.key === "D_PRIME" ? "D′" : row.key)}</th><td>${esc(resultCount(row.count))}</td><td>${esc(resultRate(row.rate))}</td></tr>`).join("");
  return `<section><h3>${esc(title)}</h3><div class="table-wrap"><table class="policy-table"><thead><tr><th scope="col">정책안</th><th scope="col">선택</th><th scope="col">비율</th></tr></thead><tbody>${rows}</tbody></table></div><p class="artifact-meta">유효 응답 ${esc(resultCount(distribution.denominator))} · 응답 보류 ${esc(resultCount(distribution.abstention_count))} · 미응답 ${esc(resultCount(distribution.attrition_count))}</p></section>`;
}
function percentageWidth(value) {
  if (value == null || Number.isNaN(Number(value))) return 0;
  return Math.max(0, Math.min(100, Number(value) * 100));
}
function dPrimeSegmentCharts(result) {
  const segments = result?.d_prime_segments;
  if (!segments?.length) return "";
  const cards = segments.map((segment) => {
    const rows = (segment.options || []).map((row) => {
      const width = percentageWidth(row.rate);
      return `<li class="segment-bar-item"><div class="segment-bar-head"><strong>${esc(row.key === "D_PRIME" ? "D′" : row.key)}</strong><span>${esc(resultRate(row.rate))}</span></div><div class="segment-bar-track" aria-hidden="true"><span class="segment-bar-fill" style="width:${width}%"></span></div><p class="artifact-meta">선택 ${esc(resultCount(row.count))} / 응답 ${esc(resultCount(row.denominator ?? segment.denominator))}</p></li>`;
    }).join("");
    return `<section class="step-card"><h4>${esc(segment.title)}</h4><ul class="segment-bar-list">${rows}</ul><p class="artifact-meta">최소 공개 기준 미달 집단은 비공개 처리합니다.</p></section>`;
  }).join("");
  return `<section><h3>D′안 별도 선택률 분포 그래프</h3><p class="stage-note">연령대·소득구간 기준은 그대로 두고, 마지막 선택(M3)과 별도로 측정한 D′안 선택 비율만 집단별로 보여 줍니다.</p>${cards}</section>`;
}
function stanceResultTable(distributions, title) {
  if (!distributions?.length) return "";
  const rows = distributions.map((item) => {
    const values = Object.fromEntries((item.stances || []).map((row) => [row.key, row]));
    return `<tr><th scope="row">${esc(item.option_id === "D_PRIME" ? "D′" : item.option_id)}</th><td>${esc(values.accept?.count ?? "—")}</td><td>${esc(values.conditional?.count ?? "—")}</td><td>${esc(values.reject?.count ?? "—")}</td><td>${esc(item.denominator)}</td></tr>`;
  }).join("");
  return `<section><h3>${esc(title)}</h3><div class="table-wrap"><table class="policy-table"><thead><tr><th scope="col">정책안</th><th scope="col">수용</th><th scope="col">조건부</th><th scope="col">비선택</th><th scope="col">유효</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}
function transitionResultTable(matrix, title) {
  if (!matrix) return "";
  const columns = matrix.column_options || [];
  const header = columns.map((option) => `<th scope="col">${esc(option === "D_PRIME" ? "D′" : option)}</th>`).join("");
  const rows = (matrix.row_options || []).map((option, rowIndex) => `<tr><th scope="row">${esc(option)}</th>${columns.map((_, columnIndex) => `<td>${esc(matrix.cells?.[rowIndex]?.[columnIndex] ?? "—")}</td>`).join("")}</tr>`).join("");
  return `<section><h3>${esc(title)}</h3><div class="table-wrap"><table class="policy-table"><thead><tr><th scope="col">이전 → 이후</th>${header}</tr></thead><tbody>${rows}</tbody></table></div><p class="artifact-meta">짝지어진 유효 응답 ${esc(resultCount(matrix.denominator))} · 이후 응답 보류 ${esc(resultCount(matrix.paired_abstention_count))} · 이후 미응답 ${esc(resultCount(matrix.paired_attrition_count))}</p></section>`;
}
function transitionMovementSummary(matrix, title) {
  if (!matrix) return "";
  const rowOptions = matrix.row_options || [];
  const columnOptions = matrix.column_options || [];
  const moves = [];
  rowOptions.forEach((fromOption, rowIndex) => {
    columnOptions.forEach((toOption, columnIndex) => {
      const count = Number(matrix.cells?.[rowIndex]?.[columnIndex] ?? 0);
      if (!count || fromOption === toOption) return;
      moves.push({
        from: fromOption,
        to: toOption,
        count,
      });
    });
  });
  moves.sort((left, right) => right.count - left.count || left.from.localeCompare(right.from) || left.to.localeCompare(right.to));
  const movedTotal = moves.reduce((sum, move) => sum + move.count, 0);
  const rows = moves.length
    ? moves.map((move) => `<tr><th scope="row">${esc(move.from)} → ${esc(move.to === "D_PRIME" ? "D′" : move.to)}</th><td>${esc(move.count)}</td><td>${esc(resultRate(matrix.denominator ? move.count / matrix.denominator : null))}</td></tr>`).join("")
    : `<tr><td colspan="3">M2와 M3 사이에 공개 가능한 선택 이동이 없습니다.</td></tr>`;
  return `<section><h3>${esc(title)}</h3><p class="stage-note">M2와 M3에 모두 응답한 참가자만 짝지어, 같은 선택을 유지한 경우를 제외한 실제 이동만 따로 계산했습니다.</p><div class="table-wrap"><table class="policy-table"><thead><tr><th scope="col">이동</th><th scope="col">인원</th><th scope="col">짝지어진 유효 응답 대비</th></tr></thead><tbody>${rows}</tbody></table></div><p class="artifact-meta">이동 인원 합계 ${esc(resultCount(movedTotal))} · 짝지어진 유효 응답 ${esc(resultCount(matrix.denominator))} · 이후 응답 보류 ${esc(resultCount(matrix.paired_abstention_count))} · 이후 미응답 ${esc(resultCount(matrix.paired_attrition_count))}</p></section>`;
}
function renderPublicResult() {
  if (current.waiting_for_result_release) {
    $("step-content").innerHTML = `<section class="step-card"><h2>${esc(current.title)}</h2><p>전체 참가자의 해당 선택이 마감되고 진행자가 결과를 동결·공개할 때까지 기다려 주세요.</p><p class="stage-note">개별 응답만으로 중간 결과를 만들거나 보여 주지 않습니다.</p><button id="step-submit" class="btn-primary">상태 새로고침</button></section>`;
    $("step-submit").onclick = load;
    return;
  }
  const result = current.public_result || {};
  let tables = "";
  if (current.stage === "T3") tables = choiceResultTable(result.m1, "1차 선택 분포");
  if (current.stage === "T5") tables = choiceResultTable(result.m1, "1차 선택 분포") + choiceResultTable(result.m2, "2차 선택 분포") + transitionResultTable(result.m1_to_m2, "1차 → 2차 선택 변화") + stanceResultTable(result.m2_stances, "2차 안별 판단");
  if (current.stage === "T10") {
    const m3Label = isV4() ? "3차" : "최종";
    const legacyDPrimeSegments = isV4() ? "" : dPrimeSegmentCharts(result);
    tables = legacyDPrimeSegments + choiceResultTable(result.m3, `${m3Label} 선택 분포`) + transitionMovementSummary(result.m2_to_m3, "M2에서 M3로 어떤 선택이 움직였나요?") + transitionResultTable(result.m2_to_m3, `2차 → ${m3Label} 선택 변화`) + transitionResultTable(result.m1_to_m3, `1차 → ${m3Label} 선택 변화`) + stanceResultTable(result.m3_stances, `${m3Label} 안별 판단`);
  }
  $("step-content").innerHTML = `<section class="step-card"><h2>${esc(current.title)}</h2><p class="stage-note">오늘 이 자리의 선택 결과이며 전체 시민의 여론이나 정책 효과를 뜻하지 않습니다.</p>${tables}<p class="artifact-meta">동결 시각 ${esc(result.cutoff)} · 집계 규칙 ${esc(result.rules_version)}<br>결과 해시 ${esc(result.content_hash)}</p><label class="option-choice"><input id="public-result-check" type="checkbox"><span>공개 결과와 집계 기준을 확인했습니다.</span></label><p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">확인하고 계속</button></div></section>`;
  bindActions(() => submitAction(
    `public-results/${current.stage}/ack`,
    {content_hash: result.content_hash},
    () => $("public-result-check").checked || "공개 결과 확인이 필요합니다.",
  ));
}
function renderPolicyOptions() {
  const demographics = current.demographics || {};
  if (isV4() && demographics.required === true && demographics.recorded !== true) return renderDemographics();
  const options = current.policy_options || [];
  $("step-content").innerHTML = `<section class="step-card"><h2>${esc(current.title || "정책전문가 A·B·C안 비교")}</h2><p>정책전문가가 설명한 세 안을 같은 세 정책 항목으로 다시 확인한 뒤 1차 선택으로 넘어갑니다.</p>${renderPolicyComparison(options,"정책전문가 A·B·C안")}<label class="option-choice"><input id="policy-options-check" type="checkbox"><span>A·B·C안 비교표를 확인했습니다.</span></label><p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">확인하고 1차 선택으로</button></div></section>`;
  bindActions(() => submitAction(
    "policy-options-ack",
    {content_hash: current.content_hash},
    () => $("policy-options-check").checked || "A·B·C안 비교표 확인이 필요합니다.",
  ));
}
function isV4() { return current?.procedure_version === "aipol-pension-3-measurements-v4"; }
function renderDemographics() {
  const contract = current.demographics || {};
  const fields = [
    ["gender_band_id", "성별 구간"], ["age_band_id", "연령대 구간"], ["monthly_personal_income_band_id", "월 개인소득 구간"],
  ];
  const controls = fields.map((field) => {
    const key = Array.isArray(field) ? field[0] : field;
    const label = Array.isArray(field) ? field[1] : ({gender_band_id:"성별 구간", age_band_id:"연령대 구간", monthly_personal_income_band_id:"월 개인소득 구간"}[key] || key);
    const values = contract.options?.[key] || [];
    return `<label class="field-label" for="${esc(key)}">${esc(label)}</label><select id="${esc(key)}" class="field-input demographic-band"><option value="">구간을 선택해 주세요</option>${values.map((value) => `<option value="${esc(value.id ?? value)}">${esc(value.label ?? value)}</option>`).join("")}</select>`;
  }).join("");
  $("step-content").innerHTML = `<section class="step-card"><h2>참가자 구간 정보</h2><p>개인 식별이 되지 않는 세 구간만 기록합니다. 정확한 나이·소득 등 원값은 입력하지 않습니다.</p>${controls}<p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">구간 정보를 저장하고 정책안 확인</button></div></section>`;
  bindActions(() => {
    const demographics = Object.fromEntries(fields.map((field) => [field[0], $(field[0]).value]));
    return submitAction("demographics", {...demographics, rules_version: contract.rules_version || ""}, () => Object.values(demographics).every(Boolean) || "세 구간을 모두 선택해 주세요.");
  });
}
function renderWaiting() { const final=current.stage==="E3"; $("step-content").innerHTML=`<section class="step-card"><h2>${final ? "수정 의견 D′ 공개 대기" : "잠정 의견 D 공개 대기"}</h2><p>${final ? "전문가 논평과 진행자가 선별한 공개 청중 의견이 고정되고, 승인된 D′가 공개될 때까지 기다려 주세요." : "모든 참가자의 2차 선택이 고정되고 진행자가 승인한 D를 공개할 때까지 기다려 주세요."}</p><button id="step-submit" class="btn-primary">상태 새로고침</button></section>`;$("step-submit").onclick=load; }
function renderConsent() {
  $("step-content").innerHTML = `<section class="step-card"><h2>연구 참여 동의</h2><p>${esc(current.consent_text)}</p><p class="artifact-meta">동의문 버전 ${esc(current.consent_version)}</p><label class="option-choice"><input id="consent-check" type="checkbox"><span>위 내용을 확인했으며 세 번의 선택과 자료 노출 기록 수집에 동의합니다.</span></label><p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">동의하고 계속</button></div></section>`;
  if (isV4()) $("consent-check").nextElementSibling.textContent = "위 내용을 확인했으며 각 단계의 선택과 자료 노출 기록 수집에 동의합니다.";
  bindActions(() => submitAction("consent", {consent_version: current.consent_version, affirmed: true}, () => $("consent-check").checked || "동의 확인이 필요합니다."));
}
function renderExposure() {
  const artifact = current.artifact || {};
  const content = artifact.content || {};
  if (isV4() && current.stage === "E2" && Array.isArray(content.deliberation_process)) return renderV4DeliberationArtifact(artifact, content);
  const isPersonal = current.stage === "E1a";
  const syntheticReview = isPersonal && current.synthetic_review === true;
  const title = content.title || (isPersonal ? "개인 조건 비교" : "승인 자료");
  const body = content.body || content.limitations || "";
  const provenance = !isPersonal && (artifact.model || content.model) ? `<p class="artifact-meta">모델 ${esc(artifact.model || content.model)} · 배포 ${esc(artifact.deployment || content.deployment || "-")} · 프롬프트 ${esc(artifact.prompt_version || content.prompt_version || "-")}<br>근거 ${esc(((artifact.evidence_refs || content.evidence_refs || [])).join(", ") || "-")}</p>` : "";
  const reviewProvenance = (current.stage === "E2" || current.stage === "E3") ? provenanceItems({
    generated_at: artifact.generated_at || content.generated_at,
    approved_by: artifact.approved_by,
    approved_at: artifact.approved_at,
    ...(Object.prototype.hasOwnProperty.call(artifact, "fallback_used") ? {fallback_used:artifact.fallback_used} : {}),
  }) : "";
  const policyId = current.stage === "E2" ? "D" : current.stage === "E3" ? "D_PRIME" : "";
  const policyComparison = policyId && content.lever_values ? renderPolicyComparison([{
    policy_option_id:policyId, label:title, lever_values:content.lever_values,
  }], current.stage === "E2" ? "AI 잠정 의견 D 핵심값" : "수정 의견 D′ 핵심값") : "";
  const basis = policyId
    ? `<section class="policy-basis"><h3>${current.stage === "E2" ? "D 생성 근거" : "D′ 수정 근거"}</h3><p>${esc(body)}</p><p class="artifact-meta">근거 식별자 ${esc(((artifact.evidence_refs || content.evidence_refs || [])).join(", ") || "-")}</p></section><p class="constraint-note"><strong>생성 허용범위</strong> · 보험료율 18% 이하 · 소득대체율 43% · 운용수익률 5~7% · 수급개시연령 65~70세 · 국고투입 GDP 1% 이하</p>`
    : `<p>${esc(body)}</p>`;
  const preview = isPersonal && content.review_preview ? renderPersonalComparisonPreview(content.review_preview) : "";
  clearCalculatorIntegration();
  const integrationReady = isPersonal && current.calculator_integration && current.receipt_context;
  const link = isPersonal && !syntheticReview ? `<button id="launch-calculator" class="external-link" type="button" ${integrationReady ? "" : "disabled"}>승인된 비교 도구 열기 ↗</button>` : "";
  const receipt = syntheticReview
    ? `<p class="stage-note">합성 검토에서는 외부 계산기 영수증을 생략합니다. 아래 자료와 전체 진행 흐름만 검토해 주세요.</p>`
    : isPersonal ? `<p id="calculator-status" class="stage-note" role="status" aria-live="polite">${integrationReady ? "비교 도구를 열어 완료 증명을 받아 주세요." : "승인된 계산기 연동 계약을 사용할 수 없어 진행할 수 없습니다."}</p><section id="manual-receipt" class="step-card hidden"><h3>서명 영수증 직접 입력</h3><p class="stage-note">자동 전달을 지원하지 않거나 시간이 초과되면 계산기가 표시한 flattened JWS JSON을 붙여 넣으세요. 서버가 서명과 행사 문맥을 다시 검증합니다.</p><textarea id="manual-receipt-value" maxlength="25000" rows="5"></textarea><button id="accept-manual-receipt" class="external-link" type="button">서명 영수증 확인</button><p id="manual-receipt-error" class="error-inline" role="alert"></p></section>` : "";
  $("step-content").innerHTML = `<section class="step-card"><h2>${esc(title)}</h2>${policyComparison}${basis}${preview}${link}<p class="artifact-meta">자료 ${esc(artifact.artifact_id)} · 버전 ${esc(artifact.artifact_version)} · 승인 ${esc(artifact.approval_id)}<br>해시 ${esc(artifact.content_hash)}${reviewProvenance ? `<br>${reviewProvenance}` : ""}</p>${provenance}${isPersonal ? '<p class="stage-note">나이·월소득·예상 가입기간·은퇴연령의 정확한 원값은 이 행사 서버로 보내지 않습니다.</p>' : ''}${receipt}<label class="option-choice"><input id="read-check" type="checkbox"><span>자료를 확인했습니다.</span></label><p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">확인 완료</button></div></section>`;
  if (isPersonal && integrationReady) $("launch-calculator").onclick = startCalculator;
  if (isPersonal && integrationReady) $("accept-manual-receipt").onclick = acceptManualReceipt;
  if (isPersonal && !syntheticReview) $("read-check").disabled = true;
  bindActions(() => {
    if (!$("read-check").checked) {
      $("step-error").textContent = "자료 확인이 필요합니다.";
      return;
    }
    const completionReceipt = isPersonal ? calculatorReceipt : undefined;
    if (isPersonal && !syntheticReview && !completionReceipt) { $("step-error").textContent = "비교 도구의 서명된 완료 증명이 필요합니다."; return; }
    submitAction(
      `exposures/${current.stage}`,
      {read_ack:true, ...(isPersonal && !syntheticReview ? {completion_receipt:completionReceipt} : {})},
      () => true,
    );
  });
}
function artifactText(value, fallback="승인 자료 없음") { return typeof value === "string" && value.trim() ? value : fallback; }
function artifactValueText(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (Array.isArray(value)) return value.map(artifactValueText).join(", ");
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${key}: ${artifactValueText(item)}`).join(" · ");
  return String(value);
}
function renderV4DeliberationArtifact(artifact, content) {
  const summary = content.public_summary ?? content.deliberation_summary ?? content.summary;
  const sources = content.source_bundle || {};
  const issues = content.issue_aggregation || {};
  const taxonomy = content.issue_taxonomy || issues.taxonomy || {};
  const constraints = content.admin_constraints || {};
  const process = Array.isArray(content.deliberation_process) ? content.deliberation_process : [];
  const diff = Array.isArray(content.expert_approval_diff) ? content.expert_approval_diff : [];
  const rationale = content.approval_rationale ?? content.rationale;
  const provenance = content.provenance || artifact.provenance || {};
  const sourceRows = Array.isArray(sources.documents) && sources.documents.length
    ? sources.documents.map((item) => `<li><strong>${esc(item.title)}</strong><br><span class="artifact-meta">문서 ${esc(item.document_id)} · 해시 ${esc(item.content_hash)}</span></li>`).join("")
    : `<li>${esc(artifactText(null))}</li>`;
  const processRows = process.length
    ? process.map((item, index) => `<li><strong>${index + 1}. ${esc(item.stage)}</strong><br>${esc(item.summary)}</li>`).join("")
    : `<li>${esc(artifactText(null))}</li>`;
  let issueSection = `<p>${esc(artifactText(issues.notice))}</p>`;
  if (Array.isArray(issues.topics)) {
    const denominators = issues.denominators || {};
    const issueRows = issues.topics.map((topic) => `<li><strong>${esc(topic.label)}</strong>${topic.description ? ` · ${esc(topic.description)}` : ""}<br><span>1차 관심 선택 ${esc(topic.declared_interest_participant_count)}명 · 2차 사유 언급 ${esc(topic.classified_reason_participant_count)}명 · 분류 사유 ${esc(topic.classified_reason_record_count)}건</span></li>`).join("");
    issueSection = `<ul>${issueRows}</ul><p class="artifact-meta">분모 · 1차 관심 응답자 ${esc(denominators.declared_interest_respondents)}명 · 유효 2차 응답자 ${esc(denominators.valid_m2_respondents)}명 · 승인 분류 ${esc(denominators.approved_reason_records)}/${esc(denominators.expected_reason_records)}건 · 누락 ${esc(denominators.missing_reason_records)}건</p><p class="stage-note">${issues.multi_label_totals_may_exceed_denominator ? "복수 쟁점 분류이므로 쟁점별 합계가 응답자 수를 넘을 수 있습니다." : "각 사유는 하나의 쟁점으로 분류됩니다."} 이 값은 점수가 아니라 고유 참가자 수와 승인된 사유 레코드 수입니다.</p>`;
  }
  const constraintRows = Array.isArray(constraints.constraints) && constraints.constraints.length
    ? constraints.constraints.map((item) => `<li><strong>${esc(item.constraint_id)}</strong> · ${esc(item.description)}</li>`).join("")
    : `<li>${esc(artifactText(null))}</li>`;
  const diffRows = diff.length
    ? diff.map((item) => `<li><strong>${esc(item.field)}</strong><br><span>AI 초안: ${esc(artifactValueText(item.before))}</span><br><span>전문가 승인: ${esc(artifactValueText(item.after))}</span><br><span>수정 사유: ${esc(item.reason)}</span></li>`).join("")
    : `<li>AI 초안과 승인본 사이에 공개할 수정 내역이 없습니다.</li>`;
  const provenanceRows = [
    ["자료 묶음", sources.version_id, sources.content_hash],
    ["제약조건", constraints.version_id, constraints.content_hash],
    ["쟁점 분류표", taxonomy.version_id, taxonomy.content_hash],
    ["생성 입력", provenance.contract_version, provenance.generation_input_hash],
    ["AI 초안", provenance.model, provenance.ai_draft_hash],
    ["전문가 승인 D안", provenance.approval_id, provenance.approved_d_hash],
    ["전문가 수정", provenance.approved_by, provenance.expert_diff_hash],
  ].map(([label, version, hash]) => `<li><strong>${esc(label)}</strong> · ${esc(version || "-")}<br><span class="artifact-meta">해시 ${esc(hash || "-")}</span></li>`).join("");
  const policyComparison = content.lever_values ? renderPolicyComparison([{
    policy_option_id:"D", label:content.title || "D안", lever_values:content.lever_values,
  }], "전문가 승인 D안 핵심값") : "";
  const title = content.title || "공개 AI 숙의 및 전문가 승인 D안";
  $("step-content").innerHTML = `<section class="step-card"><h2>${esc(title)}</h2>${policyComparison}<section><h3>공개 AI 숙의 요약</h3><p>${esc(artifactText(summary))}</p><ol>${processRows}</ol></section><section><h3>AI가 고려한 승인 사전자료</h3><ul>${sourceRows}</ul></section><section><h3>참가자 관심·의견의 쟁점 집계</h3>${issueSection}</section><section><h3>관리자가 승인한 제약조건</h3><ul>${constraintRows}</ul></section><section><h3>AI 초안 → 전문가 승인</h3><ul>${diffRows}</ul><p><strong>승인 사유</strong></p><p>${esc(artifactText(rationale))}</p></section><section><h3>출처·승인 계보</h3><ul>${provenanceRows}</ul><p class="artifact-meta">생성 ${esc(provenance.generated_at || "-")} · 승인 ${esc(provenance.approved_at || "-")} · 프롬프트 버전 ${esc(provenance.prompt_version || "-")}</p></section><p class="stage-note">숨은 사고 과정, 내부 프롬프트, 시민 자유서술 원문과 개인 식별 정보는 공개하지 않습니다.</p><label class="option-choice"><input id="read-check" type="checkbox"><span>숙의 과정과 전문가 승인 자료를 확인했습니다.</span></label><p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">확인 완료</button></div></section>`;
  bindActions(() => submitAction(`exposures/${current.stage}`, {read_ack:true}, () => $("read-check").checked || "자료 확인이 필요합니다."));
}
function renderPersonalComparisonPreview(preview) {
  const options = Array.isArray(preview.options)
    ? preview.options
    : Object.entries(preview.options || {}).map(([policy_option_id, value]) => ({policy_option_id, ...(value || {})}));
  const rows = options.map((option) => `<tr><th scope="row">${esc(option.policy_option_id)}</th><td>${esc(option.monthly_pension)}</td><td>${esc(option.start_and_income_gap)}</td><td>${esc(option.lifetime_benefit_at_83_5)}</td><td>${esc(option.annual_tax_burden_rate)}</td><td>${esc(option.fund_depletion_timing)}</td><td>${esc(option.personal_commentary)}</td></tr>`).join("");
  return `<section class="policy-basis"><h3>개인영향 비교 출력 항목</h3><p class="scope-banner scope-synthetic">화면 검토용 예시 · 계산 정책값과 산식 승인 전이며 실제 연금액이 아닙니다.</p><div class="table-wrap"><table class="policy-table"><thead><tr><th scope="col">안</th><th scope="col">예상 월연금</th><th scope="col">개시·소득공백</th><th scope="col">생애 총수급(83.5세)</th><th scope="col">예상 연조세부담률</th><th scope="col">연금 소진시점</th><th scope="col">개인 해설</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}
function renderAudienceDiscussion() {
  $("step-content").innerHTML = `<section class="step-card"><h2>공개 청중 의견 진행</h2><p>현장의 공개 발언을 듣고 진행자가 선별한 의견만 AI 수정 의견 D′의 입력으로 등록합니다.</p><p class="artifact-meta">이 화면은 참가자의 개인 텍스트를 수집하지 않습니다.</p><p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">공개 청중 의견 절차 확인</button></div></section>`;
  bindActions(() => submitAction("audience-discussion-ack", {}, () => true));
}
function startCalculator() {
  const status = $("calculator-status");
  try {
    clearCalculatorIntegration();
    const channelId = crypto.randomUUID();
    const returnUrl = `${location.origin}/aipol-calculator-return.html`;
    const launchUrl = AipolReceipt.buildLaunchUrl(current.calculator_integration, current.receipt_context, returnUrl, channelId, location.origin);
    stopCalculatorHandshake = AipolReceipt.createReturnChannel({
      channelId,
      context: current.receipt_context,
      BroadcastChannelClass: window.BroadcastChannel,
      onReceipt: (receiptValue) => {
        calculatorReceipt = receiptValue;
        status.textContent = "서명된 완료 증명을 받았습니다. 자료 확인 후 다음 단계로 진행하세요.";
        $("read-check").disabled = false;
        $("read-check").focus();
      },
    });
    window.open(launchUrl, "_blank", "noopener,noreferrer,popup,width=900,height=760");
    calculatorFallbackTimer = setTimeout(() => {
      $("manual-receipt").classList.remove("hidden");
      status.textContent = "자동 완료 증명을 받지 못했습니다. 계산기 창을 확인하거나 서명 영수증을 직접 붙여 넣어 주세요.";
    }, 15000);
    status.textContent = "opener와 referrer 없이 비교 도구를 열었습니다. 완료 후 안전한 행사 복귀 화면을 기다립니다.";
  } catch (error) {
    clearCalculatorIntegration();
    $("manual-receipt").classList.remove("hidden");
    status.textContent = error.message;
  }
}

function acceptManualReceipt() {
  try {
    calculatorReceipt = AipolReceipt.parse($("manual-receipt-value").value);
    $("manual-receipt-error").textContent = "";
    $("calculator-status").textContent = "서명 영수증 형식을 확인했습니다. 서버가 서명과 행사 문맥을 최종 검증합니다.";
    $("read-check").disabled = false;
    $("read-check").focus();
  } catch (error) {
    calculatorReceipt = null;
    $("manual-receipt-error").textContent = error.message;
  }
}
function renderMeasurement() {
  const options = current.policy_options || [];
  const simpleM1 = current.stage === "M1" && current.procedure_version === "aipol-pension-3-measurements-v3";
  const v4M1 = isV4() && current.stage === "M1";
  const v4M3 = isV4() && current.stage === "M3";
  const legacyStructuredM2 = current.stage === "M2" && current.procedure_version === "aipol-pension-3-measurements-v2";
  const structuredM2 = current.stage === "M2" && current.structured_option_assessment === true;
  const structuredM3 = current.stage === "M3" && current.structured_final_assessment === true && !v4M3;
  const structuredAssessment = structuredM2 || structuredM3;
  const issueTaxonomy = v4M1 && current.issue_taxonomy && Array.isArray(current.issue_taxonomy.topics)
    ? current.issue_taxonomy : null;
  const assessmentFields = structuredAssessment ? `<h3>${structuredM3 ? "네 안에 대한 최종 판단" : "세 안에 대한 판단"}</h3><p class="stage-note">선택안은 수용 또는 조건부 수용, 나머지 안은 각각 비선택 사유를 적어 주세요. 조건부 수용에도 사유가 필요합니다.</p><p class="artifact-meta">이름·연락처·소속 등 개인을 알아볼 수 있는 정보는 적지 마세요.</p>${options.map((option) => `<fieldset class="option-assessment"><legend>${esc(option.policy_option_id === "D_PRIME" ? "D′" : option.policy_option_id)}</legend><label class="field-label" for="assessment-${esc(option.policy_option_id)}">판단</label><select id="assessment-${esc(option.policy_option_id)}" class="field-input option-assessment-stance" data-option-id="${esc(option.policy_option_id)}"><option value="">선택해 주세요</option><option value="accept">수용</option><option value="conditional">조건부 수용</option><option value="reject">비선택</option></select><label class="field-label" for="assessment-reason-${esc(option.policy_option_id)}">사유</label><textarea id="assessment-reason-${esc(option.policy_option_id)}" class="option-assessment-reason" data-option-id="${esc(option.policy_option_id)}" maxlength="2000"></textarea></fieldset>`).join("")}` : "";
  const legacyStance = legacyStructuredM2 ? `<label class="field-label" for="stance">선택한 안에 대한 판단</label><select id="stance" class="field-input"><option value="">선택해 주세요</option><option value="accept">수용</option><option value="conditional">조건부 수용</option><option value="reject">비선택</option></select>` : "";
  const reasonLabel = legacyStructuredM2 ? "선택 이유 (조건부 수용·비선택은 필수)" : "선택 이유 (선택)";
  const optionalDetails = simpleM1 ? "" : structuredAssessment ? assessmentFields : `${legacyStance}<label class="field-label" for="reason">${reasonLabel}</label><p class="artifact-meta">이름·연락처·소속 등 개인을 알아볼 수 있는 정보는 적지 마세요.</p><textarea id="reason" maxlength="2000"></textarea>`;
  const confidenceField = simpleM1 ? "" : `<label class="field-label" for="confidence">선택 확신도 1~5</label><select id="confidence" class="field-input"><option value="">선택 안 함</option>${[1,2,3,4,5].map((n) => `<option value="${n}">${n}</option>`).join("")}</select>`;
  const comparisonCaption = current.stage === "M3" ? "A·B·C·D′ 최종 비교" : "A·B·C 핵심값 비교";
  const effectiveComparisonCaption = isV4() ? "정책안 핵심값 비교" : comparisonCaption;
  const stageCaption = isV4() && current.stage === "M3" ? "3차 선택" : `${current.stage.replace("M", "")}차 선택`;
  $("step-content").innerHTML = `<section class="step-card"><h2>${esc(stageCaption)}</h2><p>${esc(current.question_text || current.question_id)}</p>${renderPolicyComparison(options,effectiveComparisonCaption)}<div class="option-list">${options.map((option) => `<label class="option-choice"><input type="radio" name="choice" value="${esc(option.policy_option_id)}"><span><strong>${esc(option.policy_option_id === "D_PRIME" && !isV4() ? "D′" : option.policy_option_id)}</strong><small>정책 버전 ${esc(option.policy_version)}</small></span></label>`).join("")}${structuredAssessment || simpleM1 ? "" : `<label class="option-choice"><input type="radio" name="choice" value="__abstain__"><span><strong>응답 보류</strong><small>주 선택은 무응답으로 기록됩니다.</small></span></label>`}</div>${optionalDetails}${confidenceField}${current.stage === "M3" && current.secondary_evaluation ? `<hr><h3>AI가 제시한 별도 안 평가</h3><p class="stage-note">이 평가는 위 주 선택과 별도로 저장됩니다.</p><label class="field-label" for="secondary">수용도 1~5</label><select id="secondary" class="field-input"><option value="">선택 안 함</option>${[1,2,3,4,5].map((n) => `<option value="${n}">${n}</option>`).join("")}</select>` : ""}<p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">${esc(current.stage)} 제출</button></div></section>`;
  if (v4M1 || v4M3) {
    document.querySelectorAll('input[value="__abstain__"], #confidence, #secondary').forEach((node) => node.closest("label, hr, h3, select")?.remove());
    document.querySelectorAll("#reason, #stance").forEach((node) => node.remove());
    const detail = document.createElement("div");
    const issueFields = v4M1
      ? `<fieldset class="option-assessment"><legend>현재 관심 있는 쟁점 (필수)</legend><p class="stage-note">선택 이유와 함께 쟁점 분류의 입력으로 사용됩니다. 승인된 분류표 버전 ${esc(issueTaxonomy?.version_id || "-")} 기준입니다.</p>${(issueTaxonomy?.topics || []).map((topic) => `<label class="option-choice"><input type="${issueTaxonomy.classification_mode === "single_label" ? "radio" : "checkbox"}" name="issue-interest" value="${esc(topic.code)}"><span><strong>${esc(topic.label)}</strong>${topic.description ? `<small>${esc(topic.description)}</small>` : ""}</span></label>`).join("")}</fieldset>`
      : "";
    detail.innerHTML = `<label class="field-label" for="stance">선택한 안에 대한 판단</label><select id="stance" class="field-input"><option value="">선택해 주세요</option><option value="accept">수용</option><option value="conditional">조건부 수용</option></select><label class="field-label" for="reason">선택 이유 (필수)</label><textarea id="reason" maxlength="2000"></textarea>${issueFields}`;
    $("step-submit").parentElement.parentElement.insertBefore(detail, $("step-submit").parentElement.previousElementSibling);
  }
  bindActions(() => {
    const choice = document.querySelector('input[name="choice"]:checked');
    const secondary = $("secondary");
    const extra = secondary && secondary.value ? {secondary_evaluation:{artifact_id:current.secondary_evaluation.artifact_id, acceptance:Number(secondary.value), reason:""}} : {};
    const optionAssessments = structuredAssessment ? Object.fromEntries(options.map((option) => [option.policy_option_id, {stance:$(`assessment-${option.policy_option_id}`).value, reason:$(`assessment-reason-${option.policy_option_id}`).value}])) : undefined;
    const issueInterests = v4M1 ? Array.from(document.querySelectorAll('input[name="issue-interest"]:checked')).map((node) => node.value) : undefined;
    const effectiveChoice = choice?.value;
    const effectiveConfidence = $("confidence")?.value ? Number($("confidence").value) : null;
    submitAction(`measurements/${current.stage}`, {choice:effectiveChoice === "__abstain__" ? null : effectiveChoice, stance:$("stance")?.value || null, reason:$("reason")?.value || "", confidence:effectiveConfidence, ...(structuredAssessment ? {option_assessments:optionAssessments} : {}), ...(v4M1 ? {issue_interests:issueInterests} : {}), ...extra}, () => {
      if (!effectiveChoice) return structuredAssessment ? "정책안 중 하나를 선택해 주세요." : "A/B/C 또는 응답 보류를 선택해 주세요.";
      if ((v4M1 || v4M3) && !["accept", "conditional"].includes($("stance").value)) return "선택한 안을 수용 또는 조건부 수용으로 표시해 주세요.";
      if ((v4M1 || v4M3) && !$("reason").value.trim()) return "선택 이유를 적어 주세요.";
      if (v4M1 && issueInterests.length === 0) return "현재 관심 있는 쟁점을 하나 이상 선택해 주세요.";
      if (structuredAssessment) {
        for (const option of options) {
          const assessment = optionAssessments[option.policy_option_id];
          if (option.policy_option_id === effectiveChoice && !["accept","conditional"].includes(assessment.stance)) return "선택안은 수용 또는 조건부 수용으로 표시해 주세요.";
          if (option.policy_option_id === effectiveChoice && !assessment.reason.trim()) return "선택안의 수용 또는 조건부 수용 사유를 적어 주세요.";
          if (option.policy_option_id !== effectiveChoice && (assessment.stance !== "reject" || !assessment.reason.trim())) return "선택하지 않은 각 안은 비선택과 사유를 적어 주세요.";
          if (assessment.stance === "conditional" && !assessment.reason.trim()) return "조건부 수용 사유를 적어 주세요.";
        }
      }
      const legacyDecision = $("stance")?.value;
      if (legacyStructuredM2 && !legacyDecision) return "수용, 조건부 수용, 비선택 중 하나를 선택해 주세요.";
      if (legacyStructuredM2 && ["conditional", "reject"].includes(legacyDecision) && !$("reason").value.trim()) return "조건부 수용과 비선택에는 이유를 적어 주세요.";
      return true;
    });
  });
}
function bindActions(primary) { $("step-submit").onclick = primary; const row=$("step-submit").parentElement; const withdraw=document.createElement("button");withdraw.type="button";withdraw.className="external-link";withdraw.textContent="참여 철회";withdraw.onclick=async()=>{if(!confirm("참여를 철회하면 이후 단계를 제출할 수 없습니다. 철회할까요?"))return;const idem=actionKey(`withdraw-${current.stage}`,current.state_revision);try{await api(`/api/aipol/experiments/${encodeURIComponent(eventId)}/withdraw`,{method:"POST",body:JSON.stringify({reason:"participant-request",expected_revision:current.state_revision,idempotency_key:idem.value})});localStorage.removeItem(idem.key);await load();}catch(e){$("step-error").textContent=e.message;}};row.appendChild(withdraw); }
async function submitAction(path, body, validate) {
  const valid = validate(); if (valid !== true) { $("step-error").textContent = valid; return; }
  const idem = actionKey(current.stage, current.state_revision); $("step-submit").disabled = true;
  try {
    await api(`/api/aipol/experiments/${encodeURIComponent(eventId)}/${path}`, {method:"POST", body:JSON.stringify({...body, expected_revision:current.state_revision, idempotency_key:idem.value})});
    localStorage.removeItem(idem.key); clearCalculatorIntegration(); await load();
  } catch (error) { $("step-error").textContent = error.message; $("step-submit").disabled = false; }
}
$("register").onclick = register;
$("recover").onclick = recoverParticipant;
$("download-recovery-kit").onclick = downloadRecoveryKit;
$("continue-after-recovery").onclick = continueAfterRecovery;
$("continue-review").onclick = () => { reviewIntroPending = false; render(); };
$("retry").onclick = load;
$("reset-error").onclick = resetParticipant;
$("reset-done").onclick = resetParticipant;
$("reset-withdrawn").onclick = resetParticipant;
load();
