"""AIPOL policy-news provider/approval/provenance contract tests."""

from __future__ import annotations

import json
import sys
import threading
import types
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bots" / "policy_news"
sys.path.insert(0, str(BOT))

from adapters import (  # noqa: E402
    AzureFoundryDraftAdapter,
    MockDraftAdapter,
    MockKbCompilerAdapter,
    MockReviewAdapter,
    NaiaKbCompilerCommandAdapter,
    NaiaKbCompilerHttpAdapter,
    TransientProviderError,
    _kb_input,
)
import adapters  # noqa: E402
import run_v2  # noqa: E402
from config import Budget, RuntimeConfig, validate_kb_compiler_origin  # noqa: E402
from contracts import ApprovalState, SourcePacket, transition  # noqa: E402
from orchestrator import FileRunStore, PolicyNewsOrchestrator  # noqa: E402


RECEIVER_DEPLOYMENT = "sha256:" + "a" * 64
RECEIVER_APP_CLIENT_ID = "11111111-1111-4111-8111-111111111111"
RECEIVER_SCOPE = f"api://{RECEIVER_APP_CLIENT_ID}/.default"


def receiver_contract() -> dict[str, str]:
    tenant = "tenant-id"
    return {
        "schemaVersion": "aipol-kb-receiver-contract-v1",
        "tenantId": tenant,
        "audience": f"api://{RECEIVER_APP_CLIENT_ID}",
        "scope": RECEIVER_SCOPE,
        "receiverAppClientId": RECEIVER_APP_CLIENT_ID,
        "allowedUamiClientId": "uami-client-id",
        "allowedUamiPrincipalId": "uami-principal-id",
        "requiredAppRole": "Aipol.PolicyNews.Compile",
        "issuer": f"https://login.microsoftonline.com/{tenant}/v2.0",
        "jwksUri": f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
        "validationMode": "entra-jwt-v2-strict",
        "receiverVersion": "1.2.3",
        "deploymentId": RECEIVER_DEPLOYMENT,
        "compilePath": "/compile",
    }


def receiver_kwargs() -> dict[str, str]:
    return {
        "tenant_id": "tenant-id",
        "app_client_id": RECEIVER_APP_CLIENT_ID,
        "principal_id": "uami-principal-id",
        "required_app_role": "Aipol.PolicyNews.Compile",
        "receiver_version": "1.2.3",
        "deployment_id": RECEIVER_DEPLOYMENT,
    }


def fetch_receiver_contract(url: str, timeout: int, max_bytes: int) -> dict[str, str]:
    assert url == "https://kb.aipol.example/.well-known/aipol-kb-compiler-receiver.json"
    assert timeout == 120 and max_bytes == 65_536
    return receiver_contract()


def packet() -> dict[str, str]:
    return {
        "source_name": "Official Test Agency",
        "source_url": "https://example.gov/policy/ai-consultation",
        "published": "2026-07-20",
        "country": "Testland",
        "title": "AI support for policy consultation",
        "source_text": "The agency uses AI to group consultation comments. A human analyst reviews every result.",
        "fetched_at": "2026-07-21T01:02:03+00:00",
    }


def enabled_config(**updates: object) -> RuntimeConfig:
    base = RuntimeConfig(
        enabled=True,
        dry_run=True,
        review_provider="mock",
        kb_compiler_mode="mock",
        foundry_managed_identity_client_id="uami-client-id",
        kb_compiler_scope=RECEIVER_SCOPE,
        kb_compiler_app_client_id=RECEIVER_APP_CLIENT_ID,
        kb_compiler_allowed_origins=("https://kb.aipol.example",),
        kb_compiler_tenant_id="tenant-id",
        kb_compiler_uami_principal_id="uami-principal-id",
        kb_compiler_required_app_role="Aipol.PolicyNews.Compile",
        kb_compiler_receiver_version="1.2.3",
        kb_compiler_receiver_deployment_id=RECEIVER_DEPLOYMENT,
    )
    return replace(base, **updates)


class FakeKbToken:
    token = "kb-managed-identity-token"


class FakeKbCredential:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, scope: str) -> FakeKbToken:
        self.scopes.append(scope)
        return FakeKbToken()


@pytest.mark.parametrize(
    ("config", "argv", "expected"),
    [
        (RuntimeConfig(enabled=False), ["run_v2.py", "missing.json"], 0),
        (
            enabled_config(
                dry_run=True,
                kb_compiler_mode="http",
                kb_compiler_endpoint="https://kb.aipol.example",
            ),
            ["run_v2.py", "missing.json", "--draft-provider", "mock"],
            2,
        ),
    ],
)
def test_run_v2_off_and_nonmock_dry_run_construct_no_adapter_and_make_no_network_call(
    monkeypatch: pytest.MonkeyPatch,
    config: RuntimeConfig,
    argv: list[str],
    expected: int,
) -> None:
    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("called")
        raise AssertionError("adapter/network boundary must not be reached")

    monkeypatch.setattr(run_v2.RuntimeConfig, "from_env", lambda: config)
    for name in (
        "AzureFoundryDraftAdapter", "SolarDraftAdapter", "MockDraftAdapter",
        "NemotronReviewAdapter", "MockReviewAdapter", "NaiaKbCompilerHttpAdapter",
        "NaiaKbCompilerCommandAdapter", "MockKbCompilerAdapter",
    ):
        monkeypatch.setattr(run_v2, name, forbidden)
    monkeypatch.setattr(sys, "argv", argv)
    assert run_v2.main() == expected
    assert calls == []


