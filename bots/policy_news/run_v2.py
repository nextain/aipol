"""CLI for the provider-neutral policy-news pipeline (never auto-publishes)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adapters import (
    AnyLlmDraftAdapter,
    AnyLlmReviewAdapter,
    AzureFoundryDraftAdapter,
    MockDraftAdapter,
    MockKbCompilerAdapter,
    MockReviewAdapter,
    NaiaKbCompilerCommandAdapter,
    NaiaKbCompilerHttpAdapter,
    NemotronReviewAdapter,
    SolarDraftAdapter,
)
from config import Budget, RuntimeConfig
from orchestrator import FileRunStore, PolicyNewsOrchestrator


def main() -> int:
    parser = argparse.ArgumentParser(description="AIPOL policy-news review pipeline")
    parser.add_argument("source_packet", type=Path)
    parser.add_argument("--draft-provider", choices=("foundry", "solar", "anyllm", "mock"), default="foundry")
    parser.add_argument("--confirm-provider-call", action="store_true", help="required for non-mock provider calls")
    parser.add_argument("--state-dir", type=Path)
    args = parser.parse_args()

    config = RuntimeConfig.from_env()
    if not config.enabled:
        print(json.dumps({"status": "stopped", "reason": "POLICY_NEWS_ENABLED=false"}))
        return 0
    if config.dry_run and (
        args.draft_provider != "mock"
        or config.review_provider != "mock"
        or config.kb_compiler_mode != "mock"
    ):
        print("dry-run permits mock adapters only", file=sys.stderr)
        return 2
    if args.draft_provider != "mock" and not args.confirm_provider_call:
        print("--confirm-provider-call is required for non-mock providers", file=sys.stderr)
        return 2
    budget = Budget(config)
    if args.draft_provider == "foundry":
        draft = AzureFoundryDraftAdapter(config, budget=budget)
    elif args.draft_provider == "solar":
        draft = SolarDraftAdapter(budget=budget)
    elif args.draft_provider == "anyllm":
        draft = AnyLlmDraftAdapter(config, budget=budget)
    else:
        draft = MockDraftAdapter()
    if config.review_provider == "mock":
        review = MockReviewAdapter()
    elif config.review_provider == "anyllm":
        review = AnyLlmReviewAdapter(config, budget=budget)
    else:
        review = NemotronReviewAdapter(budget=budget)

    artifact_dir = (args.state_dir / "kb") if args.state_dir else None
    compiler = None
    if config.kb_compiler_mode == "http":
        compiler = NaiaKbCompilerHttpAdapter(
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
            artifact_dir=artifact_dir,
        )
    elif config.kb_compiler_mode == "command":
        compiler = NaiaKbCompilerCommandAdapter(
            config.kb_compiler_command,
            timeout=config.kb_compiler_timeout_seconds,
            budget=budget,
            artifact_dir=artifact_dir,
        )
    elif config.kb_compiler_mode == "mock":
        if artifact_dir is None:
            artifact_dir = Path(__file__).resolve().parents[2] / "data-private" / "policy-news" / "kb"
        compiler = MockKbCompilerAdapter(artifact_dir)

    store = FileRunStore(args.state_dir) if args.state_dir else FileRunStore()
    packet = json.loads(args.source_packet.read_text(encoding="utf-8"))
    record = PolicyNewsOrchestrator(
        config=config,
        draft_port=draft,
        review_port=review,
        knowledge_compiler=compiler,
        store=store,
    ).run(packet)
    print(json.dumps({"run_id": record.run_id, "idempotency_key": record.idempotency_key, "state": record.state.value}, ensure_ascii=False))
    return 0 if record.state.value not in {"review_blocked", "rejected"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
