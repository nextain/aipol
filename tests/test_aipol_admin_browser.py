"""Playwright smoke test for the signed AIPOL preparation and 3-measurement path."""
from __future__ import annotations

import importlib
import json
import socket
import sys
import threading
import time

import pytest

from policy_lab.domains.pension.experiment import content_hash


CATEGORIES = (
    "policy_options", "calculation", "measurement", "privacy",
    "research_ethics", "source_license", "procedure",
)
RECEIPT_CONTRACT = {
    "contract_id": "calculator-completion-v1",
    "version": "1.0.0",
    "mode": "signed_one_time_completion",
    "issuer": "https://example.test",
    "audience": "aipol-event-tool",
    "public_key_id": "fixture-key-1",
    "receipt_format": "flattened_jws_json",
    "signature_algorithm": "EdDSA",
}
MODULES = (
    "server", "db", "aipol_store", "aipol_admin_store", "aipol_audit_checkpoint", "aipol_chat",
    "aipol_batch", "aipol_receipt", "ai_config", "deliberate", "llm",
)


def _free_port() -> int:
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _fill_experiment(page) -> None:
    values = {
        "title": "AIPOL 브라우저 통합 실험", "version": "browser-v1",
        "session": "browser-session", "capacity": "1", "consent": "consent-v1",
        "consent-text": "세 차례 선택과 자료 노출 기록에 동의합니다.",
        "question": "어느 연금개혁안을 선택하시겠습니까?", "option-version": "options-v1",
    }
    for key, value in values.items():
        page.locator(f"#{key}").fill(value)
    for option in ("A", "B", "C"):
        page.locator(f"#label-{option}").fill(f"정책안 {option}")
        page.locator(f"#source-{option}").fill("KAPS 승인자료")
        page.locator(f"#approver-{option}").fill("approver")
        page.locator(f"#lever-{option}").fill(f"승인 레버 {option}")


def _calculation_evidence() -> dict:
    return {
        "source_repository": "https://github.com/example/approved-calculator",
        "source_commit": "a" * 40,
        "source_tree_hash": "b" * 64,
        "build_hash": "c" * 64,
        "license_spdx": "Apache-2.0",
        "license_evidence_hash": "d" * 64,
        "approved_origin": "https://example.test",
        "csp": "default-src 'self'; script-src 'self'; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        "network_test_hash": "e" * 64,
        "policy_values_status": "approved",
        "integration_status": "approved",
        "integration_contract_version": "aipol-calculator-return-v2",
        "integration_test_hash": "9" * 64,
        "receipt_contract": RECEIPT_CONTRACT,
        "receipt_contract_hash": content_hash(RECEIPT_CONTRACT),
        "raw_input_egress": False,
    }


def _measure(page, choice: str, *, secondary: str | None = None) -> None:
    page.locator(f'input[name="choice"][value="{choice}"]').check()
    page.locator("#confidence").select_option("4")
    if secondary is not None:
        page.locator("#secondary").select_option(secondary)
    page.locator("#step-submit").click()