def test_source_packet_requires_replayable_provenance_and_matches_hash() -> None:
    parsed = SourcePacket.from_dict(packet())
    assert len(parsed.content_sha256) == 64
    assert parsed.source_id
    assert "source_text" not in parsed.public_source_metadata()
    bad = {**packet(), "content_sha256": "0" * 64}
    with pytest.raises(ValueError, match="does not match"):
        SourcePacket.from_dict(bad)
    missing_fetch = {key: value for key, value in packet().items() if key != "fetched_at"}
    with pytest.raises(ValueError, match="fetched_at"):
        SourcePacket.from_dict(missing_fetch)
    with pytest.raises(ValueError, match="timezone"):
        SourcePacket.from_dict({**packet(), "fetched_at": "2026-07-21T01:02:03"})
    with pytest.raises(ValueError, match="source_id"):
        SourcePacket.from_dict({**packet(), "source_id": "../../site/leak"})


def test_private_file_store_rejects_tracked_public_paths() -> None:
    with pytest.raises(ValueError, match="data-private"):
        FileRunStore(ROOT / "site" / "policy-news-state")
    FileRunStore(ROOT / "tmp" / "policy-news-state")


def test_approval_state_machine_requires_adversarial_and_human_gates() -> None:
    assert transition(ApprovalState.DRAFTED, ApprovalState.REVIEW_PASSED) == ApprovalState.REVIEW_PASSED
    with pytest.raises(ValueError, match="invalid approval transition"):
        transition(ApprovalState.DRAFTED, ApprovalState.PUBLISHED)
    with pytest.raises(ValueError, match="invalid approval transition"):
        transition(ApprovalState.REVIEW_PASSED, ApprovalState.PUBLISHED)


def test_mock_pipeline_compiles_kb_is_idempotent_and_requires_human_approval(tmp_path: Path) -> None:
    draft = MockDraftAdapter()
    review = MockReviewAdapter("PASS")
    compiler = MockKbCompilerAdapter(tmp_path / "kb")
    store = FileRunStore(tmp_path / "runs")
    pipeline = PolicyNewsOrchestrator(
        config=enabled_config(),
        draft_port=draft,
        review_port=review,
        knowledge_compiler=compiler,
        store=store,
        allowed_hosts={"example.gov"},
        clock=lambda: "2026-07-28T00:00:00+00:00",
        sleeper=lambda _: None,
    )

    first = pipeline.run(packet())
    second = pipeline.run(packet())
    assert first.run_id == second.run_id
    assert first.state == ApprovalState.KB_COMPILED
    assert (draft.calls, review.calls, compiler.calls) == (1, 1, 1)
    assert first.source["content_sha256"]
    assert "source_text" not in first.to_dict()["source"]
    assert first.kb and Path(first.kb["artifact_uri"]).is_file()
    assert list((tmp_path / "runs" / "sources").glob("*.json"))

    approved = pipeline.human_approve(first.idempotency_key, actor="editor@example.org", reason="official source checked")
    assert approved.state == ApprovalState.HUMAN_APPROVED
    published = pipeline.mark_published(first.idempotency_key, actor="release@example.org", reason="approved PR merged")
    assert published.state == ApprovalState.PUBLISHED


def test_blocking_review_stops_before_kb_and_publication(tmp_path: Path) -> None:
    compiler = MockKbCompilerAdapter(tmp_path / "kb")
    pipeline = PolicyNewsOrchestrator(
        config=enabled_config(),
        draft_port=MockDraftAdapter(),
        review_port=MockReviewAdapter("BLOCK"),
        knowledge_compiler=compiler,
        store=FileRunStore(tmp_path / "runs"),
        allowed_hosts={"example.gov"},
        sleeper=lambda _: None,
    )
    record = pipeline.run(packet())
    assert record.state == ApprovalState.REVIEW_BLOCKED
    assert compiler.calls == 0
    with pytest.raises(ValueError, match="invalid approval transition"):
        pipeline.mark_published(record.idempotency_key, actor="x", reason="bypass")


class FlakyDraft(MockDraftAdapter):
    name = "mock-flaky-draft"

    def draft(self, packet: SourcePacket):  # type: ignore[override]
        self.calls += 1
        if self.calls < 3:
            raise TransientProviderError("temporary")
        self.calls -= 1
        return super().draft(packet)


