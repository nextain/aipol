(() => {
  "use strict";

  const query = new URLSearchParams(location.search);
  const experimentId = query.get("experiment") || "";
  const planningMode = query.get("mode") === "planning";
  const fragment = new URLSearchParams(location.hash.replace(/^#/, ""));
  let pendingReviewToken = fragment.get("review_token") || "";
  let exchangeNonce = "";
  if (pendingReviewToken) {
    const nonceBytes = crypto.getRandomValues(new Uint8Array(32));
    exchangeNonce = btoa(String.fromCharCode(...nonceBytes))
      .replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
  }
  const initialStage = query.get("stage") || "intro";
  if (location.hash) history.replaceState(null, "", `${location.pathname}${location.search}`);

  const status = document.querySelector("#review-status");
  const content = document.querySelector("#review-content");
  const disclosure = document.querySelector("#review-disclosure");
  const stageList = document.querySelector("#review-stage-list");
  const snapshot = document.querySelector("#review-snapshot");
  const expiry = document.querySelector("#review-expiry");
  const retry = document.querySelector("#review-retry");
  const previous = document.querySelector("#review-previous");
  const next = document.querySelector("#review-next");
  const reset = document.querySelector("#review-reset");
  let catalog = null;
  let stageIndex = 0;
  let retryAction = null;
  let loadSerial = 0;
  let activeLoad = null;

  const text = value => String(value ?? "");

  const selectedStage = () => new URLSearchParams(location.search).get("stage") || initialStage;

  function enableExchangeRetry() {
    retryAction = () => exchange().then(() => load(selectedStage(), "replace"));
  }

  async function exchange() {
    if (!pendingReviewToken) return;
    let response;
    try {
      response = await fetch("/api/aipol/review/exchange", {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          experiment_id: experimentId,
          review_token: pendingReviewToken,
          exchange_nonce: exchangeNonce,
        }),
      });
    } catch (error) {
      enableExchangeRetry();
      throw new Error("네트워크 연결을 확인한 뒤 다시 시도해 주세요.");
    }
    if (!response.ok) {
      if (response.status === 429 || response.status >= 500) {
        enableExchangeRetry();
        throw new Error("검토 연결이 지연되고 있습니다. 잠시 뒤 다시 시도해 주세요.");
      }
      pendingReviewToken = "";
      exchangeNonce = "";
      retryAction = null;
      throw new Error("검토 링크가 만료되었거나 철회되었습니다.");
    }
    pendingReviewToken = "";
    exchangeNonce = "";
  }

  function writeStageUrl(stage, mode) {
    const params = new URLSearchParams(location.search);
    if (experimentId) params.set("experiment", experimentId);
    params.set("stage", stage);
    history[mode === "push" ? "pushState" : "replaceState"](
      {stage}, "", `${location.pathname}?${params.toString()}`,
    );
  }

  function setBusy(busy) {
    content.setAttribute("aria-busy", String(busy));
    stageList.querySelectorAll("button").forEach(button => { button.disabled = busy; });
    previous.disabled = busy || !catalog || stageIndex === 0;
    next.disabled = busy || !catalog || stageIndex === catalog.stages.length - 1;
    reset.disabled = busy || !catalog;
    retry.disabled = busy;
  }

  async function load(stage = "intro", historyMode = "replace") {
    const serial = ++loadSerial;
    if (activeLoad) activeLoad.abort();
    const controller = new AbortController();
    activeLoad = controller;
    setBusy(true);
    try {
      const catalogUrl = planningMode
        ? `/api/aipol/review/planning/catalog?stage=${encodeURIComponent(stage)}`
        : `/api/aipol/review/${encodeURIComponent(experimentId)}/catalog?stage=${encodeURIComponent(stage)}`;
      const response = await fetch(
        catalogUrl,
        {credentials: "same-origin", cache: "no-store", signal: controller.signal},
      );
      if (!response.ok) {
        if (response.status === 429 || response.status >= 500) {
          retryAction = () => load(stage, "replace");
          throw new Error("검토 자료 연결이 지연되고 있습니다. 다시 시도해 주세요.");
        }
        retryAction = null;
        throw new Error("검토 세션을 확인할 수 없습니다. 새 링크를 요청해 주세요.");
      }
      const payload = await response.json();
      if (serial !== loadSerial) return;
      catalog = payload.catalog;
      stageIndex = catalog.stages.findIndex(item => item.id === payload.current_stage_id);
      if (stageIndex < 0) throw new Error("검토 단계 계약이 올바르지 않습니다.");
      retryAction = null;
      retry.hidden = true;
      writeStageUrl(payload.current_stage_id, historyMode);
      render(payload.snapshot_hash, payload.expires_at, payload.scope);
    } catch (error) {
      if (error.name !== "AbortError") {
        if (error instanceof TypeError) {
          retryAction = () => load(stage, "replace");
          throw new Error("네트워크 연결을 확인한 뒤 다시 시도해 주세요.");
        }
        throw error;
      }
    } finally {
      if (serial === loadSerial) {
        activeLoad = null;
        setBusy(false);
      }
    }
  }

  function policyTable(extra = null) {
    const headings = catalog.policy_columns.map(value => `<th scope="col">${escapeHtml(value)}</th>`).join("");
    const options = extra ? [...catalog.policy_options, extra] : catalog.policy_options;
    const rows = options.map(option => `
      <tr>
        <th scope="row">${escapeHtml(option.id)}안</th>
        <td>${escapeHtml(option.start_age)}</td>
        <td>${escapeHtml(option.fund_strategy)}</td>
        <td>${escapeHtml(option.government_support)}</td>
      </tr>`).join("");
    return `<div class="table-scroll" role="region" aria-label="정책안 비교표" tabindex="0"><table><caption>정책안 비교</caption><thead><tr><th scope="col">정책안</th>${headings}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function escapeHtml(value) {
    const node = document.createElement("span");
    node.textContent = text(value);
    return node.innerHTML;
  }

  function listBlock(title, values) {
    if (!Array.isArray(values) || values.length === 0) return "";
    return `<section class="contract-block"><h3>${escapeHtml(title)}</h3><ul>${values.map(
      value => `<li>${escapeHtml(value)}</li>`
    ).join("")}</ul></section>`;
  }

  function stageDetails(stage) {
    return [
      listBlock("입력", stage.input_contract),
      listBlock("화면·출력", stage.output_contract),
      listBlock("분석 변수", stage.grouping_variables),
      listBlock("생성 입력", stage.generation_inputs),
      listBlock("수치 경계", stage.bounds),
      stage.discussion_scope
        ? listBlock("논의 범위", [stage.discussion_scope]) : "",
      listBlock("선택지", stage.choice_set),
      listBlock("검토 포인트", stage.review_points),
    ].join("");
  }

  function resultTable(headings, rows) {
    return `<div class="table-scroll result-view" role="region" aria-label="합성 검토 결과표" tabindex="0"><table><caption>합성 검토 결과</caption><thead><tr>${headings.map(
      heading => `<th scope="col">${escapeHtml(heading)}</th>`
    ).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(
      (value, index) => index === 0
        ? `<th scope="row">${escapeHtml(value)}</th>`
        : `<td>${escapeHtml(value)}</td>`
    ).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function exampleView(stage) {
    const example = stage.example_view;
    if (!example) return "";
    if (example.type === "policy_table") return policyTable();
    if (example.type === "timeline" || example.type === "closing") {
      return listBlock("화면 예시", example.items);
    }
    if (example.type === "choice_result") {
      return `<section class="example"><h3>합성 화면 예시</h3><p>${escapeHtml(example.question)}</p>${resultTable(
        ["정책안", "선택률"], example.rows.map(row => [`${row.option}안`, `${row.percent}%`])
      )}</section>`;
    }
    if (example.type === "personal_impact") {
      return `<section class="example"><h3>개인영향 화면 예시</h3>${listBlock("입력 영역", example.input_placeholders)}${resultTable(
        ["안", "월연금", "수급공백", "83.5세 생애총액", "연 조세부담률", "기금 상태", "AI 정책 해설"],
        example.rows.map(row => [row.option, row.monthly, row.gap, row.lifetime, row.tax_rate, row.fund_status, row.explanation])
      )}</section>`;
    }
    if (example.type === "m2_result") {
      return `<section class="example"><h3>합성 T5 결과 예시</h3>${resultTable(
        ["안", "M1", "M2", "수용", "조건부 수용", "비선택"],
        example.rows.map(row => [row.option, row.m1, row.m2, row.accept, row.conditional, row.not_selected].map(
          (value, index) => index === 0 ? value : `${value}%`
        ))
      )}</section>`;
    }
    if (example.type === "segment_result") {
      return `<section class="example"><h3>합성 T6 결과 예시</h3>${resultTable(
        ["변수", "구간", "특성", "설명"],
        example.rows.map(row => [row.variable, row.segment, row.characteristic, row.reason])
      )}</section>`;
    }
    if (example.type === "generated_policy") {
      const option = {id: example.label, ...example.values};
      return `<section class="example"><h3>합성 ${escapeHtml(example.label)}안 화면 예시</h3>${policyTable(option)}${listBlock("생성 근거", example.basis)}</section>`;
    }
    if (example.type === "commentary") {
      return `<section class="example"><h3>합성 논평 화면 예시</h3>${listBlock("전문가 논평", example.expert)}${listBlock("진행자 선정 공개 청중 의견", example.audience)}</section>`;
    }
    if (example.type === "m3_result") {
      const option = {id: "D′", ...example.d_prime};
      return `<section class="example"><h3>합성 최종 평가 화면 예시</h3>${policyTable(option)}${resultTable(
        ["정책안", "최종 선택률"], example.rows.map(row => [row.option, `${row.percent}%`])
      )}</section>`;
    }
    return "";
  }

  function render(snapshotHash, expiresAt, scope) {
    const stage = catalog.stages[stageIndex];
    disclosure.textContent = catalog.disclosure;
    disclosure.hidden = false;
    snapshot.textContent = `검토 스냅숏 ${snapshotHash.slice(0, 12)}`;
    expiry.textContent = expiresAt
      ? `범위: ${scope === "national-pension-only" ? "국민연금" : "확인 필요"} · 만료: ${new Date(expiresAt).toLocaleString("ko-KR")}`
      : `범위: ${scope === "national-pension-only" ? "국민연금" : "확인 필요"} · 합성 기획 검토본 · 만료 없음`;
    stageList.innerHTML = catalog.stages.map((item, index) => `
      <button type="button" data-stage="${escapeHtml(item.id)}" aria-current="${index === stageIndex ? "step" : "false"}">
        <span>${item.position}</span>${escapeHtml(item.title)}
      </button>`).join("");
    content.innerHTML = `
      <p class="step-label">STEP ${stage.position} / ${catalog.stages.length}</p>
      <h2>${escapeHtml(stage.title)}</h2>
      <p>${escapeHtml(stage.summary)}</p>
      ${exampleView(stage)}
      ${stageDetails(stage)}
      <p class="classification">데이터 구분: 교수 검토용 합성 예시</p>`;
    content.hidden = false;
    status.hidden = true;
    previous.disabled = stageIndex === 0;
    next.disabled = stageIndex === catalog.stages.length - 1;
    reset.disabled = false;
    next.textContent = next.disabled ? "검토 끝" : "다음";
    content.focus({preventScroll: true});
  }

  async function move(targetIndex, historyMode = "push") {
    if (!catalog || targetIndex < 0 || targetIndex >= catalog.stages.length) return;
    status.hidden = false;
    status.textContent = "검토 단계를 확인하고 있습니다.";
    await load(catalog.stages[targetIndex].id, historyMode);
  }

  stageList.addEventListener("click", event => {
    const button = event.target.closest("button[data-stage]");
    if (!button || !catalog) return;
    const target = catalog.stages.findIndex(item => item.id === button.dataset.stage);
    move(target).catch(showError);
  });
  previous.addEventListener("click", () => move(stageIndex - 1).catch(showError));
  next.addEventListener("click", () => move(stageIndex + 1).catch(showError));
  reset.addEventListener("click", () => move(0, "replace").catch(showError));
  retry.addEventListener("click", () => {
    if (!retryAction) return;
    retry.disabled = true;
    status.textContent = "다시 연결하고 있습니다.";
    const action = retryAction;
    action().catch(showError);
  });
  addEventListener("popstate", () => {
    const stage = new URLSearchParams(location.search).get("stage") || "intro";
    load(stage, "replace").catch(showError);
  });

  function showError(error) {
    loadSerial += 1;
    if (activeLoad) activeLoad.abort();
    activeLoad = null;
    content.hidden = true;
    disclosure.hidden = true;
    stageList.replaceChildren();
    previous.disabled = true;
    next.disabled = true;
    reset.disabled = true;
    retry.hidden = retryAction === null;
    retry.disabled = false;
    status.hidden = false;
    status.textContent = error.message || "검토 자료를 불러오지 못했습니다.";
  }

  if (!experimentId && !planningMode) {
    showError(new Error("검토 대상 식별자가 없습니다."));
  } else {
    exchange().then(() => load(initialStage)).catch(showError);
  }
})();
