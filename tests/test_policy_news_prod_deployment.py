from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bots" / "policy_news"
sys.path.insert(0, str(BOT))

import adapters  # noqa: E402
import azure_blob_store  # noqa: E402
import collector  # noqa: E402
import scheduled_job  # noqa: E402
from adapters import AnyLlmDraftAdapter, AnyLlmReviewAdapter, PermanentProviderError  # noqa: E402
from config import RuntimeConfig, validate_anyllm_endpoint  # noqa: E402
from contracts import SourcePacket  # noqa: E402


def _source_packet() -> SourcePacket:
    return SourcePacket.from_dict({
        "source_name": "Official",
        "source_url": "https://example.gov/item",
        "published": "2026-07-31",
        "country": "GB",
        "title": "Policy",
        "source_text": "Official source text",
        "fetched_at": "2026-07-31T00:00:00+00:00",
    })


def _editorial_draft():
    return adapters.EditorialDraft.from_dict(
        {
            "title_ko": "제목",
            "summary_ko": "요약",
            "policy_use": "활용",
            "human_review": "사람 검토 필요",
            "relevance": "관련",
            "caveat": "한계",
        },
        provider="solar",
        model="solar-open2",
        generated_at="2026-07-31T00:00:00+00:00",
    )


def _coverage() -> dict[str, str]:
    return {item: "checked" for item in adapters.nemotron_review.ALLOWED_COVERAGE}


def test_prod_job_is_digest_pinned_manual_first_and_fail_closed() -> None:
    bicep = (ROOT / "deploy/azure/policy-news-prod/main.bicep").read_text(encoding="utf-8")
    assert "expectedResourceGroupName = 'rg_aipol'" in bicep
    assert "param cronExpression string = '0 21 * * *'" in bicep
    assert "approvedImagePrefix = '${registryName}.azurecr.io/aipol/policy-news@sha256:'" in bicep
    assert "length(imageDigest) == 64" in bicep
    assert "imageDigest == toLower(imageDigest)" in bicep
    assert "manualRunImageDigest == imageDigest" in bicep
    assert "manualRunConfigurationFingerprint == runtimeConfigurationFingerprint" in bicep
    assert "startsWith(manualRunExecutionName, '${jobName}-')" in bicep
    assert "enableSchedule requires a successful manual execution receipt" in bicep
    assert "providerQualityStatus == 'passed'" in bicep
    assert "runtimeEnabled ? [" in bicep
    assert "publicAccess: 'None'" in bicep
    assert "parallelism: 1" in bicep
    assert "replicaCompletionCount: 1" in bicep
    assert "param maxEstimatedCostUsd string = '2.00'" in bicep
    assert "{ name: 'POLICY_NEWS_MAX_COST_USD', value: maxEstimatedCostUsd }" in bicep
    assert "|${maxItemsPerRun}|${maxEstimatedCostUsd}|${cronExpression}" in bicep
    assert "command: ['python']" in bicep
    assert "args: ['scheduled_job.py']" in bicep
    assert "OPENROUTER_API_KEY" not in bicep
    assert "human_approve" not in bicep
    assert "mark_published" not in bicep
    assert "uami-aipol-prod'" not in bicep
    assert "Microsoft.KeyVault/vaults/secrets/providers/roleAssignments@2022-04-01" in bicep
    assert "scope: upstageSecret" not in bicep
    assert "scope: anyllmSecret" not in bicep
    assert bicep.count("'secret-scope-v2'") == 1