def test_transient_failures_retry_with_cap_and_audit(tmp_path: Path) -> None:
    draft = FlakyDraft()
    sleeps: list[float] = []
    pipeline = PolicyNewsOrchestrator(
        config=enabled_config(max_attempts=3, retry_base_seconds=0.5),
        draft_port=draft,
        review_port=MockReviewAdapter(),
        store=FileRunStore(tmp_path / "runs"),
        allowed_hosts={"example.gov"},
        sleeper=sleeps.append,
    )
    record = pipeline.run(packet())
    assert record.state == ApprovalState.REVIEW_PASSED
    assert record.attempts["draft"] == 3
    assert sleeps == [0.5, 1.0]
    assert len([event for event in record.audit if event.get("event") == "transient_failure"]) == 2


def test_exhausted_run_resumes_from_last_durable_stage(tmp_path: Path) -> None:
    draft = FlakyDraft()
    review = MockReviewAdapter()
    pipeline = PolicyNewsOrchestrator(
        config=enabled_config(max_attempts=1),
        draft_port=draft,
        review_port=review,
        store=FileRunStore(tmp_path / "runs"),
        allowed_hosts={"example.gov"},
        sleeper=lambda _: None,
    )
    with pytest.raises(TransientProviderError):
        pipeline.run(packet())
    with pytest.raises(TransientProviderError):
        pipeline.run(packet())
    completed = pipeline.run(packet())
    assert completed.state == ApprovalState.REVIEW_PASSED
    assert draft.calls == 3
    assert review.calls == 1


def test_kill_switch_dry_run_and_budget_fail_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    with pytest.raises(RuntimeError, match="kill switch"):
        PolicyNewsOrchestrator(
            config=RuntimeConfig(enabled=False), draft_port=MockDraftAdapter(), review_port=MockReviewAdapter(), store=store,
            allowed_hosts={"example.gov"}
        ).run(packet())

    class NonMockDraft(MockDraftAdapter):
        name = "real-provider-name"

    with pytest.raises(RuntimeError, match="dry-run"):
        PolicyNewsOrchestrator(
            config=enabled_config(), draft_port=NonMockDraft(), review_port=MockReviewAdapter(), store=store,
            allowed_hosts={"example.gov"}
        ).run({**packet(), "source_url": "https://example.gov/other"})

    with pytest.raises(RuntimeError, match="mock KB compiler"):
        PolicyNewsOrchestrator(
            config=enabled_config(),
            draft_port=MockDraftAdapter(),
            review_port=MockReviewAdapter(),
            knowledge_compiler=NaiaKbCompilerHttpAdapter(
                "https://kb.aipol.example",
                client_id="uami-client-id",
                scope=RECEIVER_SCOPE,
                allowed_origins=("https://kb.aipol.example",),
                **receiver_kwargs(),
                token_credential=FakeKbCredential(),
                contract_fetcher=fetch_receiver_contract,
                artifact_dir=tmp_path / "kb",
            ),
            store=store,
            allowed_hosts={"example.gov"},
        ).run({**packet(), "source_url": "https://example.gov/compiler-dry-run"})

    budget = Budget(enabled_config(max_provider_calls_per_run=1, max_estimated_cost_usd_per_run=0.1))
    budget.reserve(estimated_cost_usd=0.05)
    with pytest.raises(RuntimeError, match="quota"):
        budget.reserve()

    with pytest.raises(ValueError, match="not allow-listed"):
        PolicyNewsOrchestrator(
            config=enabled_config(), draft_port=MockDraftAdapter(), review_port=MockReviewAdapter(), store=store,
            allowed_hosts={"official.example"}
        ).run({**packet(), "source_url": "https://untrusted.example/prompt-injection"})


def test_kb_boundary_keeps_official_source_distinct_from_ai_draft() -> None:
    source = SourcePacket.from_dict(packet())
    draft = MockDraftAdapter().draft(source)
    request = _kb_input(source, draft)
    assert request["safety"] == "block"
    assert request["sources"][0]["kind"] == "url"
    assert request["sources"][0]["uri"] == source.source_url
    assert request["sources"][1]["kind"] == "text"
    assert request["sources"][1]["uri"].startswith("urn:aipol:editorial-draft:")
    assert source.source_text not in request["sources"][1]["text"]


