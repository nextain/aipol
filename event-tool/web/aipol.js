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
    if (current.procedure_version === "aipol-pension-3-measurements-v2") {
      $("procedure-summary").textContent = "1차 선택, 개인 비교와 2차 의견, 잠정 의견 D, 전문가·청중 의견, 수정 의견 D′ 뒤 최종 선택을 남깁니다.";
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
  const labels = {consent:"동의", M1:"1차 선택", E1a:"개인 조건 비교", M2:"2차 선택", E2:"잠정 의견 D", E1b:"전문가 논평", A1:"공개 청중 의견", E3:"수정 의견 D′", M3:"3차 선택"};
  $("step-line").textContent = `${labels[current.stage] || current.stage} · 기록 버전 ${current.state_revision}`;
  if ((current.stage === "E2" && current.waiting_for_e2_release) || (current.stage === "E3" && current.waiting_for_e3_release)) renderWaiting();
  else if (current.stage === "consent") renderConsent();
  else if (["E1a","E1b","E2","E3"].includes(current.stage)) renderExposure();
  else if (current.stage === "A1") renderAudienceDiscussion();
  else renderMeasurement();
  const heading=document.querySelector("#step-content h2");if(heading){heading.tabIndex=-1;heading.focus();}
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
  clearCalculatorIntegration();
  const integrationReady = isPersonal && current.calculator_integration && current.receipt_context;
  const link = isPersonal && !syntheticReview ? `<button id="launch-calculator" class="external-link" type="button" ${integrationReady ? "" : "disabled"}>승인된 비교 도구 열기 ↗</button>` : "";
  const receipt = syntheticReview
    ? `<p class="stage-note">합성 검토에서는 외부 계산기 영수증을 생략합니다. 아래 자료와 전체 진행 흐름만 검토해 주세요.</p>`
    : isPersonal ? `<p id="calculator-status" class="stage-note" role="status" aria-live="polite">${integrationReady ? "비교 도구를 열어 완료 증명을 받아 주세요." : "승인된 계산기 연동 계약을 사용할 수 없어 진행할 수 없습니다."}</p><section id="manual-receipt" class="step-card hidden"><h3>서명 영수증 직접 입력</h3><p class="stage-note">자동 전달을 지원하지 않거나 시간이 초과되면 계산기가 표시한 flattened JWS JSON을 붙여 넣으세요. 서버가 서명과 행사 문맥을 다시 검증합니다.</p><textarea id="manual-receipt-value" maxlength="25000" rows="5"></textarea><button id="accept-manual-receipt" class="external-link" type="button">서명 영수증 확인</button><p id="manual-receipt-error" class="error-inline" role="alert"></p></section>` : "";
  $("step-content").innerHTML = `<section class="step-card"><h2>${esc(title)}</h2><p>${esc(body)}</p>${link}<p class="artifact-meta">자료 ${esc(artifact.artifact_id)} · 버전 ${esc(artifact.artifact_version)} · 승인 ${esc(artifact.approval_id)}<br>해시 ${esc(artifact.content_hash)}</p>${isPersonal ? '<p class="stage-note">소득 등 개인 입력 원값은 이 행사 서버로 보내지 않습니다.</p>' : ''}${receipt}<label class="option-choice"><input id="read-check" type="checkbox"><span>자료를 확인했습니다.</span></label><p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">확인 완료</button></div></section>`;
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
  const structuredM2 = current.stage === "M2" && current.procedure_version === "aipol-pension-3-measurements-v2";
  const stance = structuredM2 ? `<label class="field-label" for="stance">선택한 안에 대한 판단</label><select id="stance" class="field-input"><option value="">선택해 주세요</option><option value="accept">수용</option><option value="conditional">조건부 수용</option><option value="reject">비선택</option></select>` : "";
  const reasonLabel = structuredM2 ? "선택 이유 (조건부 수용·비선택은 필수)" : "선택 이유 (선택)";
  $("step-content").innerHTML = `<section class="step-card"><h2>${esc(current.stage.replace("M", ""))}차 선택</h2><p>${esc(current.question_text || current.question_id)}</p><div class="option-list">${options.map((option) => `<label class="option-choice"><input type="radio" name="choice" value="${esc(option.policy_option_id)}"><span><strong>${esc(option.policy_option_id)} · ${esc(option.label)}</strong><small>정책 버전 ${esc(option.policy_version)}</small></span></label>`).join("")}<label class="option-choice"><input type="radio" name="choice" value="__abstain__"><span><strong>응답 보류</strong><small>주 선택은 무응답으로 기록됩니다.</small></span></label></div>${stance}<label class="field-label" for="reason">${reasonLabel}</label><p class="artifact-meta">이름·연락처·소속 등 개인을 알아볼 수 있는 정보는 적지 마세요.</p><textarea id="reason" maxlength="2000"></textarea><label class="field-label" for="confidence">선택 확신도 1~5</label><select id="confidence" class="field-input"><option value="">선택 안 함</option>${[1,2,3,4,5].map((n) => `<option value="${n}">${n}</option>`).join("")}</select>${current.stage === "M3" && current.secondary_evaluation ? `<hr><h3>AI가 제시한 별도 안 평가</h3><p class="stage-note">이 평가는 위 A/B/C 주 선택과 별도로 저장됩니다.</p><label class="field-label" for="secondary">수용도 1~5</label><select id="secondary" class="field-input"><option value="">선택 안 함</option>${[1,2,3,4,5].map((n) => `<option value="${n}">${n}</option>`).join("")}</select>` : ""}<p id="step-error" class="error-inline" role="alert" aria-live="polite"></p><div class="action-row"><button id="step-submit" class="btn-primary">${esc(current.stage)} 제출</button></div></section>`;
  bindActions(() => {
    const choice = document.querySelector('input[name="choice"]:checked');
    const secondary = $("secondary");
    const extra = secondary && secondary.value ? {secondary_evaluation:{artifact_id:current.secondary_evaluation.artifact_id, acceptance:Number(secondary.value), reason:""}} : {};
    submitAction(`measurements/${current.stage}`, {choice:choice?.value === "__abstain__" ? null : choice?.value, stance:$("stance")?.value || null, reason:$("reason").value, confidence:$("confidence").value ? Number($("confidence").value) : null, ...extra}, () => {
      if (!choice) return "A/B/C 또는 응답 보류를 선택해 주세요.";
      const decision = $("stance")?.value;
      if (structuredM2 && !decision) return "수용, 조건부 수용, 비선택 중 하나를 선택해 주세요.";
      if (structuredM2 && ["conditional", "reject"].includes(decision) && !$("reason").value.trim()) return "조건부 수용과 비선택에는 이유를 적어 주세요.";
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
