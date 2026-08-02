"use strict";
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const experimentId = params.get("experiment");
const tokenKey = experimentId ? `aipol:participant:${experimentId}` : "aipol:participant:missing";
const registrationNonceKey = `aipol:registration-nonce:${experimentId}`;
const registrationIdempotencyKey = `aipol:registration-idempotency:${experimentId}`;
const reviewToken = new URLSearchParams(location.hash.slice(1)).get("review_token");
let reviewTokenError = "";
let pendingReviewToken = "";
if (location.hash) history.replaceState(null, "", `${location.pathname}${location.search}`);
if (reviewToken !== null) {
  if (experimentId && /^S[A-F0-9]{32}$/.test(reviewToken)) pendingReviewToken = reviewToken;
  else reviewTokenError = "합성 검토 링크가 올바르지 않습니다.";
}
let storedParticipantToken = localStorage.getItem(tokenKey) || "";
let participantToken = pendingReviewToken || storedParticipantToken;
let current = null;
let calculatorReceipt = null;
let stopCalculatorHandshake = null;
let calculatorFallbackTimer = null;
let pendingRecoveryCode = "";

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
    if (key && key.startsWith(`aipol:idem:${experimentId}:`)) localStorage.removeItem(key);
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
function show(name) { ["loading","error","start","recovery","step","done","withdrawn"].forEach((state) => $("state-" + state).classList.toggle("hidden", state !== name)); }
function actionKey(stage, revision) {
  const key = `aipol:idem:${experimentId}:${stage}:${revision}`;
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
  if (!experimentId) { $("error-message").textContent = "행사 링크에 experiment 값이 없습니다."; show("error"); return; }
  if (reviewTokenError) { $("error-message").textContent = reviewTokenError; show("error"); return; }
  show("loading");
  if (!participantToken) { show("start"); return; }
  try {
    current = await api(`/api/aipol/experiments/${encodeURIComponent(experimentId)}/current`);
    if (current.procedure_version === "aipol-pension-3-measurements-v3") {
      $("procedure-summary").textContent = "전문가 A/B/C안, 개인 영향 비교, 세 번의 선택, 전문가·청중 논평과 AI 수정 의견 D′를 차례로 확인합니다.";
    }
    if (pendingReviewToken) {
      if (current.participant_type !== "synthetic" || current.synthetic_review !== true) {
        const error = new Error("합성 검토 링크가 이 실험의 검토 권한과 일치하지 않습니다.");
        error.status = 401;
        throw error;
      }
      localStorage.setItem(tokenKey, pendingReviewToken);
      storedParticipantToken = pendingReviewToken;
      pendingReviewToken = "";
    }
    if (["E1a","E1b","E2","E3"].includes(current.stage) && current.artifact) {
      const opened=actionKey(`${current.stage}-open`,current.state_revision);
      await api(`/api/aipol/experiments/${encodeURIComponent(experimentId)}/exposures/${current.stage}/open`,{method:"POST",body:JSON.stringify({expected_revision:current.state_revision,idempotency_key:opened.value})});
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
    const result = await api(`/api/aipol/experiments/${encodeURIComponent(experimentId)}/participants`, {method:"POST", body:JSON.stringify({admission_code:admissionCode,registration_nonce:nonce,idempotency_key:idempotency})});
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
    const result = await api(`/api/aipol/experiments/${encodeURIComponent(experimentId)}/participants/recover`, {method:"POST", body:JSON.stringify({recovery_code:recoveryCode})});
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
  const blob = new Blob([`AIPOL participant recovery kit\nExperiment: ${experimentId}\nOne-time recovery code: ${pendingRecoveryCode}\n`], {type:"text/plain;charset=utf-8"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `aipol-recovery-${experimentId}.txt`;
  link.click();
  URL.revokeObjectURL(link.href);
}
async function continueAfterRecovery() {
  pendingRecoveryCode = "";
  $("recovery-kit-code").value = "";
  await load();
}
function render() {
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
  if (current.stage === "T10") tables = choiceResultTable(result.m3, "최종 선택 분포") + transitionResultTable(result.m2_to_m3, "2차 → 최종 선택 변화") + transitionResultTable(result.m1_to_m3, "1차 → 최종 선택 변화") + stanceResultTable(result.m3_stances, "최종 안별 판단");
  $("step-content").innerHTML = `<section class="step-card"><h2>${esc(current.title)}</h2><p class="stage-note">오늘 이 자리의 선택 결과이며 전체 시민의 여론이나 정책 효과를 뜻하지 않습니다.</p>${tables}<p class="artifact-meta">동결 시각 ${esc(result.cutoff)} · 집계 규칙 ${esc(result.rules_version)}<br>결과 해시 ${esc(result.content_hash)}</p><label class="option-choice"><input id="public-result-check" type="checkbox"><span>공개 결과와 집계 기준을 확인했습니다.</span></label><p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">확인하고 계속</button></div></section>`;
  bindActions(() => submitAction(
    `public-results/${current.stage}/ack`,
    {content_hash: result.content_hash},
    () => $("public-result-check").checked || "공개 결과 확인이 필요합니다.",
  ));
}
function renderPolicyOptions() {
  const options = current.policy_options || [];
  const leverKeys = [...new Set(options.flatMap((option) => Object.keys(option.lever_values || {})))];
  const header = leverKeys.map((key) => `<th scope="col">${esc(key)}</th>`).join("");
  const rows = options.map((option) => `<tr><th scope="row">${esc(option.policy_option_id)} · ${esc(option.label)}</th>${leverKeys.map((key) => `<td>${esc(option.lever_values?.[key] ?? "-")}</td>`).join("")}</tr>`).join("");
  $("step-content").innerHTML = `<section class="step-card"><h2>${esc(current.title || "정책전문가 A·B·C안 비교")}</h2><p>정책전문가가 설명한 세 안을 같은 항목으로 다시 확인한 뒤 1차 선택으로 넘어갑니다.</p><div class="table-wrap"><table class="policy-table"><thead><tr><th scope="col">정책안</th>${header}</tr></thead><tbody>${rows}</tbody></table></div><label class="option-choice"><input id="policy-options-check" type="checkbox"><span>A·B·C안 비교표를 확인했습니다.</span></label><p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">확인하고 1차 선택으로</button></div></section>`;
  bindActions(() => submitAction(
    "policy-options-ack",
    {content_hash: current.content_hash},
    () => $("policy-options-check").checked || "A·B·C안 비교표 확인이 필요합니다.",
  ));
}
function renderWaiting() { const final=current.stage==="E3"; $("step-content").innerHTML=`<section class="step-card"><h2>${final ? "수정 의견 D′ 공개 대기" : "잠정 의견 D 공개 대기"}</h2><p>${final ? "전문가 논평과 진행자가 선별한 공개 청중 의견이 고정되고, 승인된 D′가 공개될 때까지 기다려 주세요." : "모든 참가자의 2차 선택이 고정되고 진행자가 승인한 D를 공개할 때까지 기다려 주세요."}</p><button id="step-submit" class="btn-primary">상태 새로고침</button></section>`;$("step-submit").onclick=load; }
function renderConsent() {
  $("step-content").innerHTML = `<section class="step-card"><h2>연구 참여 동의</h2><p>${esc(current.consent_text)}</p><p class="artifact-meta">동의문 버전 ${esc(current.consent_version)}</p><label class="option-choice"><input id="consent-check" type="checkbox"><span>위 내용을 확인했으며 세 번의 선택과 자료 노출 기록 수집에 동의합니다.</span></label><p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">동의하고 계속</button></div></section>`;
  bindActions(() => submitAction("consent", {consent_version: current.consent_version, affirmed: true}, () => $("consent-check").checked || "동의 확인이 필요합니다."));
}
function renderExposure() {
  const artifact = current.artifact || {};
  const content = artifact.content || {};
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
  clearCalculatorIntegration();
  const integrationReady = isPersonal && current.calculator_integration && current.receipt_context;
  const link = isPersonal && !syntheticReview ? `<button id="launch-calculator" class="external-link" type="button" ${integrationReady ? "" : "disabled"}>승인된 비교 도구 열기 ↗</button>` : "";
  const receipt = syntheticReview
    ? `<p class="stage-note">합성 검토에서는 외부 계산기 영수증을 생략합니다. 아래 자료와 전체 진행 흐름만 검토해 주세요.</p>`
    : isPersonal ? `<p id="calculator-status" class="stage-note" role="status" aria-live="polite">${integrationReady ? "비교 도구를 열어 완료 증명을 받아 주세요." : "승인된 계산기 연동 계약을 사용할 수 없어 진행할 수 없습니다."}</p><section id="manual-receipt" class="step-card hidden"><h3>서명 영수증 직접 입력</h3><p class="stage-note">자동 전달을 지원하지 않거나 시간이 초과되면 계산기가 표시한 flattened JWS JSON을 붙여 넣으세요. 서버가 서명과 행사 문맥을 다시 검증합니다.</p><textarea id="manual-receipt-value" maxlength="25000" rows="5"></textarea><button id="accept-manual-receipt" class="external-link" type="button">서명 영수증 확인</button><p id="manual-receipt-error" class="error-inline" role="alert"></p></section>` : "";
  $("step-content").innerHTML = `<section class="step-card"><h2>${esc(title)}</h2><p>${esc(body)}</p>${link}<p class="artifact-meta">자료 ${esc(artifact.artifact_id)} · 버전 ${esc(artifact.artifact_version)} · 승인 ${esc(artifact.approval_id)}<br>해시 ${esc(artifact.content_hash)}${reviewProvenance ? `<br>${reviewProvenance}` : ""}</p>${provenance}${isPersonal ? '<p class="stage-note">소득 등 개인 입력 원값은 이 행사 서버로 보내지 않습니다.</p>' : ''}${receipt}<label class="option-choice"><input id="read-check" type="checkbox"><span>자료를 확인했습니다.</span></label><p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">확인 완료</button></div></section>`;
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
  const legacyStructuredM2 = current.stage === "M2" && current.procedure_version === "aipol-pension-3-measurements-v2";
  const structuredM2 = current.stage === "M2" && current.structured_option_assessment === true;
  const structuredM3 = current.stage === "M3" && current.structured_final_assessment === true;
  const structuredAssessment = structuredM2 || structuredM3;
  const assessmentFields = structuredAssessment ? `<h3>${structuredM3 ? "네 안에 대한 최종 판단" : "세 안에 대한 판단"}</h3><p class="stage-note">선택안은 수용 또는 조건부 수용, 나머지 안은 각각 비선택 사유를 적어 주세요. 조건부 수용에도 사유가 필요합니다.</p><p class="artifact-meta">이름·연락처·소속 등 개인을 알아볼 수 있는 정보는 적지 마세요.</p>${options.map((option) => `<fieldset class="option-assessment"><legend>${esc(option.policy_option_id)} · ${esc(option.label)}</legend><label class="field-label" for="assessment-${esc(option.policy_option_id)}">판단</label><select id="assessment-${esc(option.policy_option_id)}" class="field-input option-assessment-stance" data-option-id="${esc(option.policy_option_id)}"><option value="">선택해 주세요</option><option value="accept">수용</option><option value="conditional">조건부 수용</option><option value="reject">비선택</option></select><label class="field-label" for="assessment-reason-${esc(option.policy_option_id)}">사유</label><textarea id="assessment-reason-${esc(option.policy_option_id)}" class="option-assessment-reason" data-option-id="${esc(option.policy_option_id)}" maxlength="2000"></textarea></fieldset>`).join("")}` : "";
  const legacyStance = legacyStructuredM2 ? `<label class="field-label" for="stance">선택한 안에 대한 판단</label><select id="stance" class="field-input"><option value="">선택해 주세요</option><option value="accept">수용</option><option value="conditional">조건부 수용</option><option value="reject">비선택</option></select>` : "";
  const reasonLabel = legacyStructuredM2 ? "선택 이유 (조건부 수용·비선택은 필수)" : "선택 이유 (선택)";
  $("step-content").innerHTML = `<section class="step-card"><h2>${esc(current.stage.replace("M", ""))}차 선택</h2><p>${esc(current.question_text || current.question_id)}</p><div class="option-list">${options.map((option) => `<label class="option-choice"><input type="radio" name="choice" value="${esc(option.policy_option_id)}"><span><strong>${esc(option.policy_option_id)} · ${esc(option.label)}</strong><small>정책 버전 ${esc(option.policy_version)}</small></span></label>`).join("")}${structuredAssessment ? "" : `<label class="option-choice"><input type="radio" name="choice" value="__abstain__"><span><strong>응답 보류</strong><small>주 선택은 무응답으로 기록됩니다.</small></span></label>`}</div>${structuredAssessment ? assessmentFields : `${legacyStance}<label class="field-label" for="reason">${reasonLabel}</label><p class="artifact-meta">이름·연락처·소속 등 개인을 알아볼 수 있는 정보는 적지 마세요.</p><textarea id="reason" maxlength="2000"></textarea>`}<label class="field-label" for="confidence">선택 확신도 1~5</label><select id="confidence" class="field-input"><option value="">선택 안 함</option>${[1,2,3,4,5].map((n) => `<option value="${n}">${n}</option>`).join("")}</select>${current.stage === "M3" && current.secondary_evaluation ? `<hr><h3>AI가 제시한 별도 안 평가</h3><p class="stage-note">이 평가는 위 A/B/C 주 선택과 별도로 저장됩니다.</p><label class="field-label" for="secondary">수용도 1~5</label><select id="secondary" class="field-input"><option value="">선택 안 함</option>${[1,2,3,4,5].map((n) => `<option value="${n}">${n}</option>`).join("")}</select>` : ""}<p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">${esc(current.stage)} 제출</button></div></section>`;
  bindActions(() => {
    const choice = document.querySelector('input[name="choice"]:checked');
    const secondary = $("secondary");
    const extra = secondary && secondary.value ? {secondary_evaluation:{artifact_id:current.secondary_evaluation.artifact_id, acceptance:Number(secondary.value), reason:""}} : {};
    const optionAssessments = structuredAssessment ? Object.fromEntries(options.map((option) => [option.policy_option_id, {stance:$(`assessment-${option.policy_option_id}`).value, reason:$(`assessment-reason-${option.policy_option_id}`).value}])) : undefined;
    submitAction(`measurements/${current.stage}`, {choice:choice?.value === "__abstain__" ? null : choice?.value, stance:$("stance")?.value || null, reason:$("reason")?.value || "", confidence:$("confidence").value ? Number($("confidence").value) : null, ...(structuredAssessment ? {option_assessments:optionAssessments} : {}), ...extra}, () => {
      if (!choice) return structuredAssessment ? "정책안 중 하나를 선택해 주세요." : "A/B/C 또는 응답 보류를 선택해 주세요.";
      if (structuredAssessment) {
        for (const option of options) {
          const assessment = optionAssessments[option.policy_option_id];
          if (option.policy_option_id === choice.value && !["accept","conditional"].includes(assessment.stance)) return "선택안은 수용 또는 조건부 수용으로 표시해 주세요.";
          if (option.policy_option_id === choice.value && !assessment.reason.trim()) return "선택안의 수용 또는 조건부 수용 사유를 적어 주세요.";
          if (option.policy_option_id !== choice.value && (assessment.stance !== "reject" || !assessment.reason.trim())) return "선택하지 않은 각 안은 비선택과 사유를 적어 주세요.";
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
function bindActions(primary) { $("step-submit").onclick = primary; const row=$("step-submit").parentElement; const withdraw=document.createElement("button");withdraw.type="button";withdraw.className="external-link";withdraw.textContent="참여 철회";withdraw.onclick=async()=>{if(!confirm("참여를 철회하면 이후 단계를 제출할 수 없습니다. 철회할까요?"))return;const idem=actionKey(`withdraw-${current.stage}`,current.state_revision);try{await api(`/api/aipol/experiments/${encodeURIComponent(experimentId)}/withdraw`,{method:"POST",body:JSON.stringify({reason:"participant-request",expected_revision:current.state_revision,idempotency_key:idem.value})});localStorage.removeItem(idem.key);await load();}catch(e){$("step-error").textContent=e.message;}};row.appendChild(withdraw); }
async function submitAction(path, body, validate) {
  const valid = validate(); if (valid !== true) { $("step-error").textContent = valid; return; }
  const idem = actionKey(current.stage, current.state_revision); $("step-submit").disabled = true;
  try {
    await api(`/api/aipol/experiments/${encodeURIComponent(experimentId)}/${path}`, {method:"POST", body:JSON.stringify({...body, expected_revision:current.state_revision, idempotency_key:idem.value})});
    localStorage.removeItem(idem.key); clearCalculatorIntegration(); await load();
  } catch (error) { $("step-error").textContent = error.message; $("step-submit").disabled = false; }
}
$("register").onclick = register;
$("recover").onclick = recoverParticipant;
$("download-recovery-kit").onclick = downloadRecoveryKit;
$("continue-after-recovery").onclick = continueAfterRecovery;
$("retry").onclick = load;
$("reset-error").onclick = resetParticipant;
$("reset-done").onclick = resetParticipant;
$("reset-withdrawn").onclick = resetParticipant;
load();