def test_http_kb_compiler_advances_only_to_kb_compiled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, payload: dict, headers: dict, timeout: int, *, max_bytes: int = 1_000_000):
        captured.update(url=url, payload=payload, headers=headers, timeout=timeout)
        captured["max_bytes"] = max_bytes
        return {
            "compiler_version": "1.2.3",
            "kb": {"cards": [], "entities": [], "relations": []},
            "report": {
                "sourceCount": 2, "cardCount": 0, "entityCount": 0,
                "relationCount": 0, "acceptedCount": 0, "gapCount": 0,
                "draftCount": 0,
            },
            "safety": {
                "mode": "block", "findings": [], "piiCount": 0,
                "confidentialCount": 0, "redactedCount": 0,
            },
        }, "request-kb-1"

    monkeypatch.setattr(adapters, "_post_json", fake_post)
    config = enabled_config(
        dry_run=False,
        kb_compiler_mode="http",
        kb_compiler_endpoint="https://kb.aipol.example",
    )
    credential = FakeKbCredential()
    pipeline = PolicyNewsOrchestrator(
        config=config,
        draft_port=MockDraftAdapter(),
        review_port=MockReviewAdapter("PASS"),
        knowledge_compiler=NaiaKbCompilerHttpAdapter(
            config.kb_compiler_endpoint,
            client_id=config.foundry_managed_identity_client_id,
            scope=config.kb_compiler_scope,
            allowed_origins=config.kb_compiler_allowed_origins,
            **receiver_kwargs(),
            token_credential=credential,
            contract_fetcher=fetch_receiver_contract,
            artifact_dir=tmp_path / "kb",
        ),
        store=FileRunStore(tmp_path / "runs"),
        allowed_hosts={"example.gov"},
        sleeper=lambda _: None,
    )

    record = pipeline.run(packet())
    assert record.state == ApprovalState.KB_COMPILED
    assert captured["url"] == "https://kb.aipol.example/compile"
    assert captured["payload"]["safety"] == "block"  # type: ignore[index]
    assert captured["headers"] == {"Authorization": "Bearer kb-managed-identity-token"}
    assert captured["max_bytes"] == 1_000_000
    assert credential.scopes == [RECEIVER_SCOPE]
    assert record.kb and record.kb["compiler"] == "naia-kb-compiler"
    assert len(record.kb["provenance"]["receiver_contract_sha256"]) == 64
    assert all(event.get("to") not in {"human_approved", "published"} for event in record.audit)


def test_json_schemas_and_bicep_defaults_are_safe() -> None:
    for path in sorted((BOT / "schemas").glob("*.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"].endswith("2020-12/schema")
        assert schema["$id"].startswith("https://aipol.kaps.or.kr/schemas/")

    bicep = (ROOT / "deploy" / "azure" / "policy-ai.bicep").read_text(encoding="utf-8")
    assert "param deployFoundry bool = false" in bicep
    assert "param deployModel bool = false" in bicep
    assert "kind: 'AIServices'" in bicep
    assert "param modelName string = 'gpt-5.4-mini'" in bicep
    assert "param modelVersion string = '2026-03-17'" in bicep
    assert "disableLocalAuth: disableLocalAuth" in bicep
    assert "param inferencePrincipalId string = ''" in bicep
    assert "a97b65f3-24c7-4388-baec-2e87135dc908" in bicep
    assert "resource inferenceRole 'Microsoft.Authorization/roleAssignments@2022-04-01'" in bicep
    assert "if (deployFoundry && deployModel)" in bicep
    assert "Microsoft.CognitiveServices/accounts/deployments@2024-04-01-preview" in bicep
    assert "AZURE_AI_FOUNDRY_AUTH_MODE=managed_identity" in bicep
    assert "AZURE_AI_FOUNDRY_AUTH_MODE=bearer" not in bicep


def test_config_snapshot_never_contains_provider_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "super-secret-value")
    monkeypatch.setenv("POLICY_NEWS_ENABLED", "true")
    monkeypatch.setenv("POLICY_NEWS_KB_COMPILER_MODE", "mock")
    config = RuntimeConfig.from_env()
    serialized = json.dumps(config.public_snapshot())
    assert "super-secret-value" not in serialized
    assert config.foundry_api_key_env == "AZURE_OPENAI_API_KEY"


