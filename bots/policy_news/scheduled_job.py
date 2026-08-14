"""Azure Container Apps Job entrypoint for bounded daily collection and review.

This entrypoint never calls the publication methods. Its furthest automatic
state is ``kb_compiled``; release still requires explicit human approval.
"""

from __future__ import annotations

import json
import os
import sys

from config import Budget, RuntimeConfig


def build_knowledge_compiler(config: RuntimeConfig, budget: Budget):
    """Build the required compiler without importing provider modules while OFF."""
    from adapters import NaiaKbCompilerCommandAdapter, NaiaKbCompilerHttpAdapter

    if config.kb_compiler_mode == "http":
        return NaiaKbCompilerHttpAdapter(
            config.kb_compiler_endpoint,
            client_id=config.foundry_managed_identity_client_id,
            app_client_id=config.kb_compiler_app_client_id,
            scope=config.kb_compiler_scope,
            allowed_origins=config.kb_compiler_allowed_origins,
            tenant_id=config.kb_compiler_tenant_id,
            principal_id=config.kb_compiler_uami_principal_id,
            required_app_role=config.kb_compiler_required_app_role,
            receiver_version=config.kb_compiler_receiver_version,
            deployment_id=config.kb_compiler_receiver_deployment_id,
            validation_mode=config.kb_compiler_validation_mode,
            timeout=config.kb_compiler_timeout_seconds,
            max_response_bytes=config.kb_compiler_max_response_bytes,
            contract_max_bytes=config.kb_compiler_contract_max_bytes,
            budget=budget,
        )
    if config.kb_compiler_mode == "command":
        return NaiaKbCompilerCommandAdapter(
            config.kb_compiler_command,
            timeout=config.kb_compiler_timeout_seconds,
            budget=budget,
        )
    if config.kb_compiler_mode == "disabled" and not config.require_kb_compile:
        return None
    raise ValueError("scheduled policy-news requires http or command KB compiler mode")


def main() -> int:
    config = RuntimeConfig.from_env()
    if not config.enabled:
        print(json.dumps({"status": "stopped", "reason": "POLICY_NEWS_ENABLED=false"}))
        return 0
    if config.dry_run:
        print("Scheduled Azure job refuses dry-run with real cloud adapters; use run_v2.py mocks for rehearsal", file=sys.stderr)
        return 2
    if config.max_items_per_run > 3:
        print("Scheduled collector permits at most 3 source packets", file=sys.stderr)
        return 2
    if (config.draft_provider == "foundry" or config.kb_compiler_mode == "http") and config.foundry_auth_mode != "managed_identity":
        print("Scheduled Azure job requires AZURE_AI_FOUNDRY_AUTH_MODE=managed_identity", file=sys.stderr)
        return 2
    account_url = os.getenv("AZURE_STORAGE_BLOB_URL", "").strip().rstrip("/")
    if not account_url:
        print("AZURE_STORAGE_BLOB_URL is required", file=sys.stderr)
        return 2

    # Keep the disabled path independent of provider, Azure SDK and workspace-
    # only modules. A stopped job must be able to exit before cloud imports as
    # well as before cloud access.
    from adapters import (
        AnyLlmDraftAdapter,
        AnyLlmReviewAdapter,
        AzureFoundryDraftAdapter,
        NemotronReviewAdapter,
        PermanentProviderError,
        SolarDraftAdapter,
        TransientProviderError,
    )
    from azure_blob_store import ActiveRunError, AzureBlobRunStore
    from collector import collect
    from orchestrator import PolicyNewsOrchestrator, configured_official_hosts

    draft_provider = config.draft_provider
    budget = Budget(config)
    if draft_provider == "foundry":
        draft = AzureFoundryDraftAdapter(config, budget=budget)
    elif draft_provider == "solar":
        draft = SolarDraftAdapter(budget=budget)
    elif draft_provider == "anyllm":
        draft = AnyLlmDraftAdapter(config, budget=budget)
    else:
        print("POLICY_NEWS_DRAFT_PROVIDER must be foundry, solar, or anyllm", file=sys.stderr)
        return 2
    if config.review_provider == "nemotron":
        import nemotron_review
        if not nemotron_review.api_key():
            print("OPENROUTER_API_KEY is required through the approved secret boundary", file=sys.stderr)
            return 2
        review = NemotronReviewAdapter(budget=budget)
    elif config.review_provider == "anyllm":
        review = AnyLlmReviewAdapter(config, budget=budget)
    else:
        print("Scheduled job requires nemotron or anyllm independent review; mock is rehearsal-only", file=sys.stderr)
        return 2
    compiler = build_knowledge_compiler(config, budget)
    store = AzureBlobRunStore(account_url)
    orchestrator = PolicyNewsOrchestrator(
        config=config,
        draft_port=draft,
        review_port=review,
        knowledge_compiler=compiler,
        store=store,
        allowed_hosts=configured_official_hosts(),
    )

    packets = collect(max_items=config.max_items_per_run, timeout=min(config.timeout_seconds, 30))
    results: list[dict[str, str]] = []
    completed_count = 0
    failed_count = 0
    for packet in packets:
        try:
            with store.claim_source(packet.content_sha256):
                record = orchestrator.run(packet.provider_payload())
                results.append({"run_id": record.run_id, "state": record.state.value, "source_id": packet.source_id})
                completed_count += 1
        except ActiveRunError:
            results.append({"run_id": "", "state": "already_active", "source_id": packet.source_id})
            completed_count += 1
        except (PermanentProviderError, TransientProviderError) as exc:
            results.append({
                "run_id": "",
                "state": "provider_failed",
                "source_id": packet.source_id,
                "error_type": type(exc).__name__,
            })
            failed_count += 1
    status = "completed_with_errors" if failed_count else "completed"
    print(json.dumps({
        "status": status,
        "collected": len(packets),
        "completed": completed_count,
        "failed": failed_count,
        "provider_calls": budget.calls,
        "estimated_cost_usd": budget.estimated_cost_usd,
        "runs": results,
    }, ensure_ascii=False))
    return 0 if completed_count or not packets else 1


if __name__ == "__main__":
    raise SystemExit(main())
