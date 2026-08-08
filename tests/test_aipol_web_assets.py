import json
import subprocess
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).parents[1]
WEB = ROOT / "event-tool" / "web"


def test_legacy_review_route_hands_off_to_the_canonical_participant_app():
    soup = BeautifulSoup((WEB / "aipol-review.html").read_text("utf-8"), "html.parser")
    script = (WEB / "aipol-review.js").read_text("utf-8")

    assert not soup.find("progress")
    assert "별도의 목업 화면은 제공하지 않습니다" in soup.get_text(" ", strip=True)
    assert 'params.get("review")' in script
    assert 'params.get("experiment")' in script
    assert '`/aipol.html?${mode}=' in script
    assert "window.location.replace(target)" in script
    for fixture_marker in ("const STAGES", "issueScores", "D_PRIME", "최종선택"):
        assert fixture_marker not in script


def test_participant_page_has_all_server_driven_states_and_no_result_container():
    soup = BeautifulSoup((WEB / "aipol.html").read_text("utf-8"), "html.parser")
    assert soup.html["lang"] == "ko"
    for element_id in (
        "state-loading", "state-error", "state-start", "state-step", "state-done",
        "state-withdrawn", "state-recovery", "state-review-intro",
    ):
        assert soup.find(id=element_id)
    assert not soup.find(id="results")
    script = (WEB / "aipol.js").read_text("utf-8")
    assert "consent" in script and "exposures/" in script and "measurements/" in script
    assert "secondary_evaluation" in script
    assert "participant_results" not in script
    for element_id in ("reset-error", "reset-done", "reset-withdrawn"):
        button = soup.find(id=element_id)
        assert button and button.get_text(strip=True) == "다른 참가자로 시작"
    assert "localStorage.removeItem(tokenKey)" in script
    assert "localStorage.removeItem(registrationNonceKey)" in script
    assert "localStorage.removeItem(registrationIdempotencyKey)" in script
    assert "completion_receipt" in script and "launch-calculator" in script
    assert 'get("review_token")' in script
    assert "/^S[A-F0-9]{32}$/" in script
    assert 'history.replaceState(null, "", `${location.pathname}${location.search}`)' in script
    assert "synthetic_review" in script
    assert "localStorage.setItem(tokenKey, reviewToken)" not in script
    assert 'current.participant_type !== "synthetic"' in script
    assert "completion-receipt" not in script
    assert "createReturnChannel" in script and "buildLaunchUrl" in script
    assert '"noopener,noreferrer,popup' in script
    assert "window.opener" not in script
    assert "manual-receipt-value" in script
    assert soup.find("script", src="/aipol-receipt.js")
    receipt_parser = (WEB / "aipol-receipt.js").read_text("utf-8")
    for field in ("protected", "payload", "signature"):
        assert field in receipt_parser
    assert "{token:" not in script
    assert soup.find(id="recovery-code") and soup.find(id="recovery-kit-code")
    assert "participants/recover" in script and "downloadRecoveryKit" in script
    assert "localStorage.setItem(recovery" not in script


def test_participant_page_starts_with_experiment_intro_and_ends_with_panel_closing():
    soup = BeautifulSoup((WEB / "aipol.html").read_text("utf-8"), "html.parser")
    assert soup.find("h1").get_text(strip=True) == "정책이 나와 사회에 미치는 영향을 확인한 후, 다시 정책을 선택합니다."
    start = soup.find(id="state-start")
    assert start.find(id="intro-procedure-title").get_text(strip=True) == "진행 절차"
    procedure = start.find(id="intro-procedure")
    assert len(procedure.find_all("li")) == 5
    assert "정책전문가팀" in start.get_text(" ", strip=True)
    assert "AI팀" in start.get_text(" ", strip=True)
    assert "AI가 정책을 결정하거나 정답을 제시하지 않으며" in start.get_text(" ", strip=True)
    assert start.find(id="admission-code")

    review_intro = soup.find(id="state-review-intro")
    assert review_intro.find(id="review-teams-title")
    assert review_intro.find(id="review-procedure-title")
    assert len(review_intro.find_all("li")) == 11
    review_text = review_intro.get_text(" ", strip=True)
    assert "합성 검토 전용" in review_text
    assert "정책전문가팀" in review_text and "AI팀" in review_text
    assert soup.find(id="participation-scope")

    done = soup.find(id="state-done")
    assert done.find(id="closing-panel-title").get_text(strip=True) == "패널 총평과 마무리"
    closing = done.get_text(" ", strip=True)
    assert "정책전문가팀과 AI팀의 총평" in closing
    assert "전체 시민의 여론이나 정책 효과를 뜻하지 않습니다" in closing