def test_config_requires_compiler_when_enabled_and_omits_target_details() -> None:
    RuntimeConfig(enabled=False, kb_compiler_mode="disabled").validate()
    with pytest.raises(ValueError, match="requires a configured KB compiler"):
        RuntimeConfig(enabled=True, kb_compiler_mode="disabled").validate()
    with pytest.raises(ValueError, match="requires http or command"):
        RuntimeConfig(enabled=True, dry_run=False, kb_compiler_mode="mock").validate()
    with pytest.raises(ValueError, match="receiver contract is incomplete"):
        RuntimeConfig(
            enabled=False,
            kb_compiler_mode="http",
            kb_compiler_endpoint="https://kb.example",
            kb_compiler_allowed_origins=("https://kb.example",),
            kb_compiler_scope=RECEIVER_SCOPE,
            kb_compiler_app_client_id=RECEIVER_APP_CLIENT_ID,
            foundry_managed_identity_client_id="uami-client-id",
        ).validate()
    with pytest.raises(ValueError, match="exact credential-free HTTPS origin"):
        RuntimeConfig(
            enabled=True,
            dry_run=False,
            kb_compiler_mode="http",
            kb_compiler_endpoint="https://user:secret@kb.example/compile?token=secret#fragment",
            kb_compiler_allowed_origins=("https://kb.example",),
            kb_compiler_scope=RECEIVER_SCOPE,
            kb_compiler_app_client_id=RECEIVER_APP_CLIENT_ID,
            foundry_managed_identity_client_id="uami-client-id",
            kb_compiler_tenant_id="tenant-id",
            kb_compiler_uami_principal_id="uami-principal-id",
            kb_compiler_required_app_role="Aipol.PolicyNews.Compile",
            kb_compiler_receiver_version="1.2.3",
            kb_compiler_receiver_deployment_id=RECEIVER_DEPLOYMENT,
        ).validate()

    config = RuntimeConfig(
        enabled=False,
        kb_compiler_mode="http",
        kb_compiler_endpoint="https://user:secret@kb.example/compile?token=secret",
        kb_compiler_allowed_origins=("https://kb.example",),
        kb_compiler_scope=RECEIVER_SCOPE,
        kb_compiler_app_client_id=RECEIVER_APP_CLIENT_ID,
        foundry_managed_identity_client_id="uami-client-id",
        kb_compiler_command="compiler --token secret-value",
    )
    snapshot = config.safe_snapshot()
    serialized = json.dumps(snapshot)
    assert "kb_compiler_endpoint" not in snapshot
    assert "kb_compiler_command" not in snapshot
    assert "user:secret" not in serialized
    assert "secret-value" not in serialized


@pytest.mark.parametrize("endpoint", [
    "https://kb.example/",
    "https://KB.example",
    "https://kb.example:443",
    "https://kb.example/compile",
    "https://user@kb.example",
    "https://kb.example?mode=compile",
    "https://kb.example#fragment",
])
def test_kb_origin_policy_rejects_every_noncanonical_url_form(endpoint: str) -> None:
    with pytest.raises(ValueError):
        validate_kb_compiler_origin(endpoint)


def test_command_compiler_remains_local_argv_without_shell(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    payload = {
        "compiler_version": "command-test",
        "kb": {"cards": [], "entities": [], "relations": []},
        "report": {
            "sourceCount": 2, "cardCount": 0, "entityCount": 0,
            "relationCount": 0, "acceptedCount": 0, "gapCount": 0, "draftCount": 0,
        },
        "safety": {
            "mode": "block", "findings": [], "piiCount": 0,
            "confidentialCount": 0, "redactedCount": 0,
        },
    }

    def fake_run(argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(adapters.subprocess, "run", fake_run)
    source = SourcePacket.from_dict(packet())
    result = NaiaKbCompilerCommandAdapter(
        "python compiler.py --profile policy-news", artifact_dir=tmp_path / "kb"
    ).compile(source, MockDraftAdapter().draft(source))
    assert captured["argv"] == ["python", "compiler.py", "--profile", "policy-news"]
    assert captured["shell"] is False
    assert result.provenance["adapter_mode"] == "command"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["safety"].update(findings=[{"kind": "email"}]),
        lambda value: value["safety"].update(piiCount=1),
        lambda value: value["safety"].update(confidentialCount=1),
        lambda value: value["safety"].update(redactedCount=1),
        lambda value: value.pop("kb"),
        lambda value: value["report"].update(cardCount=1),
        lambda value: value["report"].update(gapCount=1),
        lambda value: value["kb"].update(cards=[{"status": "untrusted"}]) or value["report"].update(cardCount=1),
        lambda value: value["kb"].update(cards=[{}]) or value["report"].update(cardCount=1),
    ],
)
def test_kb_compiler_response_attack_payloads_fail_closed(mutation, tmp_path: Path) -> None:
    payload = {
        "compiler_version": "contract-test",
        "kb": {"cards": [], "entities": [], "relations": []},
        "report": {
            "sourceCount": 2, "cardCount": 0, "entityCount": 0,
            "relationCount": 0, "acceptedCount": 0, "gapCount": 0,
            "draftCount": 0,
        },
        "safety": {
            "mode": "block", "findings": [], "piiCount": 0,
            "confidentialCount": 0, "redactedCount": 0,
        },
    }
    mutation(payload)
    with pytest.raises(adapters.PermanentProviderError):
        adapters._kb_result(
            payload,
            artifact_uri=str(tmp_path / "rejected.json"),
            artifact_sha256="0" * 64,
            mode="http",
        )


def test_http_receiver_contract_must_match_every_identity_and_validation_field(tmp_path: Path) -> None:
    attacked = receiver_contract()
    attacked["allowedUamiPrincipalId"] = "attacker-principal"
    with pytest.raises(adapters.PermanentProviderError, match="allowedUamiPrincipalId"):
        NaiaKbCompilerHttpAdapter(
            "https://kb.aipol.example",
            client_id="uami-client-id",
            scope=RECEIVER_SCOPE,
            allowed_origins=("https://kb.aipol.example",),
            **receiver_kwargs(),
            token_credential=FakeKbCredential(),
            contract_fetcher=lambda _url, _timeout, _limit: attacked,
            artifact_dir=tmp_path / "kb",
        )


