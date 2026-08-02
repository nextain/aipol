"""Playwright smoke test for the signed AIPOL preparation and 3-measurement path."""
from __future__ import annotations

import importlib
import json
import socket
import sys
import threading
import time
from datetime import datetime, timezone

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


def _fill_experiment(page, procedure_version: str) -> None:
    values = {
        "title": "AIPOL 브라우저 통합 실험", "version": "browser-current",
        "session": "browser-session", "capacity": "1", "consent": "consent-v1",
        "consent-text": "세 차례 선택과 자료 노출 기록에 동의합니다.",
        "question": "어느 연금개혁안을 선택하시겠습니까?", "option-version": "options-v1",
    }
    for key, value in values.items():
        page.locator(f"#{key}").fill(value)
    page.locator("#procedure-version").select_option(procedure_version)
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


def _measure(page, choice: str, *, structured: bool = False) -> None:
    page.locator(f'input[name="choice"][value="{choice}"]').check()
    page.locator("#confidence").select_option("4")
    if structured:
        option_ids = page.locator(".option-assessment-stance").evaluate_all(
            "nodes => nodes.map(node => node.dataset.optionId)"
        )
        for option_id in option_ids:
            selected = option_id == choice
            page.locator(f"#assessment-{option_id}").select_option(
                "conditional" if selected else "reject"
            )
            page.locator(f"#assessment-reason-{option_id}").fill(
                "조건과 재정 근거를 더 확인합니다." if selected else f"{option_id}안의 비용과 제약을 고려했습니다."
            )
    else:
        page.locator("#reason").fill(f"{choice}안의 목표와 부담을 함께 고려했습니다.")
    page.locator("#step-submit").click()


def _admin_api(page, path: str, body: dict | None = None) -> dict:
    result = page.evaluate(
        """async ({path, body}) => {
          const response = await fetch(path, {
            method: 'POST',
            headers: {'Content-Type':'application/json', 'X-Admin-Token':sessionStorage.getItem('aipol:admin')},
            body: JSON.stringify(body || {}),
          });
          let payload = {}; try { payload = await response.json(); } catch (_) {}
          return {status: response.status, payload};
        }""",
        {"path": path, "body": body or {}},
    )
    assert result["status"] == 200, f"{path}: {result}"
    return result["payload"]


def _admin_get(page, path: str) -> dict | list:
    result = page.evaluate(
        """async (path) => {
          const response = await fetch(path, {
            headers: {'X-Admin-Token':sessionStorage.getItem('aipol:admin')},
          });
          let payload = {}; try { payload = await response.json(); } catch (_) {}
          return {status: response.status, payload};
        }""",
        path,
    )
    assert result["status"] == 200, f"{path}: {result}"
    return result["payload"]


def _release_result(page, experiment_id: str, stage: str) -> dict:
    return _admin_api(
        page,
        f"/api/admin/aipol/experiments/{experiment_id}/public-results/{stage}/release",
        {
            "cutoff_at": datetime.now(timezone.utc).isoformat(),
            "rules_version": "aipol-public-results-v1",
        },
    )


def _ack_public_result(page, title: str) -> None:
    page.locator("#step-content").filter(has_text=title).wait_for()
    page.locator("#public-result-check").check()
    page.locator("#step-submit").click()