def test_prod_job_fixes_four_stage_naia_pipeline_and_no_delete_role() -> None:
    bicep = (ROOT / "deploy/azure/policy-news-prod/main.bicep").read_text(encoding="utf-8")
    role = (ROOT / "deploy/azure/policy-news-prod/blob-role.bicep").read_text(encoding="utf-8")
    assert "{ name: 'POLICY_NEWS_DRAFT_PROVIDER', value: 'anyllm' }" in bicep
    assert "{ name: 'POLICY_NEWS_REVIEW_PROVIDER', value: 'anyllm' }" in bicep
    assert "param anyllmAnalysisModel string = 'upstage:solar-pro4'" in bicep
    assert "param anyllmVerificationModel string = 'azure:deepseek-v4-pro'" in bicep
    assert "param anyllmTranslationModel string = 'azure:gpt-5.6-luna'" in bicep
    assert "param anyllmReviewModel string = 'azure:deepseek-v4-flash'" in bicep
    assert "UPSTAGE_API_KEY" not in bicep
    assert "ANYLLM_API_KEY" in bicep
    assert "blobs/delete" not in role
    assert "containers/delete" not in role
    assert "move/action" not in role
    assert bicep.count("dependsOn: [blobRole]") == 2


def test_review_only_runtime_requires_quality_evidence() -> None:
    with pytest.raises(ValueError, match="PROVIDER_APPROVAL"):
        RuntimeConfig(enabled=True, dry_run=False, require_kb_compile=False).validate()
    config = RuntimeConfig(
        enabled=True,
        dry_run=False,
        require_kb_compile=False,
        provider_approval="passed",
        provider_evidence_sha256="a" * 64,
    )
    config.validate()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api.nextain.io/v1",
        "https://user:pass@api.nextain.io/v1",
        "https://api.nextain.io/v1/chat",
        "https://api.nextain.io/v1?token=x",
        "https://anyllm.example/v1",
    ],
)
def test_anyllm_endpoint_rejects_noncanonical_targets(endpoint: str) -> None:
    with pytest.raises(ValueError, match="AnyLLM endpoint"):
        validate_anyllm_endpoint(endpoint)