@pytest.mark.parametrize("scope", [
    "https://management.azure.com/.default",
    "https://storage.azure.com/.default",
    "https://kb.aipol.example/.default",
    "api://22222222-2222-4222-8222-222222222222/.default",
])
def test_http_compiler_scope_is_receiver_app_client_id_only(scope: str) -> None:
    with pytest.raises(ValueError, match="approved receiver app client ID"):
        enabled_config(
            dry_run=False,
            kb_compiler_mode="http",
            kb_compiler_endpoint="https://kb.aipol.example",
            kb_compiler_scope=scope,
        ).validate()


def test_http_compiler_missing_or_mismatched_attested_version_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = {
        "compiler_version": "1.2.3",
        "kb": {"cards": [], "entities": [], "relations": []},
        "report": {
            "sourceCount": 2, "cardCount": 0, "entityCount": 0,
            "relationCount": 0, "acceptedCount": 0, "gapCount": 0, "draftCount": 0,
        },
        "safety": {
            "mode": "block", "findings": [], "piiCount": 0,
            "confidentialCount": 0, "redactedCount": 0,
        },
    }
    for index, version in enumerate((None, "attacker-version")):
        payload = dict(base)
        if version is None:
            payload.pop("compiler_version")
        else:
            payload["compiler_version"] = version
        monkeypatch.setattr(adapters, "_post_json", lambda *_a, **_k: (payload, "req"))
        artifact_dir = tmp_path / f"kb-{index}"
        compiler = NaiaKbCompilerHttpAdapter(
            "https://kb.aipol.example",
            client_id="uami-client-id",
            scope=RECEIVER_SCOPE,
            allowed_origins=("https://kb.aipol.example",),
            **receiver_kwargs(),
            token_credential=FakeKbCredential(),
            contract_fetcher=fetch_receiver_contract,
            artifact_dir=artifact_dir,
        )
        with pytest.raises(adapters.PermanentProviderError, match="compiler_version"):
            compiler.compile(SourcePacket.from_dict(packet()), MockDraftAdapter().draft(SourcePacket.from_dict(packet())))
        assert not artifact_dir.exists() or list(artifact_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("NAIA_KB_COMPILER_APP_CLIENT_ID", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
        ("NAIA_KB_COMPILER_RECEIVER_DEPLOYMENT_ID", "sha256:" + "A" * 64),
    ],
)
def test_http_config_preserves_and_rejects_noncanonical_case(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    settings = {
        "POLICY_NEWS_KB_COMPILER_MODE": "http",
        "NAIA_KB_COMPILER_ENDPOINT": "https://kb.aipol.example",
        "NAIA_KB_COMPILER_ALLOWED_ORIGINS": "https://kb.aipol.example",
        "NAIA_KB_COMPILER_SCOPE": RECEIVER_SCOPE,
        "NAIA_KB_COMPILER_APP_CLIENT_ID": RECEIVER_APP_CLIENT_ID,
        "AZURE_CLIENT_ID": "uami-client-id",
        "AZURE_TENANT_ID": "tenant-id",
        "NAIA_KB_COMPILER_UAMI_PRINCIPAL_ID": "uami-principal-id",
        "NAIA_KB_COMPILER_REQUIRED_APP_ROLE": "Aipol.PolicyNews.Compile",
        "NAIA_KB_COMPILER_RECEIVER_VERSION": "1.2.3",
        "NAIA_KB_COMPILER_RECEIVER_DEPLOYMENT_ID": RECEIVER_DEPLOYMENT,
    }
    for env_name, env_value in settings.items():
        monkeypatch.setenv(env_name, env_value)
    monkeypatch.setenv(name, value)
    if name == "NAIA_KB_COMPILER_APP_CLIENT_ID":
        monkeypatch.setenv(
            "NAIA_KB_COMPILER_SCOPE", "api://aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/.default"
        )
    with pytest.raises(ValueError):
        RuntimeConfig.from_env()


def test_get_and_post_redirects_are_not_followed_or_leaked_cross_origin() -> None:
    sink = {"calls": 0, "authorization": None}

    class SinkHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            sink["calls"] += 1
            sink["authorization"] = self.headers.get("Authorization")
            self.send_response(200)
            self.end_headers()

        do_POST = do_GET

        def log_message(self, *_args):
            return

    sink_server = ThreadingHTTPServer(("127.0.0.1", 0), SinkHandler)

    class RedirectHandler(BaseHTTPRequestHandler):
        def _redirect(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{sink_server.server_port}/sink")
            self.end_headers()

        do_GET = _redirect
        do_POST = _redirect

        def log_message(self, *_args):
            return

    redirect_server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in (sink_server, redirect_server)
    ]
    for thread in threads:
        thread.start()
    origin = f"http://127.0.0.1:{redirect_server.server_port}"
    try:
        with pytest.raises(adapters.PermanentProviderError, match="redirect"):
            adapters._get_json(origin + "/contract", 2, 1024)
        with pytest.raises(adapters.PermanentProviderError, match="redirect"):
            adapters._post_json(
                origin + "/compile", {}, {"Authorization": "Bearer leaked-token"}, 2
            )
    finally:
        redirect_server.shutdown()
        sink_server.shutdown()
        redirect_server.server_close()
        sink_server.server_close()
    assert sink == {"calls": 0, "authorization": None}


def test_streaming_json_limit_is_enforced_before_parse() -> None:
    class Headers(dict):
        pass

    class Response:
        headers = Headers()

        def __init__(self) -> None:
            self.requested = 0

        def read(self, size: int) -> bytes:
            self.requested = size
            return b"{" + b"x" * size

    response = Response()
    with pytest.raises(adapters.PermanentProviderError, match="response limit"):
        adapters._read_bounded_json(response, max_bytes=1024, source="attack")
    assert response.requested == 1025


def test_foundry_adapter_uses_openai_v1_deployment_and_keeps_key_out_of_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, payload: dict, headers: dict, timeout: int):
        captured.update(url=url, payload=payload, headers=headers, timeout=timeout)
        editorial = {
            "title_ko": "공식 정책 사례",
            "summary_ko": "공식 원문 요약",
            "policy_use": "의견 분석",
            "human_review": "사람 검토",
            "relevance": "정책실험 참고",
            "caveat": "자동 결정이 아님"
        }
        return {"id": "response-123", "choices": [{"message": {"content": json.dumps(editorial)}}]}, "request-456"

    monkeypatch.setattr(adapters, "_post_json", fake_post)
    config = enabled_config(
        dry_run=False,
        foundry_region="eastus2",
        foundry_endpoint="https://aipol-ai.example.services.ai.azure.com",
        foundry_deployment="aipol-policy-news-draft",
    )
    draft = AzureFoundryDraftAdapter(config, api_key="secret-value").draft(SourcePacket.from_dict(packet()))
    assert captured["url"] == "https://aipol-ai.example.services.ai.azure.com/openai/v1/chat/completions"
    assert captured["headers"] == {"api-key": "secret-value"}
    assert captured["payload"]["model"] == "aipol-policy-news-draft"  # type: ignore[index]
    assert captured["payload"]["reasoning_effort"] == "low"  # type: ignore[index]
    assert captured["payload"]["max_completion_tokens"] == 1024  # type: ignore[index]
    assert "temperature" not in captured["payload"]  # type: ignore[operator]
    response_format = captured["payload"]["response_format"]  # type: ignore[index]
    assert response_format["type"] == "json_schema"
    schema = response_format["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "title_ko", "summary_ko", "policy_use", "human_review", "relevance", "caveat"
    }
    assert "secret-value" not in json.dumps(captured["payload"])
    assert draft.response_id == "response-123"


