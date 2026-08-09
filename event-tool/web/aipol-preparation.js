"use strict";

let canonicalPreview = null;
let preparationAggregate = null;
let canonicalDrafts = [];
const PREP_CATEGORIES = [
  "policy_options", "calculation", "measurement", "privacy",
  "research_ethics", "source_license", "procedure",
];
const V4_PREP_CATEGORIES = PREP_CATEGORIES.filter((category) => category !== "calculation");
const CALCULATOR_INTEGRATION_VERSION = "aipol-calculator-return-v2";

function prepTextarea(id, label, placeholder = "") {
  return `<label class="field-label" for="${id}">${label}</label><textarea class="field-input" id="${id}" rows="5" placeholder="${esc(placeholder)}"></textarea>`;
}

function prepJson(id, label) {
  try {
    const value = JSON.parse($(id).value || "{}");
    if (!value || Array.isArray(value) || typeof value !== "object") throw new Error();
    return value;
  } catch (_) {
    throw new Error(`${label}은 JSON 객체여야 합니다.`);
  }
}

function prepActor() {
  if (!actor) throw new Error("서명 계정 정보가 없습니다. 다시 로그인해 주세요.");
  return actor;
}

async function prepSafe(path, fallback) {
  try { return await api(path); } catch (_) { return fallback; }
}

function prepStatus(message) {
  $("admin-error").textContent = "";
  const node = $("preparation-status");
  if (node) node.textContent = message;
}

async function refreshPreparation() {
  const rows = await api("/api/admin/aipol/experiments");
  const current = rows.find((item) => item.id === selected.id);
  if (!current) throw new Error("실험을 다시 불러올 수 없습니다.");
  await openPreparation(current);
}

function canonicalRows(documents, drafts, categories = PREP_CATEGORIES) {
  return categories.map((category) => {
    const item = documents.find((value) => value.category === category);
    const draft = drafts.find((value) => value.category === category);
    if (item) {
      return `<article class="proposal-card"><strong>${category}</strong><p class="artifact-meta">승인 완료 · ${esc(item.document_id)} · ${esc(item.content_hash)}</p><p class="artifact-meta">approval_id ${esc(item.approval_id)} · ${esc(item.approved_by)} · 서버 시각 ${esc(item.approved_at)}</p></article>`;
    }
    if (draft) {
      return `<article class="proposal-card"><strong>${category}</strong><p class="artifact-meta">편집자 초안 · ${esc(draft.document_id)} · ${esc(draft.content_hash)}</p><label class="field-label" for="approval-${category}">별도 승인 ID</label><input class="field-input" id="approval-${category}" value="approval-${esc(category)}"><button type="button" class="btn-primary" data-approve-canonical="${category}">동일 해시 재검증 후 승인</button></article>`;
    }
    return `<article class="proposal-card"><strong>${category}</strong><p class="artifact-meta">미등록</p></article>`;
  }).join("");
}

function v4Deliberation(inputs, roundId) {
  return (inputs.deliberations || []).find((item) => item.round_id === roundId);
}