def test_admin_editor_approver_freeze_and_participant_e1a_to_m3(tmp_path, monkeypatch):
    sync_api = pytest.importorskip("playwright.sync_api")
    uvicorn = pytest.importorskip("uvicorn")
    event_tool = __import__("pathlib").Path(__file__).parents[1] / "event-tool"
    monkeypatch.setenv("EVENT_ENV", "development")
    monkeypatch.setenv("EVENT_DEMO_ENABLED", "false")
    monkeypatch.setenv("EVENT_DB_PATH", str(tmp_path / "browser.db"))
    monkeypatch.setenv("EVENT_SQLITE_NOLOCK", "false")
    monkeypatch.setenv("EVENT_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("EVENT_ADMIN_USERS_JSON", json.dumps({
        "editor": "editor-password-12345", "approver": "approver-password-12345",
    }))
    monkeypatch.setenv("EVENT_ADMIN_ROLES_JSON", json.dumps({
        "editor": ["editor"],
        "approver": ["approver", "operator", "admin", "auditor"],
    }))
    monkeypatch.syspath_prepend(str(event_tool))
    for name in MODULES:
        sys.modules.pop(name, None)
    app_module = importlib.import_module("server")

    class BrowserReceiptVerifier:
        verifier_id = "browser-fixture-verifier"

        def verify(self, receipt, contract, context):
            if contract != RECEIPT_CONTRACT or receipt.get("contract_hash") != content_hash(contract):
                raise app_module.aipol_store.ExperimentError("invalid browser receipt")
            return str(receipt.get("receipt_id") or "")

    app_module.aipol_store.configure_completion_receipt_verifier(BrowserReceiptVerifier())
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(
        app_module.app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started
    base = f"http://127.0.0.1:{port}"

    console_errors: list[str] = []
    try:
        with sync_api.sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True)
            admin = context.new_page()
            admin.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            admin.goto(f"{base}/aipol-admin.html")
            admin.locator("#user").fill("editor")
            admin.locator("#pw").fill("editor-password-12345")
            admin.locator("#login-btn").click()
            _fill_experiment(admin)
            admin.locator("#create").click()
            admin.locator("#admission-credentials textarea").wait_for()
            admission_code = admin.locator("#admission-credentials textarea").input_value().splitlines()[0]
            with admin.expect_download() as download_info:
                admin.locator("#download-admission-csv").click()
            assert download_info.value.suggested_filename.endswith("admission-credentials.csv")
            admin.locator("#experiments button").first.click()
            experiment_id = admin.locator('#detail a[href^="/aipol.html?experiment="]').get_attribute("href").split("=")[1]

            calculation_evidence = _calculation_evidence()
            for category in CATEGORIES:
                admin.locator("#canonical-category").select_option(category)
                admin.locator("#canonical-id").fill(f"doc-{category}")
                admin.locator("#canonical-version").fill("v1")
                admin.locator("#canonical-body").fill(f"승인 대상 {category} 정본")
                evidence = calculation_evidence if category == "calculation" else {"review": "approved"}
                admin.locator("#canonical-evidence").fill(json.dumps(evidence))
                admin.locator("#preview-canonical").click()
                admin.locator("#canonical-preview").wait_for()
                assert "content_hash:" in admin.locator("#canonical-preview").inner_text()
                admin.locator("#register-canonical-draft").click()
                admin.locator(f'[data-approve-canonical="{category}"]').wait_for()

            admin.close()
            approver_context = browser.new_context(accept_downloads=True)
            admin = approver_context.new_page()
            admin.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            admin.goto(f"{base}/aipol-admin.html")
            admin.locator("#user").fill("approver")
            admin.locator("#pw").fill("approver-password-12345")
            admin.locator("#login-btn").click()
            admin.locator("#experiments button").first.click()
            for category in CATEGORIES:
                admin.locator(f"#approval-{category}").fill(f"approval-{category}")
                admin.locator(f'[data-approve-canonical="{category}"]').click()
                admin.locator(f'[data-approve-canonical="{category}"]').wait_for(state="detached")
            assert admin.locator("#canonical-rows").inner_text().count("승인 완료") == 7

            personal = {
                "pc-id": "calculator-v1", "pc-version": "v1", "pc-title": "개인 조건 비교",
                "pc-url": "https://example.test/approved-calculator", "pc-origin": "https://example.test",
                "pc-limitations": "실험용 계산 결과이며 실제 연금액이 아닙니다.",
                "pc-canonical": admin.locator("#pc-canonical").input_value(),
                "pc-build": calculation_evidence["build_hash"],
                "pc-receipt": calculation_evidence["receipt_contract_hash"],
                "pc-integration-test": calculation_evidence["integration_test_hash"],
                "pc-approval": "approval-e1a",
            }
            for key, value in personal.items():
                admin.locator(f"#{key}").fill(value)
            admin.locator("#save-personal").click()
            admin.locator("#personal-result").filter(has_text="approval-e1a").wait_for()
            for key, value in {
                "expert-id": "expert-v1", "expert-version": "v1", "expert-title": "전문가 설명",
                "expert-body": "승인된 전문가의 연금개혁 설명입니다.", "expert-approval": "approval-e1b",
            }.items():
                admin.locator(f"#{key}").fill(value)
            admin.locator("#save-expert").click()
            admin.locator("#expert-result").filter(has_text="approval-e1b").wait_for()
            admin.locator("#ai-role").select_option("fallback")
            for key, value in {
                "ai-id": "ai-fallback", "ai-version": "v1", "ai-title": "AI 대체 의견",
                "ai-body": "M2 집계 장애 시 사용할 승인된 대체 의견입니다.", "ai-model": "fixture-model",
                "ai-deployment": "fixture-deployment", "ai-prompt": "prompt-v1",
                "ai-evidence": "evidence-1", "ai-approval": "approval-ai-fallback",
            }.items():
                admin.locator(f"#{key}").fill(value)
            admin.locator("#ai-generated").evaluate("el => { const d=new Date(Date.now()-1000); el.value=new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,19); }")
            admin.locator("#save-ai").click()
            admin.locator("#ai-result").filter(has_text="fallback 승인").wait_for()
            admin.locator("#freeze-prep-id").fill("freeze-browser-v1")
            admin.locator("#freeze-preparation").click()
            admin.locator("#detail").filter(has_text="수집 ON").wait_for()

            participant_context = browser.new_context(accept_downloads=True)
            participant = participant_context.new_page()
            participant.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            participant.goto(f"{base}/aipol.html?experiment={experiment_id}")
            participant.locator("#admission-code").fill(admission_code)
            participant.locator("#register").click()
            participant.locator("#state-recovery").wait_for()
            recovery_code = participant.locator("#recovery-kit-code").input_value()
            assert recovery_code.startswith("AIPOL-RC-")
            with participant.expect_download() as recovery_download:
                participant.locator("#download-recovery-kit").click()
            assert recovery_download.value.suggested_filename.startswith("aipol-recovery-")
            participant.locator("#continue-after-recovery").click()
            participant.locator("#consent-check").check()
            participant.locator("#step-submit").click()
            participant.locator("#launch-calculator").wait_for()
            participant.evaluate("""() => {
                calculatorReceipt={receipt_id:'browser-receipt-1',contract_hash:current.receipt_context.contract_hash};
                document.getElementById('read-check').disabled=false;
            }""")
            participant.locator("#read-check").check()
            participant.locator("#step-submit").click()
            participant.locator('input[name="choice"]').first.wait_for()

            old_participant = participant
            transfer_context = browser.new_context(accept_downloads=True)
            participant = transfer_context.new_page()
            participant.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            participant.goto(f"{base}/aipol.html?experiment={experiment_id}")
            participant.locator("#recovery-code").fill(recovery_code)
            participant.locator("#recover").click()
            participant.locator("#state-recovery").wait_for()
            replacement_recovery_code = participant.locator("#recovery-kit-code").input_value()
            assert replacement_recovery_code.startswith("AIPOL-RC-")
            assert replacement_recovery_code != recovery_code
            participant.locator("#continue-after-recovery").click()
            participant.locator('input[name="choice"]').first.wait_for()
            errors_before_old_token_check = len(console_errors)
            old_participant.reload()
            old_participant.locator("#state-error").wait_for()
            assert old_participant.locator("#reset-error").is_visible()
            expected_old_token_errors = console_errors[errors_before_old_token_check:]
            assert len(expected_old_token_errors) == 1 and "401" in expected_old_token_errors[0]
            del console_errors[errors_before_old_token_check:]

            _measure(participant, "A")
            participant.locator("#read-check").check()
            participant.locator("#step-submit").click()
            _measure(participant, "B")
            participant.locator("#step-content").filter(has_text="AI 의견 공개 대기").wait_for()

            admin.locator("#close-preparation-registration").click()
            admin.locator("#refresh-m2").click()
            admin.locator("#m2-finalization").filter(has_text="M2 확정").wait_for()
            # datetime-local is serialized at whole-second precision. Keep the
            # generated timestamp unambiguously after the finalized barrier.
            time.sleep(2.1)
            admin.locator("#ai-role").select_option("primary")
            for key, value in {
                "ai-id": "ai-primary", "ai-version": "v1", "ai-title": "AI 집계 의견",
                "ai-body": "마감된 M2 집계에 근거한 AI 의견입니다.", "ai-model": "fixture-model",
                "ai-deployment": "fixture-deployment", "ai-prompt": "prompt-v1",
                "ai-evidence": "evidence-1", "ai-approval": "approval-ai-primary",
            }.items():
                admin.locator(f"#{key}").fill(value)
            admin.locator("#ai-generated").evaluate("el => { const d=new Date(Date.now()-300); el.value=new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,19); }")
            admin.locator("#save-ai").click()
            admin.wait_for_timeout(500)
            assert admin.locator("#admin-error").inner_text() == ""
            admin.locator("#ai-result").filter(has_text="primary 승인").wait_for()
            admin.locator("#release-reason").fill("M2 집계와 근거를 검토해 primary를 선택함")
            admin.locator("#release-candidate").click()
            admin.locator("#detail").filter(has_text="E2 공개").wait_for()

            participant.locator("#step-submit").click()
            participant.locator("#read-check").check()
            participant.locator("#step-submit").click()
            _measure(participant, "C", secondary="4")
            participant.locator("#state-done").wait_for()

            unlabeled = admin.locator("input:not([type=hidden]),select,textarea").evaluate_all("""nodes => nodes.filter(node => !node.disabled && !node.labels?.length && !node.getAttribute('aria-label')).map(node => node.id)""")
            assert unlabeled == []
            assert console_errors == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        for name in MODULES:
            sys.modules.pop(name, None)