def test_saved_v2_keeps_legacy_single_stance_form_and_intro_is_version_neutral():
    script = (WEB / "aipol.js").read_text("utf-8")
    html = (WEB / "aipol.html").read_text("utf-8")
    soup = BeautifulSoup(html, "html.parser")
    tokenless_copy = " ".join((
        soup.find(id="procedure-summary").get_text(" ", strip=True),
        soup.find(id="state-start").get_text(" ", strip=True),
    ))
    assert 'legacyStructuredM2 = current.stage === "M2"' in script
    assert 'aipol-pension-3-measurements-v2' in script
    assert 'id="stance"' in script
    assert "실험 버전" in tokenless_copy
    assert "진행자가 안내한 실험 버전" in tokenless_copy
    for version_specific_claim in (
        "A/B/C/D′를 놓고",
        "D와 D′",
        "AI 수정 의견",
        "청중 논평",
        "세 번의 선택",
    ):
        assert version_specific_claim not in tokenless_copy


def test_m2_renders_three_structured_option_assessments_with_reason_limits():
    script = (WEB / "aipol.js").read_text("utf-8")
    assert "structured_option_assessment" in script
    assert "세 안에 대한 판단" in script
    assert "선택안은 수용 또는 조건부 수용" in script
    assert "선택하지 않은 각 안은 비선택과 사유" in script
    assert 'class="option-assessment-reason"' in script
    assert 'maxlength="2000"' in script
    assert "...(structuredAssessment ? {option_assessments:optionAssessments} : {})" in script


def test_policy_values_are_reused_across_e0_measurements_and_d_lineage():
    script = (WEB / "aipol.js").read_text("utf-8")
    for label in ("수급개시연령", "기금운용전략(수익률)", "국고투입(지원) 수준"):
        assert label in script
    assert "기금운용전략(운용수익률)" in script
    assert script.count("renderPolicyComparison(") >= 4
    assert 'const comparisonCaption = current.stage === "M3" ? "A·B·C·D′ 최종 비교"' in script
    assert 'const simpleM1 = current.stage === "M1"' in script
    assert 'const optionalDetails = simpleM1 ? ""' in script
    assert 'const confidenceField = simpleM1 ? ""' in script
    assert "D 생성 근거" in script and "D′ 수정 근거" in script
    for limit in ("보험료율 18% 이하", "소득대체율 43%", "운용수익률 5~7%", "수급개시연령 65~70세", "국고투입 GDP 1% 이하"):
        assert limit in script
    assert "D′안 별도 선택률 분포 그래프" in script
    assert "segment-bar-fill" in script
    assert "M2에서 M3로 어떤 선택이 움직였나요?" in script
    assert "transitionMovementSummary(result.m2_to_m3" in script
    assert "같은 선택을 유지한 경우를 제외한 실제 이동만 따로 계산했습니다." in script
    assert "네 안에 대한 최종 판단" in script
    assert 'value="${esc(option.policy_option_id)}"' in script
    assert "A·B·C·D′ 최종 비교" in script
    assert "주 선택은 A/B/C만 대상으로 기록합니다." not in script
    assert "D′ 별도 투표" not in script


def test_personal_review_preview_supports_dict_or_array_and_labels_unapproved_example():
    script = (WEB / "aipol.js").read_text("utf-8")
    assert "Array.isArray(preview.options)" in script
    assert "Object.entries(preview.options || {})" in script
    for label in (
        "예상 월연금", "개시·소득공백", "생애 총수급(83.5세)",
        "예상 연조세부담률", "연금 소진시점", "개인 해설",
        "화면 검토용 예시 · 계산 정책값과 산식 승인 전이며 실제 연금액이 아닙니다.",
    ):
        assert label in script


def test_participant_provenance_and_suppressed_counts_are_explicit():
    script = (WEB / "aipol.js").read_text("utf-8")
    for label in ("생성 시각", "승인자", "승인 시각", "대체안"):
        assert label in script
    assert 'current.stage === "E2" || current.stage === "E3"' in script
    assert "snapshot.d_candidate_provenance" in script
    assert "규칙 기반 분석 설명" in script
    assert "승인된 AI 분석 설명" not in script
    assert "resultCount(row.count)" in script
    assert 'value == null ? "—"' in script