def test_anyllm_draft_runs_the_three_approved_stages_and_records_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    responses = [
        {
            "title": "Official policy title",
            "summary": "The agency announced a policy measure.",
            "policy_use": "Compare implementation choices.",
            "human_review": "Verify the cited source.",
            "relevance": "Relevant to public-sector AI policy.",
            "caveat": "The announcement does not report outcomes.",
        },
        {
            "verdict": "PASS",
            "issues": [],
            "summary": "All claims are supported.",
            "corrected_analysis": {
                "title": "Official policy title",
                "summary": "The agency announced a policy measure.",
                "policy_use": "Compare implementation choices.",
                "human_review": "Verify the cited source.",
                "relevance": "Relevant to public-sector AI policy.",
                "caveat": "The announcement does not report outcomes.",
            },
        },
        {
            "title_ko": "공식 정책 제목",
            "summary_ko": "기관이 정책 조치를 발표했다.",
            "policy_use": "이행 선택지를 비교할 수 있다.",
            "human_review": "인용한 원문을 확인해야 한다.",
            "relevance": "공공부문 AI 정책과 관련된다.",
            "caveat": "발표문에는 성과가 제시되지 않았다.",
        },
    ]

    def fake_post(url: str, payload: dict, headers: dict, timeout: int):
        calls.append({"url": url, "payload": payload, "headers": headers, "timeout": timeout})
        content = responses[len(calls) - 1]
        return {
            "id": f"response-{len(calls)}",
            "choices": [{"message": {"content": json.dumps(content)}}],
        }, f"request-{len(calls)}"

    monkeypatch.setattr(adapters, "_post_json", fake_post)
    config = enabled_config(
        dry_run=False,
        draft_provider="anyllm",
        review_provider="anyllm",
        anyllm_endpoint="https://api.nextain.io/v1",
        require_kb_compile=False,
        provider_approval="passed",
        provider_evidence_sha256="a" * 64,
    )
    budget = Budget(config)
    draft = adapters.AnyLlmDraftAdapter(config, api_key="secret-value", budget=budget).draft(
        SourcePacket.from_dict(packet())
    )

    assert [call["payload"]["model"] for call in calls] == [  # type: ignore[index]
        "upstage:solar-pro4",
        "azure:deepseek-v4-pro",
        "azure:gpt-5.6-luna",
    ]
    assert all(call["url"] == "https://api.nextain.io/v1/chat/completions" for call in calls)
    assert all(call["headers"] == {"Authorization": "Bearer secret-value"} for call in calls)
    assert [stage["stage"] for stage in draft.pipeline] == ["analysis", "verification", "translation"]
    assert draft.pipeline[1]["output"]["verdict"] == "PASS"
    assert "output" not in draft.pipeline[2]
    assert budget.calls == 3
    assert "secret-value" not in json.dumps(draft.pipeline)


