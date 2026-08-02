import json
import subprocess
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).parents[1]
WEB = ROOT / "event-tool" / "web"


def test_participant_page_has_all_server_driven_states_and_no_result_container():
    soup = BeautifulSoup((WEB / "aipol.html").read_text("utf-8"), "html.parser")
    assert soup.html["lang"] == "ko"
    for element_id in (
        "state-loading", "state-error", "state-start", "state-step", "state-done",
        "state-withdrawn", "state-recovery",
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
    start = soup.find(id="state-start")
    assert start.find(id="intro-procedure-title").get_text(strip=True) == "진행 절차"
    procedure = start.find(id="intro-procedure")
    assert len(procedure.find_all("li")) == 5
    assert "정책전문가팀" in start.get_text(" ", strip=True)
    assert "AI팀" in start.get_text(" ", strip=True)
    assert "AI가 정책을 결정하거나 정답을 제시하지 않으며" in start.get_text(" ", strip=True)
    assert start.find(id="admission-code")

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