def test_calculator_fragment_and_openerless_return_channel_validate_context():
    helper = WEB / "aipol-receipt.js"
    code = r"""
const fs=require('fs'),vm=require('vm'),m={exports:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{module:m,exports:m.exports,globalThis:{},Buffer,URL,TextEncoder});
const api=m.exports;
const context={experiment_id:'xp',experiment_version:'v1',session_id:'s1',participant_pseudonym:'p1',artifact_id:'calc',artifact_hash:'a'.repeat(64),contract_hash:'b'.repeat(64)};
const integration={contract_version:api.CONTRACT_VERSION,allowed_origin:'https://calculator.example',launch_url:'https://calculator.example/run',context_fragment_key:'aipol_context',max_context_bytes:2048};
const channelId='123e4567-e89b-12d3-a456-426614174000';
let channel; class FakeChannel{constructor(name){this.name=name;channel=this;}close(){this.closed=true;}}
let accepted=null; api.createReturnChannel({channelId,context,BroadcastChannelClass:FakeChannel,onReceipt:(value)=>accepted=value});
const protectedHeader=Buffer.from(JSON.stringify({alg:'EdDSA',kid:'calculator-key-1',typ:'JWT'}),'utf8').toString('base64url');
const receipt={protected:protectedHeader,payload:'q',signature:'s'};
channel.onmessage({data:{type:api.RETURN_MESSAGE,contract_version:api.CONTRACT_VERSION,channel_id:channelId,experiment_id:'wrong',receipt}});
channel.onmessage({data:{type:api.RETURN_MESSAGE,contract_version:api.CONTRACT_VERSION,channel_id:channelId,experiment_id:'xp',receipt}});
let extraHeaderRejected=false;
const extraProtected=Buffer.from(JSON.stringify({alg:'EdDSA',kid:'calculator-key-1',typ:'JWT',crit:['exp']}),'utf8').toString('base64url');
try{api.validateReceipt({...receipt,protected:extraProtected});}catch(_){extraHeaderRejected=true;}
let dirtyRejected=false;try{api.integrationOrigin({...integration,launch_url:'https://user:pass@calculator.example/run?token=x#f'});}catch(_){dirtyRejected=true;}
console.log(JSON.stringify({url:api.buildLaunchUrl(integration,context,'https://aipol.example/aipol-calculator-return.html',channelId,'https://aipol.example'),channelName:channel.name,accepted,extraHeaderRejected,dirtyRejected}));
"""
    result = subprocess.run(
        ["node", "-e", code, str(helper)], check=True, capture_output=True, text=True
    )
    value = json.loads(result.stdout)
    assert value["url"].startswith("https://calculator.example/run#aipol_context=")
    assert value["channelName"] == "aipol-calculator-123e4567-e89b-12d3-a456-426614174000"
    assert value["accepted"]["payload"] == "q" and value["accepted"]["signature"] == "s"
    protected = json.loads(__import__("base64").urlsafe_b64decode(
        value["accepted"]["protected"] + "=="
    ))
    assert protected == {"alg": "EdDSA", "kid": "calculator-key-1", "typ": "JWT"}
    assert value["extraHeaderRejected"] is True
    assert value["dirtyRejected"] is True


def test_v4_participant_branch_is_server_driven_and_review_scoped():
    script = (WEB / "aipol.js").read_text("utf-8")
    html = (WEB / "aipol.html").read_text("utf-8")
    assert 'const reviewEventId = params.get("review")' in script
    assert "queryConflict" in script and "event_kind !== \"review\"" in script
    assert "synthetic_review !== true" in script
    assert 'procedure_version === "aipol-pension-3-measurements-v4"' in script
    for field in ("gender_band_id", "age_band_id", "monthly_personal_income_band_id"):
        assert field in script
    assert 'submitAction("demographics"' in script
    assert "current.demographics || {}" in script
    assert "demographics.required === true" in script
    assert "demographics.recorded !== true" in script
    assert "contract.options?.[key]" in script
    assert 'rules_version: contract.rules_version || ""' in script
    assert "raw" not in script[script.index("function renderDemographics"):script.index("function renderWaiting")]
    assert "renderV4DeliberationArtifact" in script
    for field in (
        "public_summary", "source_bundle", "deliberation_process", "issue_aggregation",
        "admin_constraints", "expert_approval_diff", "approval_rationale",
    ):
        assert field in script
    assert "이 값은 점수가 아니라 고유 참가자 수와 승인된 사유 레코드 수입니다." in script
    assert "복수 쟁점 분류이므로 쟁점별 합계가 응답자 수를 넘을 수 있습니다." in script
    assert "AI 초안:" in script and "전문가 승인:" in script and "수정 사유:" in script
    assert "숨은 사고 과정, 내부 프롬프트, 시민 자유서술 원문" in script
    renderer = script[
        script.index("function renderV4DeliberationArtifact"):
        script.index("function renderPersonalComparisonPreview")
    ]
    assert "JSON.stringify" not in renderer
    assert "승인 자료 없음" in script
    assert "const structuredM3 = current.stage === \"M3\"" in script
    assert "&& !v4M3" in script
    assert "const v4M1" in script and "const v4M3" in script
    assert "confidence" in script and "#confidence" in script
    assert "review와 experiment" in script or "experiment와 review" in script
    assert "9단계 개요" in script
    assert 'const m3Label = isV4() ? "3차" : "최종"' in script
    assert 'const legacyDPrimeSegments = isV4() ? "" : dPrimeSegmentCharts(result)' in script
    assert 'isV4() && current.stage === "M3" ? "3차 선택"' in script
    v4_intro = script[script.index("function renderV4ReviewIntro"):script.index("function policyLeverValue")]
    assert "최종 선택" not in v4_intro
    assert "3차 선택" in v4_intro
    assert "D와 D′" not in html