def test_admin_editor_approver_freeze_and_participant_e1a_to_m3(tmp_path, monkeypatch):
    sync_api = pytest.importorskip("playwright.sync_api")
    uvicorn = pytest.importorskip("uvicorn")
    event_tool = __import__("pathlib").Path(__file__).parents[1] / "event-tool"
    monkeypatch.setenv("EVENT_ENV", "development")
    monkeypatch.setenv("EVENT_DEMO_ENABLED", "false")
    monkeypatch.setenv("AIPOL_TEST_ALLOW_SMALL_PUBLIC_COHORT", "true")
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
    http_failures: list[dict] = []

    def observe_page(page) -> None:
        page.on(
            "console",
            lambda message: console_errors.append(message.text) if message.type == "error" else None,
        )

        def record_failure(response) -> None:
            if response.status < 400:
                return
            try:
                body = response.text()
            except Exception as error:  # pragma: no cover - diagnostic fallback
                body = f"<unreadable: {error}>"
            http_failures.append({"status": response.status, "url": response.url, "body": body})

        page.on("response", record_failure)
    try:
        with sync_api.sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True)
            admin = context.new_page()
            observe_page(admin)
            admin.goto(f"{base}/aipol-admin.html")
            admin.locator("#user").fill("editor")
            admin.locator("#pw").fill("editor-password-12345")
            admin.locator("#login-btn").click()
            current_procedure = app_module.aipol_store.PROCEDURE_CONFIG["version"].rsplit("-", 1)[-1]
            _fill_experiment(admin, current_procedure)
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
            observe_page(admin)
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
            observe_page(participant)
            participant_payloads: list[str] = []
            participant.on(
                "request",
                lambda request: participant_payloads.append(request.post_data or "")
                if request.method == "POST" and "/api/aipol/" in request.url else None,
            )
            participant.goto(f"{base}/aipol.html?experiment={experiment_id}")
            participant.locator("#state-start").wait_for()
            assert "정책전문가팀" in participant.locator("#state-start").inner_text()
            assert "AI팀" in participant.locator("#state-start").inner_text()
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
            participant.locator("#policy-options-check").wait_for()

            old_participant = participant
            transfer_context = browser.new_context(accept_downloads=True)
            participant = transfer_context.new_page()
            observe_page(participant)
            participant.on(
                "request",
                lambda request: participant_payloads.append(request.post_data or "")
                if request.method == "POST" and "/api/aipol/" in request.url else None,
            )
            participant.goto(f"{base}/aipol.html?experiment={experiment_id}")
            participant.locator("#recovery-code").fill(recovery_code)
            participant.locator("#recover").click()
            participant.locator("#state-recovery").wait_for()
            replacement_recovery_code = participant.locator("#recovery-kit-code").input_value()
            assert replacement_recovery_code.startswith("AIPOL-RC-")
            assert replacement_recovery_code != recovery_code
            participant.locator("#continue-after-recovery").click()
            participant.locator("#policy-options-check").wait_for()
            old_participant.reload()
            old_participant.locator("#state-error").wait_for()
            assert old_participant.locator("#reset-error").is_visible()
            # AIPOL-STEP-02: E0 confirmation gates the first measurement.
            participant.locator("#policy-options-check").check()
            participant.locator("#step-submit").click()
            participant.locator('input[name="choice"]').first.wait_for()
            _measure(participant, "A")

            # AIPOL-STEP-03: a real cohort waits for an append-only T3 release.
            participant.locator("#step-content").filter(has_text="1차 선택 결과").wait_for()
            assert "동결·공개" in participant.locator("#step-content").inner_text()
            _admin_api(admin, f"/api/admin/aipol/experiments/{experiment_id}/close-registration")
            _release_result(admin, experiment_id, "T3")
            participant.locator("#step-submit").click()
            _ack_public_result(participant, "1차 선택 결과")

            # AIPOL-STEP-04: only approved band IDs leave the browser; exact values do not.
            participant.locator("#research-profile-consent").wait_for()
            for selector in (
                "#research-age_band_id",
                "#research-monthly_personal_income_band_id",
                "#research-expected_contribution_years_band_id",
                "#research-expected_retirement_age_band_id",
            ):
                participant.locator(selector).select_option(index=1)
            participant.locator("#research-profile-consent").check()
            participant.locator("#step-submit").click()
            participant.locator("#launch-calculator").wait_for()
            participant.evaluate("""() => {
                calculatorReceipt={receipt_id:'browser-receipt-1',contract_hash:current.receipt_context.contract_hash};
                document.getElementById('read-check').disabled=false;
            }""")
            participant.locator("#read-check").check()
            participant.locator("#step-submit").click()
            participant.locator('input[name="choice"]').first.wait_for()

            # AIPOL-STEP-05: M2 records all A/B/C stances and reasons.
            _measure(participant, "B", structured=True)
            participant.locator("#step-content").filter(has_text="1·2차 선택 비교 결과").wait_for()
            admin.locator("#refresh-m2").click()
            admin.locator("#m2-finalization").filter(has_text="M2 확정").wait_for()
            _release_result(admin, experiment_id, "T5")
            participant.locator("#step-submit").click()
            _ack_public_result(participant, "1·2차 선택 비교 결과")
            participant.locator("#step-content").filter(has_text="잠정 의견 D 공개 대기").wait_for()

            # Raw reasons are visible only to an authenticated classifier, and a
            # separately authenticated approver accepts only frozen topic codes.
            classifier_context = browser.new_context()
            classifier = classifier_context.new_page()
            observe_page(classifier)
            classifier.goto(f"{base}/aipol-admin.html")
            classifier.locator("#user").fill("editor")
            classifier.locator("#pw").fill("editor-password-12345")
            classifier.locator("#login-btn").click()
            classifier.locator("#dashboard").wait_for()
            pending = _admin_get(
                classifier,
                f"/api/admin/aipol/experiments/{experiment_id}/m2-reason-classification-pending",
            )
            assert len(pending) == 3
            for index, item in enumerate(pending):
                draft = _admin_api(
                    classifier,
                    f"/api/admin/aipol/experiments/{experiment_id}/m2-reason-classification-drafts",
                    {
                        "participant_pseudonym": item["participant_pseudonym"],
                        "option_id": item["option_id"],
                        "reason_hash": item["reason_hash"],
                        "topic_codes": ["fiscal_sustainability"],
                    },
                )
                _admin_api(
                    admin,
                    f"/api/admin/aipol/experiments/{experiment_id}/m2-reason-classifications",
                    {
                        "draft_id": draft["draft_id"], "draft_hash": draft["draft_hash"],
                        "approval_id": f"classification-browser-{index}",
                    },
                )
            classifier_context.close()

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
            released = _admin_api(
                admin,
                f"/api/admin/aipol/experiments/{experiment_id}/release-e2",
                {"candidate_role": "primary", "selection_reason": "M2 집계와 근거를 검토해 primary를 선택함"},
            )

            # AIPOL-STEP-06: T6 is shown before D and honours suppression rules.
            participant.locator("#step-submit").click()
            participant.locator("#t6-result-check").wait_for()
            assert "작은 집단" in participant.locator("#step-content").inner_text()
            t6_text = participant.locator("#step-content").inner_text()
            assert "규칙 기반 분석 설명" in t6_text
            assert "승인자 approver" in t6_text
            assert "생성 시각" in t6_text
            assert "승인 시각" in t6_text
            assert "대체안 미사용" in t6_text
            participant.locator("#t6-result-check").check()
            participant.locator("#step-submit").click()

            # AIPOL-STEP-07/08: D, expert constraints and facilitator-selected public input.
            participant.locator("#read-check").wait_for()
            d_exposure = participant.locator("#step-content").inner_text()
            assert "생성 시각" in d_exposure
            assert "승인자 approver" in d_exposure
            assert "승인 시각" in d_exposure
            assert "대체안 미사용" in d_exposure
            participant.locator("#read-check").check()
            participant.locator("#step-submit").click()
            participant.locator("#step-content").filter(has_text="전문가 설명").wait_for()
            participant.locator("#read-check").check()
            participant.locator("#step-submit").click()
            participant.locator("#step-content").filter(has_text="공개 청중 의견 진행").wait_for()
            admin.locator("#public-audience-sequence").fill("1")
            admin.locator("#public-audience-statement").fill("재정 조건과 세대별 부담을 더 명확히 공개해 주세요.")
            admin.locator("#save-public-audience-input").click()
            admin.locator("#public-audience-result").filter(has_text="등록 완료").wait_for()
            participant.locator("#step-submit").click()
            participant.locator("#step-content").filter(has_text="수정 의견 D′ 공개 대기").wait_for()

            with app_module.aipol_store.db._conn() as connection:
                expert_hash = connection.execute(
                    "SELECT content_hash FROM aipol_artifacts WHERE experiment_id=? AND kind='expert_explanation'",
                    (experiment_id,),
                ).fetchone()[0]
                d_artifact_id, d_content_hash = connection.execute(
                    "SELECT c.artifact_id,c.content_hash FROM aipol_ai_candidates c "
                    "JOIN aipol_experiments e ON e.e2_selected_candidate_id=c.id WHERE e.id=?",
                    (experiment_id,),
                ).fetchone()
            audience = admin.evaluate(
                """async (path) => { const r=await fetch(path,{headers:{'X-Admin-Token':sessionStorage.getItem('aipol:admin')}}); return await r.json(); }""",
                f"/api/admin/aipol/experiments/{experiment_id}/public-audience-inputs",
            )
            _admin_api(
                admin,
                f"/api/admin/aipol/experiments/{experiment_id}/artifacts",
                {
                    "kind": "final_ai_opinion", "artifact_id": "d-prime-browser-v2",
                    "artifact_version": "v1", "approval_id": "approval-d-prime-browser-v2",
                    "approved_by": "approver", "fallback_used": False,
                    "content": {
                        "title": "수정 의견 D′", "body": "전문가 비용·제약과 공개 청중 의견을 반영했습니다.",
                        "lever_values": {"approved_summary": "승인 레버 D′"},
                        "d_artifact_id": d_artifact_id,
                        "d_content_hash": d_content_hash,
                        "m2_aggregate_hash": released["e2_m2_aggregate_hash"],
                        "expert_artifact_hash": expert_hash,
                        "public_audience_input_hash": audience["aggregate_hash"],
                        "model": "fixture-revision-model", "deployment": "fixture-revision-deployment",
                        "prompt_version": "fixture-d-prime-v1",
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "evidence_refs": ["m2-finalization", "expert-approved", "audience-finalized"],
                    },
                },
            )

            # AIPOL-STEP-09/10/11: D′ exposure, four-option M3, T10 and closing panel.
            participant.locator("#step-submit").click()
            participant.locator("#read-check").wait_for()
            d_prime_exposure = participant.locator("#step-content").inner_text()
            assert "생성 시각" in d_prime_exposure
            assert "승인자 approver" in d_prime_exposure
            assert "승인 시각" in d_prime_exposure
            assert "대체안 미사용" in d_prime_exposure
            participant.locator("#read-check").check()
            participant.locator("#step-submit").click()
            participant.locator('input[name="choice"][value="D_PRIME"]').wait_for()
            assert participant.locator('input[name="choice"]').count() == 4
            _measure(participant, "D_PRIME", structured=True)
            participant.locator("#step-content").filter(has_text="최종 선택과 변화 결과").wait_for()
            _release_result(admin, experiment_id, "T10")
            participant.locator("#step-submit").click()
            _ack_public_result(participant, "최종 선택과 변화 결과")
            participant.locator("#state-done").wait_for()
            assert "패널 총평과 마무리" in participant.locator("#state-done").inner_text()

            raw_payloads = "\n".join(participant_payloads)
            assert all(exact_field not in raw_payloads for exact_field in ('"age"', '"income"', '"contribution_years"', '"retirement_age"'))

            unlabeled = admin.locator("input:not([type=hidden]),select,textarea").evaluate_all("""nodes => nodes.filter(node => !node.disabled && !node.labels?.length && !node.getAttribute('aria-label')).map(node => node.id)""")
            assert unlabeled == []
            allowed_failures = [
                failure for failure in http_failures
                if failure["status"] == 401 and failure["url"].endswith(f"/api/aipol/experiments/{experiment_id}/current")
            ]
            unexpected_failures = [failure for failure in http_failures if failure not in allowed_failures]
            assert len(allowed_failures) == 1
            assert unexpected_failures == [], unexpected_failures
            unexpected_console = [message for message in console_errors if "401 (Unauthorized)" not in message]
            assert unexpected_console == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        for name in MODULES:
            sys.modules.pop(name, None)