def test_anyllm_draft_translates_only_the_corrected_analysis_when_verification_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        {
            "title": "Unsupported title",
            "summary": "An unsupported outcome claim.",
            "policy_use": "Compare outcomes.",
            "human_review": "Review source.",
            "relevance": "Policy relevance.",
            "caveat": "No caveat.",
        },
        {
            "verdict": "BLOCK",
            "issues": [
                {
                    "field": "summary",
                    "severity": "high",
                    "description": "The source does not support the outcome claim.",
                }
            ],
            "summary": "Unsupported claim detected.",
            "corrected_analysis": {
                "title": "Official title",
                "summary": "The agency announced a measure.",
                "policy_use": "Compare implementation choices.",
                "human_review": "Review the official source.",
                "relevance": "Relevant to policy implementation.",
                "caveat": "The source reports no outcome.",
            },
        },
        {
            "title_ko": "공식 제목",
            "summary_ko": "기관이 조치를 발표했다.",
            "policy_use": "이행 선택지를 비교한다.",
            "human_review": "공식 원문을 확인한다.",
            "relevance": "정책 이행과 관련된다.",
            "caveat": "원문은 성과를 보고하지 않는다.",
        },
    ]
    calls: list[str] = []

    def fake_post(url: str, payload: dict, headers: dict, timeout: int):
        calls.append(payload["model"])
        content = responses[len(calls) - 1]
        return {"choices": [{"message": {"content": json.dumps(content)}}]}, f"request-{len(calls)}"

    monkeypatch.setattr(adapters, "_post_json", fake_post)
    config = enabled_config(
        draft_provider="anyllm",
        review_provider="anyllm",
        anyllm_endpoint="https://api.nextain.io/v1",
    )

    draft = adapters.AnyLlmDraftAdapter(config, api_key="secret-value").draft(SourcePacket.from_dict(packet()))

    assert calls == ["upstage:solar-pro4", "azure:deepseek-v4-pro", "azure:gpt-5.6-luna"]
    assert draft.pipeline[1]["output"]["verdict"] == "BLOCK"


@pytest.mark.parametrize("endpoint", [
    "https://example.com",
    "http://aipol.services.ai.azure.com",
    "https://services.ai.azure.com",
    "https://aipol.services.ai.azure.com/openai",
    "https://aipol.services.ai.azure.com:443",
    "https://user@aipol.services.ai.azure.com",
    "https://aipol.services.ai.azure.com?token=leak",
])
def test_foundry_config_rejects_noncanonical_origin(endpoint: str) -> None:
    with pytest.raises(ValueError, match="HTTPS origin"):
        enabled_config(
            foundry_endpoint=endpoint,
            foundry_deployment="deployment",
            foundry_region="koreacentral",
        ).validate()
    with pytest.raises(ValueError):
        AzureFoundryDraftAdapter(enabled_config(
            foundry_endpoint=endpoint, foundry_deployment="deployment", foundry_region="koreacentral",
        ))


def test_foundry_managed_identity_is_client_bound_without_default_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Credential:
        def __init__(self, *, client_id: str):
            captured["client_id"] = client_id

        def get_token(self, scope: str):
            captured["scope"] = scope
            return types.SimpleNamespace(token="uami-token")

    azure = types.ModuleType("azure")
    identity = types.ModuleType("azure.identity")
    identity.ManagedIdentityCredential = Credential
    azure.identity = identity
    monkeypatch.setitem(sys.modules, "azure", azure)
    monkeypatch.setitem(sys.modules, "azure.identity", identity)
    config = enabled_config(
        foundry_auth_mode="managed_identity",
        foundry_managed_identity_client_id="uami-client-id",
        foundry_region="koreacentral",
        foundry_endpoint="https://aipol.services.ai.azure.com",
        foundry_deployment="deployment",
    )
    config.validate()
    headers = AzureFoundryDraftAdapter(config)._auth_headers()
    assert headers == {"Authorization": "Bearer uami-token"}
    assert captured == {
        "client_id": "uami-client-id",
        "scope": "https://ai.azure.com/.default",
    }
    assert "DefaultAzureCredential" not in Path(adapters.__file__).read_text(encoding="utf-8")