def test_anyllm_draft_uses_virtual_key_and_strict_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {"calls": []}

    def fake_post(url, payload, headers, timeout, **kwargs):
        captured["calls"].append({"url": url, "payload": payload, "headers": headers, "timeout": timeout})
        if payload["model"] == "upstage:solar-pro4":
            result = {"title": "Title", "summary": "Summary", "policy_use": "Use", "human_review": "Review", "relevance": "Relevant", "caveat": "Caveat"}
            response_id = "analysis-1"
        elif payload["model"] == "azure:deepseek-v4-pro":
            result = {"verdict": "PASS", "issues": [], "summary": "Verified"}
            response_id = "verification-1"
        else:
            result = {"title_ko": "제목", "summary_ko": "요약", "policy_use": "활용", "human_review": "검토", "relevance": "관련", "caveat": "한계"}
            response_id = "translation-1"
        return {"id": response_id, "choices": [{"message": {"content": json.dumps(result)}}]}, ""

    monkeypatch.setattr(adapters, "_post_json", fake_post)
    config = RuntimeConfig(anyllm_endpoint="https://api.nextain.io/v1", draft_provider="anyllm")
    result = AnyLlmDraftAdapter(config, api_key="virtual-key").draft(_source_packet())
    assert result.provider == "naia-anyllm"
    calls = captured["calls"]
    assert [call["payload"]["model"] for call in calls] == [
        "upstage:solar-pro4", "azure:deepseek-v4-pro", "azure:gpt-5.6-luna"
    ]
    assert all(call["url"] == "https://api.nextain.io/v1/chat/completions" for call in calls)
    assert all(call["headers"] == {"Authorization": "Bearer virtual-key"} for call in calls)
    assert [stage["stage"] for stage in result.pipeline] == ["analysis", "verification", "translation"]
    schema = calls[2]["payload"]["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False


def test_anyllm_draft_fails_closed_without_key() -> None:
    config = RuntimeConfig(anyllm_endpoint="https://api.nextain.io/v1", draft_provider="anyllm")
    with pytest.raises(PermanentProviderError, match="virtual key"):
        AnyLlmDraftAdapter(config, api_key="").draft(_source_packet())


def test_anyllm_review_accepts_exact_coverage_map(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    result = {"verdict": "PASS", "issues": [], "coverage": _coverage(), "summary": "원문 대조 통과"}

    def fake_post(url, payload, headers, timeout, **kwargs):
        captured.update(url=url, payload=payload, headers=headers)
        return {"id": "review-1", "choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}]}, ""

    monkeypatch.setattr(adapters, "_post_json", fake_post)
    config = RuntimeConfig(review_provider="anyllm", anyllm_endpoint="https://api.nextain.io/v1", anyllm_review_model="azure:deepseek-v4-flash")
    review = AnyLlmReviewAdapter(config, api_key="dedicated-key").review(_source_packet(), _editorial_draft())
    assert review.verdict == "PASS"
    assert set(review.coverage) == set(_coverage())
    assert review.model == "azure:deepseek-v4-flash"
    assert captured["headers"] == {"Authorization": "Bearer dedicated-key"}
    assert "response_format" not in captured["payload"]
    system_prompt = captured["payload"]["messages"][0]["content"]
    assert "exactly field, severity, description" in system_prompt
    assert "low, medium, high, critical" in system_prompt
    assert "Do not add evidence, quote, suggestion, category" in system_prompt


@pytest.mark.parametrize(
    "result,error",
    [
        ({"verdict": "PASS", "issues": [], "coverage": {}, "summary": "ok"}, "every required check"),
        ({"verdict": "PASS", "issues": [{"field": "x", "severity": "high", "description": "bad"}], "coverage": _coverage(), "summary": "bad"}, "inconsistent"),
        ({"verdict": "BLOCK", "issues": [], "coverage": _coverage(), "summary": "bad"}, "inconsistent"),
        ({"verdict": "BLOCK", "issues": [{"field": "x", "severity": "unknown", "description": "bad"}], "coverage": _coverage(), "summary": "bad"}, "issue"),
        ({"verdict": "PASS", "issues": [], "coverage": _coverage(), "summary": "ok", "extra": True}, "strict schema"),
    ],
)
def test_anyllm_review_fails_closed(monkeypatch: pytest.MonkeyPatch, result, error) -> None:
    monkeypatch.setattr(adapters, "_post_json", lambda *args, **kwargs: ({"choices": [{"message": {"content": json.dumps(result)}}]}, ""))
    config = RuntimeConfig(review_provider="anyllm", anyllm_endpoint="https://api.nextain.io/v1", anyllm_review_model="azure:deepseek-v4-flash")
    with pytest.raises(PermanentProviderError, match=error):
        AnyLlmReviewAdapter(config, api_key="key").review(_source_packet(), _editorial_draft())


def test_scheduled_job_uses_naia_draft_and_deepseek_review_without_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str] = []
    config = RuntimeConfig(
        enabled=True,
        dry_run=False,
        require_kb_compile=False,
        provider_approval="passed",
        provider_evidence_sha256="a" * 64,
        draft_provider="anyllm",
        review_provider="anyllm",
        anyllm_endpoint="https://api.nextain.io/v1",
        anyllm_model="azure:gpt-5.6-luna",
        anyllm_review_model="azure:deepseek-v4-flash",
    )
    monkeypatch.setattr(scheduled_job.RuntimeConfig, "from_env", classmethod(lambda cls: config))
    monkeypatch.setenv("AZURE_STORAGE_BLOB_URL", "https://staipolprod01.blob.core.windows.net")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(adapters, "AnyLlmDraftAdapter", lambda *_args, **_kwargs: created.append("draft") or object())
    monkeypatch.setattr(adapters, "AnyLlmReviewAdapter", lambda *_args, **_kwargs: created.append("review") or object())
    monkeypatch.setattr(azure_blob_store, "AzureBlobRunStore", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(collector, "collect", lambda **_kwargs: [])
    assert scheduled_job.main() == 0
    assert created == ["draft", "review"]