async function openV4Preparation(experiment) {
  const [summary, inputs, documents, drafts] = await Promise.all([
    api(`/api/admin/aipol/experiments/${experiment.id}/summary`),
    api(`/api/admin/aipol/experiments/${experiment.id}/v4-inputs`),
    prepSafe(`/api/admin/aipol/experiments/${experiment.id}/canonical-documents`, []),
    prepSafe(`/api/admin/aipol/experiments/${experiment.id}/canonical-drafts`, []),
  ]);
  canonicalDrafts = drafts;
  const isEditor = experiment.created_by === actor;
  const requiredDocuments = documents.filter((item) => V4_PREP_CATEGORIES.includes(item.category));
  const first = v4Deliberation(inputs, "first");
  const second = v4Deliberation(inputs, "second");
  const artifact = inputs.artifacts || {};
  const issueRun = inputs.generation_runs?.issue_classification || null;
  const councilRun = inputs.generation_runs?.ai_council || null;
  const issueRunCards = (issueRun?.issues || []).map((item) => `
    <article class="proposal-card"><strong>${esc(item.title)}</strong>
      <p>${esc(item.summary)}</p><p class="artifact-meta">실제 M1 의견 ${esc(item.opinion_count)}건 · ${esc(item.issue_id)}</p>
      <p class="artifact-meta">전문가 설명 질문: ${esc(item.expert_prompt)}</p></article>`).join("");
  const councilRunCards = (councilRun?.steps || []).map((item) => `
    <article class="proposal-card"><strong>${esc(item.sequence)}. ${esc(item.role)}</strong>
      <p class="artifact-meta">${esc(item.company)} · ${esc(item.model)} · ${esc(item.phase)}</p>
      <p class="artifact-meta">입력 ${esc(item.input_hash)} · 출력 ${esc(item.output_hash)}</p>
      <pre class="artifact-meta">${esc(JSON.stringify(item.output, null, 2))}</pre></article>`).join("");
  const hashes = inputs.required_d_input_hashes || {};
  const dReady = Object.values(hashes).every((value) => typeof value === "string" && value.length === 64);
  $("detail").classList.remove("hidden");
  $("detail").innerHTML = `
    <h2>${esc(experiment.title)} · v4 운영</h2>
    <p class="stage-note"><strong>개인 연금 계산·개인 영향 단계는 이 절차에 존재하지 않습니다.</strong> D안은 A/B/C와 별도이며 M3 선택지에도 들어가지 않습니다.</p>
    <p class="stage-note">서명 계정: ${esc(actor || "재로그인 필요")} · ${experiment.collection_enabled ? "수집 ON" : "수집 OFF"} · 등록 ${experiment.registration_open ? "OPEN" : "CLOSED"}</p>
    <p>퍼널: 등록 ${summary.funnel.registered || 0} · M1 ${summary.funnel.M1 || 0} · M2 ${summary.funnel.M2 || 0} · M3 ${summary.funnel.M3 || 0}</p>
    <div class="action-row"><a href="/aipol.html?review=process&amp;dataset=pension-v4-20260808-r1" target="_blank" rel="noopener">프로세스 리뷰</a><a href="/aipol.html?experiment=${encodeURIComponent(experiment.id)}" target="_blank" rel="noopener">실제 참가자 화면</a></div>
    <p id="preparation-status" class="artifact-meta" role="status"></p>
    <details open><summary>0. v4 정본 6종 승인·수집 동결 (${requiredDocuments.length}/6)</summary>
      <p class="stage-note">계산 정본은 요구하지 않습니다. 정책안·측정·개인정보·연구윤리·출처 라이선스·절차 정본만 현재 설정 해시에 묶습니다.</p>
      <fieldset ${isEditor ? "" : "disabled"}><legend>편집자 정본 초안 등록</legend>
        <label class="field-label" for="canonical-category">정본 범주</label>
        <select id="canonical-category" class="field-input">${V4_PREP_CATEGORIES.map((category) => `<option value="${category}" ${requiredDocuments.some((item) => item.category === category) ? "disabled" : ""}>${category}</option>`).join("")}</select>
        ${field("canonical-id", "문서 ID")}${field("canonical-version", "문서 버전")}
        ${prepTextarea("canonical-body", "승인 정본 본문")}${prepTextarea("canonical-evidence", "근거 JSON", '{"review":"approved"}')}
        <div class="action-row"><button type="button" id="preview-canonical">서버 해시 미리보기</button><button type="button" id="register-canonical-draft" class="btn-primary" disabled>편집자 초안 등록</button></div>
        <pre id="canonical-preview" class="artifact-meta"></pre>
      </fieldset>
      <div id="canonical-rows">${canonicalRows(requiredDocuments, drafts, V4_PREP_CATEGORIES)}</div>
      ${field("freeze-prep-id", "동결표 ID", "text", "pension-v4-freeze")}
      <button type="button" id="freeze-preparation" class="btn-primary" ${requiredDocuments.length === 6 || experiment.collection_enabled ? "" : "disabled"}>${experiment.collection_enabled ? "수집 동결 완료" : "v4 정본 6종으로 수집 시작"}</button>
    </details>
    <details open><summary>1. 1차 숙의 녹음 요약 → 사람 검수</summary>
      <p class="stage-note">제도 이해와 개인 중심 혜택에 관한 현장 숙의를 요약합니다. 녹음 원문 또는 정리 파일 위치를 출처 메모로 남깁니다.</p>
      ${first ? `<p class="artifact-meta">검수 완료 · ${esc(first.reviewed_by)} · ${esc(first.reviewed_at)} · ${esc(first.content_hash)}</p><p>${esc(first.summary)}</p>` : `${prepTextarea("v4-first-summary", "사람이 검수한 1차 숙의 요약")}${field("v4-first-source", "녹음·AI 요약·사람 검수 출처 메모")}<button type="button" id="save-v4-first" class="btn-primary">1차 숙의 검수본 고정</button>`}
    </details>
    <details open><summary>2. M1 의견 기반 AI 분류 5대 쟁점 → 사람 승인</summary>
      <p class="stage-note">실제 M1 투표·의견 집계 ${inputs.m1.participant_count}명 · 해시 ${esc(inputs.m1.aggregate_hash)}. 관심사를 직접 선택시키지 않고 AI가 의견을 분류·계수한 결과만 등록합니다.</p>
      ${artifact.issue_deliberation ? `<p class="artifact-meta">승인 완료 · ${esc(artifact.issue_deliberation.content_hash)} · ${esc(artifact.issue_deliberation.approved_by)}</p>` : `
        <button type="button" id="run-v4-issues" class="btn-primary" ${inputs.m1.participant_count ? "" : "disabled"}>${issueRun ? "현재 M1 원장으로 AI 분류 다시 실행" : "M1 원장으로 AI 5대 쟁점 분류 실행"}</button>
        ${issueRun ? `<p class="artifact-meta">서버 실행 ${esc(issueRun.run_id)} · ${esc(issueRun.provider)}/${esc(issueRun.model)} · ${esc(issueRun.generated_at)} · ${esc(issueRun.content_hash)}</p>${issueRunCards}
          ${field("v4-issue-id", "자료 ID", "text", "pension-five-issues")}${field("v4-issue-version", "자료 버전", "text", experiment.experiment_version)}${field("v4-issue-title", "사람 검수 후 공개 제목", "text", "1차 투표 의견에서 도출한 5대 핵심 쟁점")}${prepTextarea("v4-issue-body", "사람이 검수한 전문가 설명용 본문")}${field("v4-issue-approval", "사람 승인 ID")}<button type="button" id="approve-v4-issues" class="btn-primary">이 서버 실행 결과를 사람 승인</button>` : ""}`}
    </details>
    <details open><summary>3. 2차 숙의 녹음 요약 → 사람 검수</summary>
      <p class="stage-note">M1 결과 그래프와 5대 쟁점에 대한 전문가 리딩 뒤 진행한 숙의를 기록합니다.</p>
      ${second ? `<p class="artifact-meta">검수 완료 · ${esc(second.reviewed_by)} · ${esc(second.reviewed_at)} · ${esc(second.content_hash)}</p><p>${esc(second.summary)}</p>` : `${prepTextarea("v4-second-summary", "사람이 검수한 2차 숙의 요약")}${field("v4-second-source", "녹음·AI 요약·사람 검수 출처 메모")}<button type="button" id="save-v4-second" class="btn-primary">2차 숙의 검수본 고정</button>`}
    </details>
    <details open><summary>4. M1·숙의1·M2·숙의2 기반 3-AI 협의 D안 → 사람 승인</summary>
      <p class="stage-note">M2 ${inputs.m2.participant_count}명. 네 입력 해시는 서버가 실제 데이터에서 계산하며 수동 변경할 수 없습니다. ${dReady ? "D안 승인 입력 준비 완료" : "두 숙의 검수본과 M1/M2 완료 필요"}</p>
      <pre class="artifact-meta">${esc(JSON.stringify(hashes, null, 2))}</pre>
      ${artifact.ai_opinion ? `<p class="artifact-meta">D안 승인 완료 · ${esc(artifact.ai_opinion.content_hash)} · ${esc(artifact.ai_opinion.approved_by)}</p>` : `
        <button type="button" id="run-v4-council" class="btn-primary" ${dReady ? "" : "disabled"}>${councilRun ? "현재 네 입력으로 3-AI 협의 다시 실행" : "3-AI 제안→상호검토→수정 실행"}</button>
        ${councilRun ? `<p class="artifact-meta">서버 실행 ${esc(councilRun.run_id)} · ${esc(councilRun.generated_at)} · ${esc(councilRun.content_hash)}</p>${councilRunCards}
          <article class="proposal-card"><strong>${esc(councilRun.final_content.title)}</strong><p>${esc(councilRun.final_content.body)}</p><p class="stage-note">한계와 의의: ${esc(councilRun.final_content.limitations)}</p></article>
          ${field("v4-d-id", "D안 자료 ID", "text", "pension-council-d")}${field("v4-d-version", "D안 버전", "text", experiment.experiment_version)}${field("v4-d-approval", "사람 승인 ID")}<button type="button" id="approve-v4-d" class="btn-primary">이 3-AI 협의 결과를 사람 승인</button>` : ""}`}
    </details>
    <details open><summary>5. 전문가 D안 설명·한계·질의응답 안내 승인</summary>
      ${artifact.expert_explanation ? `<p class="artifact-meta">승인 완료 · ${esc(artifact.expert_explanation.content_hash)} · ${esc(artifact.expert_explanation.approved_by)}</p>` : `${field("v4-expert-id", "자료 ID", "text", "pension-d-expert")}${field("v4-expert-version", "자료 버전", "text", experiment.experiment_version)}${field("v4-expert-title", "제목", "text", "D안의 의의와 한계")}${prepTextarea("v4-expert-body", "전문가 설명·한계·질의응답 안내")}${field("v4-expert-approval", "사람 승인 ID")}<button type="button" id="save-v4-expert" class="btn-primary">전문가 설명 승인</button>`}
    </details>`;
  $("preview-canonical").onclick = previewCanonical;
  $("register-canonical-draft").onclick = registerCanonicalDraft;
  document.querySelectorAll("[data-approve-canonical]").forEach((button) => {
    button.onclick = () => approveCanonical(button.dataset.approveCanonical);
  });
  $("freeze-preparation").onclick = experiment.collection_enabled
    ? null
    : () => freezePreparation(requiredDocuments, V4_PREP_CATEGORIES);
  if ($("save-v4-first")) $("save-v4-first").onclick = () => saveV4Deliberation("first");
  if ($("save-v4-second")) $("save-v4-second").onclick = () => saveV4Deliberation("second");
  if ($("run-v4-issues")) $("run-v4-issues").onclick = runV4Issues;
  if ($("approve-v4-issues")) $("approve-v4-issues").onclick = () => approveV4Issues(issueRun.run_id);
  if ($("run-v4-council")) $("run-v4-council").onclick = runV4Council;
  if ($("approve-v4-d")) $("approve-v4-d").onclick = () => approveV4D(councilRun.run_id);
  if ($("save-v4-expert")) $("save-v4-expert").onclick = saveV4Expert;
}