def test_v4_preparation_uses_approved_classification_and_structured_d_contracts():
    script = (WEB / "aipol-preparation.js").read_text("utf-8")
    for endpoint in (
        "m2-reason-classification-pending",
        "m2-reason-classification-drafts",
        "m2-reason-classification-approvals",
        "m2-reason-classifications",
        "issue-aggregation",
    ):
        assert endpoint in script
    for field in (
        "lever_values",
        "public_summary",
        "deliberation_process",
        "ai_draft",
        "approved_d",
        "expert_approval_diff",
        "approval_rationale",
    ):
        assert field in script
    approval_renderer = script[
        script.index("async function loadClassificationApprovals"):
        script.index("async function approveClassification")
    ]
    assert "item.reason}" not in approval_renderer
    assert "reason hash" in approval_renderer and "draft hash" in approval_renderer


def test_same_origin_return_page_has_no_opener_dependency_and_no_referrer():
    soup = BeautifulSoup((WEB / "aipol-calculator-return.html").read_text("utf-8"), "html.parser")
    script = (WEB / "aipol-calculator-return.js").read_text("utf-8")
    assert soup.find("meta", attrs={"name": "referrer", "content": "no-referrer"})
    assert "window.opener !== null" in script
    assert "opener.postMessage" not in script
    assert "BroadcastChannel" in script and "history.replaceState" in script


def test_admin_page_uses_forms_and_exposes_collection_gate():
    soup = BeautifulSoup((WEB / "aipol-admin.html").read_text("utf-8"), "html.parser")
    assert soup.find(id="create-fields")
    assert soup.find(id="detail")
    script = (WEB / "aipol-admin.js").read_text("utf-8")
    assert "collection_enabled" in script
    assert "policy_options" in script
    assert "window.openAipolPreparation" in script
    assert "artifact-approved-at" not in script and "freeze-approved-at" not in script
    assert "async function open(" not in script
    assert soup.find(id="admission-credentials")
    assert "created.admission_credentials" in script
    assert "downloadAdmissionCsv" in script and "text/csv" in script
    assert "admission-code" not in script
    assert "서버 CSPRNG 일회용 참가 자격" in script
    preparation = (WEB / "aipol-preparation.js").read_text("utf-8")
    assert soup.find("script", src="/aipol-preparation.js")
    for required in (
        "PREP_CATEGORIES", "canonical-documents/preview", "canonical-drafts", "canonical_document_hash",
        "receipt_contract_hash", "expert_explanation", "m2-aggregate",
        "candidate_role", "evidence_refs", "selection_reason", "freezePreparation",
        "approval_id", "launch_origin", "mark-pending-attrition", "cohort_finalized_at",
    ):
        assert required in preparation
    assert "documents.map" in preparation
    assert "open = openPreparation" not in preparation
    assert "window.openAipolPreparation = openPreparation" in preparation
    assert "approved_at: new Date" not in preparation


def test_admin_javascript_has_one_experiment_path_and_parses_in_node():
    for name in ("aipol-admin.js", "aipol-preparation.js"):
        subprocess.run(
            ["node", "--check", str(WEB / name)], check=True, capture_output=True, text=True
        )
    base = (WEB / "aipol-admin.js").read_text("utf-8")
    preparation = (WEB / "aipol-preparation.js").read_text("utf-8")
    assert "AI 의견은 primary/fallback" not in base
    assert "personal_comparison / expert_explanation / ai_opinion" not in base + preparation
    assert preparation.count("async function openPreparation") == 1