async function saveV4Deliberation(roundId) {
  try {
    const prefix = roundId === "first" ? "v4-first" : "v4-second";
    await api(`/api/admin/aipol/experiments/${selected.id}/v4-deliberations/${roundId}`, {
      method: "POST",
      body: JSON.stringify({summary: $(`${prefix}-summary`).value.trim(), source_note: $(`${prefix}-source`).value.trim(), reviewed_by: prepActor()}),
    });
    await refreshPreparation();
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function saveV4Artifact(payload) {
  return api(`/api/admin/aipol/experiments/${selected.id}/artifacts`, {
    method: "POST",
    body: JSON.stringify({...payload, approved_by: prepActor(), fallback_used: false}),
  });
}

async function runV4Issues() {
  try {
    prepStatus("실제 M1 의견을 AI가 분류하고 있습니다…");
    await api(`/api/admin/aipol/experiments/${selected.id}/v4-issue-classification/run`, {method: "POST", body: "{}"});
    await refreshPreparation();
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function approveV4Issues(runId) {
  try {
    await api(`/api/admin/aipol/experiments/${selected.id}/v4-issue-classification/approve`, {method: "POST", body: JSON.stringify({run_id: runId, artifact_id: $("v4-issue-id").value.trim(), artifact_version: $("v4-issue-version").value.trim(), title: $("v4-issue-title").value.trim(), body: $("v4-issue-body").value.trim(), approval_id: $("v4-issue-approval").value.trim()})});
    await refreshPreparation();
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function runV4Council() {
  try {
    prepStatus("세 개 독립 AI가 제안→상호검토→수정을 순서대로 실행하고 있습니다…");
    await api(`/api/admin/aipol/experiments/${selected.id}/v4-council/run`, {method: "POST", body: "{}"});
    await refreshPreparation();
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function approveV4D(runId) {
  try {
    await api(`/api/admin/aipol/experiments/${selected.id}/v4-council/approve`, {method: "POST", body: JSON.stringify({run_id: runId, artifact_id: $("v4-d-id").value.trim(), artifact_version: $("v4-d-version").value.trim(), approval_id: $("v4-d-approval").value.trim()})});
    await refreshPreparation();
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function saveV4Expert() {
  try {
    await saveV4Artifact({kind: "expert_explanation", artifact_id: $("v4-expert-id").value.trim(), artifact_version: $("v4-expert-version").value.trim(), content: {title: $("v4-expert-title").value.trim(), body: $("v4-expert-body").value.trim()}, approval_id: $("v4-expert-approval").value.trim()});
    await refreshPreparation();
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function openPreparation(experiment) {
  selected = experiment;
  canonicalPreview = null;
  if (experiment.procedure_config?.version === "aipol-pension-deliberation-v4") {
    await openV4Preparation(experiment);
    return;
  }
  const [summary, documents, drafts, publicInputs] = await Promise.all([
    api(`/api/admin/aipol/experiments/${experiment.id}/summary`),
    prepSafe(`/api/admin/aipol/experiments/${experiment.id}/canonical-documents`, []),
    prepSafe(`/api/admin/aipol/experiments/${experiment.id}/canonical-drafts`, []),
    prepSafe(`/api/admin/aipol/experiments/${experiment.id}/public-audience-inputs`, null),
  ]);
  const aggregate = preparationAggregate?.experiment_id === experiment.id
    ? preparationAggregate : null;
  canonicalDrafts = drafts;
  const calculation = documents.find((item) => item.category === "calculation");
  const isEditor = experiment.created_by === actor;
  $("detail").classList.remove("hidden");
  $("detail").innerHTML = `
    <h2>${esc(experiment.title)}</h2>
    <p class="stage-note">서명 계정: ${esc(actor || "재로그인 필요")} · 생성 편집자: ${esc(experiment.created_by)} · ${experiment.collection_enabled ? "수집 ON" : "수집 OFF"} · 등록 ${experiment.registration_open ? "OPEN" : "CLOSED"} · E2 ${experiment.e2_released ? "공개" : "대기"}</p>
    <p>퍼널: 등록 ${summary.funnel.registered || 0} · M1 ${summary.funnel.M1 || 0} · M2 ${summary.funnel.M2 || 0} · M3 ${summary.funnel.M3 || 0}</p>
    <p><a href="/aipol.html?experiment=${encodeURIComponent(experiment.id)}" target="_blank" rel="noopener">참가자 화면 열기</a></p>
    <p id="preparation-status" class="artifact-meta" role="status"></p>
    <details open><summary>1. 정본 문서 7종: 편집자 미리보기 → 별도 승인자 승인 (${documents.length}/7)</summary>
      <p class="stage-note">${isEditor ? "현재 계정은 생성 편집자입니다. 서버 해시를 확인하고 초안을 등록한 뒤 계정 전환을 누르세요." : "승인 계정은 편집자 초안의 전체 내용을 서버에 다시 보내 해시가 같은 경우에만 승인합니다."} 서버가 approval_id·approved_by·approved_at·content_hash를 보존합니다.</p>
      <fieldset ${isEditor ? "" : "disabled"}><legend>편집자 정본 초안 등록</legend>
        <label class="field-label" for="canonical-category">정본 범주</label>
        <select id="canonical-category" class="field-input">${PREP_CATEGORIES.map((category) => `<option value="${category}" ${documents.some((item) => item.category === category) ? "disabled" : ""}>${category}</option>`).join("")}</select>
        ${field("canonical-id", "문서 ID")}${field("canonical-version", "문서 버전")}
        ${prepTextarea("canonical-body", "승인 정본 본문")}${prepTextarea("canonical-evidence", "근거 JSON", '{"review":"approved"}')}
        <div class="action-row"><button type="button" id="preview-canonical">서버 해시 미리보기</button><button type="button" id="register-canonical-draft" class="btn-primary" disabled>편집자 초안 등록</button></div>
        <pre id="canonical-preview" class="artifact-meta"></pre>
      </fieldset>
      <div id="canonical-rows">${canonicalRows(documents, drafts)}</div>
    </details>
    <details open><summary>2. E1a 개인 조건 비교 도구 승인본</summary>
      <p class="stage-note">calculation 정본과 동일한 canonical/build/receipt/integration 해시 및 정확한 HTTPS launch origin을 결합합니다.</p>
      ${field("pc-id", "도구 ID")}${field("pc-version", "도구·계산 버전")}${field("pc-title", "표시 제목")}${field("pc-url", "승인 HTTPS launch URL")}${field("pc-origin", "정확한 HTTPS launch origin", "url", "https://calculator.example")}
      ${prepTextarea("pc-limitations", "한계 안내")}${field("pc-canonical", "canonical_document_hash")}${field("pc-build", "build_hash")}${field("pc-receipt", "receipt_contract_hash")}${field("pc-integration-test", "integration_test_hash")}${field("pc-approval", "승인 ID")}
      <p class="artifact-meta">integration_contract_version: ${CALCULATOR_INTEGRATION_VERSION}</p>
      <button type="button" id="save-personal" class="btn-primary">E1a 승인본 등록</button><p id="personal-result" class="artifact-meta" role="status"></p>
    </details>
    <details open><summary>3. E1b 전문가 설명 승인본</summary>
      ${field("expert-id", "자료 ID")}${field("expert-version", "자료 버전")}${field("expert-title", "제목")}${prepTextarea("expert-body", "승인된 전문가 설명 본문")}${field("expert-approval", "승인 ID")}
      <button type="button" id="save-expert" class="btn-primary">E1b 승인본 등록</button><p id="expert-result" class="artifact-meta" role="status"></p>
    </details>
    <details open><summary>4. E2 AI primary/fallback 후보 provenance</summary>
      <p class="stage-note">fallback은 동결 전에 준비합니다. primary는 등록 마감·attrition 처리·M2 최종 확정 뒤 전용 candidates API로 등록합니다. 확정 M2 aggregate: ${esc(aggregate?.aggregate_hash || "아직 확정되지 않음")}</p>
      <label class="field-label" for="ai-role">후보 역할</label><select id="ai-role" class="field-input"><option value="fallback">fallback</option><option value="primary">primary</option></select>
      ${field("ai-id", "후보 자료 ID")}${field("ai-version", "자료 버전")}${field("ai-title", "제목")}${prepTextarea("ai-body", "승인할 AI 의견 본문")}
      ${field("ai-model", "모델")}${field("ai-deployment", "배포 이름")}${field("ai-prompt", "프롬프트 버전")}${field("ai-generated", "생성 시각", "datetime-local")}${field("ai-evidence", "evidence 식별자(쉼표 구분)")}${field("ai-m2-hash", "M2 aggregate SHA-256")}${field("ai-approval", "승인 ID")}
      <button type="button" id="save-ai" class="btn-primary">AI 후보 승인 등록</button><p id="ai-result" class="artifact-meta" role="status"></p>
    </details>
    <details open><summary>5. 동결 → 등록 마감 → attrition → M2 최종 확정 → E2 공개</summary>
      ${field("freeze-prep-id", "동결표 ID")}<button type="button" id="freeze-preparation" class="btn-primary" ${documents.length === 7 ? "" : "disabled"}>서버 승인 7종으로 수집 동결</button>
      <div class="action-row"><button type="button" id="close-preparation-registration">참가자 등록 마감</button><button type="button" id="refresh-m2">M2 최종 확정 확인</button></div>
      ${prepTextarea("attrition-reason", "M2 미완료 참가자의 감사 가능한 attrition 사유")}<button type="button" id="mark-attrition">대기 참가자 attrition 처리</button>
      <p id="m2-finalization" class="artifact-meta" role="status">${aggregate ? `M2 확정 · ${esc(aggregate.aggregate_hash)} · ${esc(aggregate.cohort_finalized_at)}` : "M2 미확정"}</p>
      <label class="field-label" for="release-role">공개 후보</label><select id="release-role" class="field-input"><option value="primary">primary</option><option value="fallback">fallback</option></select>
      ${prepTextarea("release-reason", "사람의 선택 사유")}<button type="button" id="release-candidate" class="btn-primary">선택 근거와 함께 E2 공개</button>
    </details>
    ${publicInputs ? `<details open><summary>6. 공개 청중 의견 진행자 선별 입력 (${publicInputs.input_count})</summary>
      <p class="stage-note">현장에서 공개로 발언된 의견 중 진행자가 AI 수정 의견 D′에 반영할 내용만 등록합니다. 등록한 순번·내용은 변경·삭제할 수 없습니다. 참가자 개인 텍스트 입력은 받지 않습니다.</p>
      ${field("public-audience-sequence", "공개 발언 순번", "number", String(publicInputs.input_count + 1))}
      ${prepTextarea("public-audience-statement", "진행자가 선별한 공개 청중 의견")}
      <button type="button" id="save-public-audience-input" class="btn-primary">선별 공개 의견 등록</button>
      <p id="public-audience-result" class="artifact-meta" role="status"></p>
      <div>${publicInputs.inputs.length ? publicInputs.inputs.map((item) => `<article class="proposal-card"><strong>${item.sequence}. ${esc(item.statement)}</strong><p class="artifact-meta">진행자 ${esc(item.selected_by)} · ${esc(item.selected_at)}</p></article>`).join("") : "<p class='muted'>아직 선별 등록된 공개 청중 의견이 없습니다.</p>"}</div>
    </details>` : ""}`;

  if (calculation) $("pc-canonical").value = calculation.content_hash;
  if (aggregate) $("ai-m2-hash").value = aggregate.aggregate_hash;
  $("preview-canonical").onclick = previewCanonical;
  $("register-canonical-draft").onclick = registerCanonicalDraft;
  document.querySelectorAll("[data-approve-canonical]").forEach((button) => {
    button.onclick = () => approveCanonical(button.dataset.approveCanonical);
  });
  $("save-personal").onclick = savePersonal;
  $("save-expert").onclick = saveExpert;
  $("save-ai").onclick = saveAiCandidate;
  $("freeze-preparation").onclick = () => freezePreparation(documents);
  $("close-preparation-registration").onclick = closePreparationRegistration;
  $("mark-attrition").onclick = markPendingAttrition;
  $("refresh-m2").onclick = refreshM2Finalization;
  $("release-candidate").onclick = releaseCandidate;
  if ($("save-public-audience-input")) {
    $("public-audience-sequence").value = String(publicInputs.input_count + 1);
    $("save-public-audience-input").onclick = savePublicAudienceInput;
  }
}

async function previewCanonical() {
  try {
    const request = {category: $("canonical-category").value, document_id: $("canonical-id").value.trim(), document_version: $("canonical-version").value.trim(), body: $("canonical-body").value.trim(), evidence: prepJson("canonical-evidence", "근거")};
    const result = await api(`/api/admin/aipol/experiments/${selected.id}/canonical-documents/preview`, {method: "POST", body: JSON.stringify(request)});
    canonicalPreview = {request, content_hash: result.content_hash, bound_settings_hash: result.bound_settings_hash};
    $("canonical-preview").textContent = `content_hash: ${result.content_hash}\nbound_settings_hash: ${result.bound_settings_hash}`;
    $("register-canonical-draft").disabled = false;
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function registerCanonicalDraft() {
  try {
    if (!canonicalPreview) throw new Error("먼저 서버 해시를 미리보기해 주세요.");
    if (selected.created_by !== prepActor()) throw new Error("실험 생성 편집자만 초안을 등록할 수 있습니다.");
    await api(`/api/admin/aipol/experiments/${selected.id}/canonical-drafts`, {
      method: "POST",
      body: JSON.stringify({...canonicalPreview.request, declared_content_hash: canonicalPreview.content_hash}),
    });
    await refreshPreparation();
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function approveCanonical(category) {
  try {
    const draft = canonicalDrafts.find((value) => value.category === category);
    if (!draft) throw new Error("편집자 초안을 찾을 수 없습니다.");
    if (draft.editor_by === prepActor()) throw new Error("편집자와 승인자는 서로 다른 서명 계정이어야 합니다. 계정을 전환해 주세요.");
    const request = {category: draft.category, document_id: draft.document_id, document_version: draft.document_version, body: draft.body, evidence: draft.evidence};
    const preview = await api(`/api/admin/aipol/experiments/${selected.id}/canonical-documents/preview`, {method: "POST", body: JSON.stringify(request)});
    if (preview.content_hash !== draft.content_hash || preview.bound_settings_hash !== draft.bound_settings_hash) throw new Error(`${category} 서버 해시가 편집자 초안과 달라 승인을 중단했습니다.`);
    const saved = await api(`/api/admin/aipol/experiments/${selected.id}/canonical-documents`, {method: "POST", body: JSON.stringify({...request, declared_content_hash: draft.content_hash, approval_id: $(`approval-${category}`).value.trim(), approved_by: prepActor()})});
    prepStatus(`${category} 승인 완료: ${saved.approval_id} · ${saved.approved_at}`);
    await refreshPreparation();
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function savePersonal() {
  try {
    const saved = await api(`/api/admin/aipol/experiments/${selected.id}/artifacts`, {method: "POST", body: JSON.stringify({kind: "personal_comparison", artifact_id: $("pc-id").value.trim(), artifact_version: $("pc-version").value.trim(), content: {title: $("pc-title").value.trim(), launch_url: $("pc-url").value.trim(), launch_origin: $("pc-origin").value.trim(), calculation_version: $("pc-version").value.trim(), limitations: $("pc-limitations").value.trim(), canonical_document_hash: $("pc-canonical").value.trim(), build_hash: $("pc-build").value.trim(), receipt_contract_hash: $("pc-receipt").value.trim(), integration_contract_version: CALCULATOR_INTEGRATION_VERSION, integration_test_hash: $("pc-integration-test").value.trim()}, approval_id: $("pc-approval").value.trim(), approved_by: prepActor(), fallback_used: false})});
    $("personal-result").textContent = `승인 ${saved.approval_id} · ${saved.content_hash} · 서버 시각 ${saved.approved_at}`;
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function saveExpert() {
  try {
    const saved = await api(`/api/admin/aipol/experiments/${selected.id}/artifacts`, {method: "POST", body: JSON.stringify({kind: "expert_explanation", artifact_id: $("expert-id").value.trim(), artifact_version: $("expert-version").value.trim(), content: {title: $("expert-title").value.trim(), body: $("expert-body").value.trim()}, approval_id: $("expert-approval").value.trim(), approved_by: prepActor(), fallback_used: false})});
    $("expert-result").textContent = `승인 ${saved.approval_id} · ${saved.content_hash} · 서버 시각 ${saved.approved_at}`;
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function saveAiCandidate() {
  try {
    const role = $("ai-role").value;
    const content = {title: $("ai-title").value.trim(), body: $("ai-body").value.trim()};
    if (selected.procedure_config?.version === "aipol-pension-3-measurements-v3") {
      content.lever_values = Object.fromEntries(
        [...new Set((selected.policy_options || []).flatMap((option) => Object.keys(option.lever_values || {})))]
          .map((key) => [key, `D: ${key}`]),
      );
    }
    const saved = await api(`/api/admin/aipol/experiments/${selected.id}/ai-candidates`, {method: "POST", body: JSON.stringify({candidate_role: role, artifact_id: $("ai-id").value.trim(), artifact_version: $("ai-version").value.trim(), content, model: $("ai-model").value.trim(), deployment: $("ai-deployment").value.trim(), prompt_version: $("ai-prompt").value.trim(), generated_at: approvedAt("ai-generated"), evidence_refs: $("ai-evidence").value.split(",").map((value) => value.trim()).filter(Boolean), m2_aggregate_hash: role === "primary" ? $("ai-m2-hash").value.trim() : null, approval_id: $("ai-approval").value.trim(), approved_by: prepActor()})});
    $("ai-result").textContent = `${role} 승인 ${saved.approval_id} · ${saved.content_hash} · 서버 시각 ${saved.approved_at}`;
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function freezePreparation(documents, requiredCategories = PREP_CATEGORIES) {
  try {
    const approved = documents.filter((item) => requiredCategories.includes(item.category));
    if (approved.length !== requiredCategories.length) throw new Error(`정본 문서 ${requiredCategories.length}종을 모두 승인해 주세요.`);
    const body = {manifest_id: $("freeze-prep-id").value.trim(), experiment_version: selected.experiment_version, option_set_version: selected.measurement_spec.option_set_version, measurement_spec_hash: selected.measurement_spec_hash, status: "frozen", collection_enabled: true, approvals: approved.map((item) => ({category: item.category, approval_id: item.approval_id, approved_by: item.approved_by, approved_at: item.approved_at, content_hash: item.content_hash}))};
    await api(`/api/admin/aipol/experiments/${selected.id}/freeze`, {method: "PUT", body: JSON.stringify(body)});
    await load();
    await refreshPreparation();
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function closePreparationRegistration() {
  try { await api(`/api/admin/aipol/experiments/${selected.id}/close-registration`, {method: "POST"}); await refreshPreparation(); }
  catch (error) { $("admin-error").textContent = error.message; }
}

async function markPendingAttrition() {
  try {
    const result = await api(`/api/admin/aipol/experiments/${selected.id}/mark-pending-attrition`, {method: "POST", body: JSON.stringify({reason: $("attrition-reason").value.trim()})});
    prepStatus(`attrition ${result.attrited_count || 0}명 처리 완료`);
    await refreshPreparation();
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function refreshM2Finalization() {
  try {
    const aggregate = await api(`/api/admin/aipol/experiments/${selected.id}/m2-aggregate`);
    preparationAggregate = {...aggregate, experiment_id: selected.id};
    $("m2-finalization").textContent = `M2 확정 · ${aggregate.aggregate_hash} · ${aggregate.cohort_finalized_at}`;
    $("ai-m2-hash").value = aggregate.aggregate_hash;
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function releaseCandidate() {
  try {
    await api(`/api/admin/aipol/experiments/${selected.id}/release-e2`, {method: "POST", body: JSON.stringify({candidate_role: $("release-role").value, selection_reason: $("release-reason").value.trim()})});
    await refreshPreparation();
  } catch (error) { $("admin-error").textContent = error.message; }
}

async function savePublicAudienceInput() {
  try {
    const sequence = Number($("public-audience-sequence").value);
    const statement = $("public-audience-statement").value.trim();
    if (!Number.isInteger(sequence) || sequence < 1) throw new Error("공개 발언 순번은 1 이상의 정수여야 합니다.");
    if (!statement) throw new Error("진행자가 선별한 공개 청중 의견을 입력해 주세요.");
    const saved = await api(`/api/admin/aipol/experiments/${selected.id}/public-audience-inputs`, {
      method: "POST",
      body: JSON.stringify({sequence, statement, idempotency_key: crypto.randomUUID()}),
    });
    await refreshPreparation();
    if ($("public-audience-result")) {
      $("public-audience-result").textContent = `${saved.sequence}번 공개 의견 등록 완료 · ${saved.selected_at}`;
    }
  } catch (error) { $("admin-error").textContent = error.message; }
}

window.openAipolPreparation = openPreparation;
$("switch-account").onclick = () => {
  sessionStorage.removeItem("aipol:admin");
  sessionStorage.removeItem("aipol:actor");
  location.reload();
};
