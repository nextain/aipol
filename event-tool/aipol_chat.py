"""Public-chat adapter with explicit extractive and managed-identity Foundry modes."""
from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from urllib.parse import urlparse

from policy_lab.services.chatbot.models import Claim, GeneratedAnswer, KnowledgeChunk
from policy_lab.services.chatbot.security import build_generation_request
from policy_lab.services.chatbot.service import GroundedChatbot, KnowledgeRepository


class FoundryUnavailable(RuntimeError):
    pass


class AzureFoundryClaimGenerator:
    """Lazy Azure adapter. API keys are intentionally unsupported."""

    def __init__(self, reserve_cost: Callable[[], int]) -> None:
        self.endpoint = os.environ.get("AIPOL_FOUNDRY_ENDPOINT", "").rstrip("/")
        self.deployment = os.environ.get("AIPOL_FOUNDRY_DEPLOYMENT", "")
        self.client_id = os.environ.get("AZURE_CLIENT_ID", "").strip()
        # ACA managed identity exposes IDENTITY_ENDPOINT.  Refuse workstation
        # developer credentials and API-key emulation for this public service.
        if not os.environ.get("IDENTITY_ENDPOINT"):
            raise FoundryUnavailable("Azure managed identity environment is not available")
        parsed = urlparse(self.endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".services.ai.azure.com")
            or parsed.path not in {"", "/"}
            or bool(parsed.query or parsed.fragment or parsed.username or parsed.password)
            or parsed.port not in {None, 443}
            or not self.deployment
            or not self.client_id
        ):
            raise FoundryUnavailable("Foundry endpoint/deployment is not configured")
        self.reserve_cost = reserve_cost

    def generate(self, query: str, evidence: list[KnowledgeChunk] | tuple[KnowledgeChunk, ...]) -> GeneratedAnswer:
        try:
            from azure.identity import ManagedIdentityCredential
        except ImportError as exc:  # pragma: no cover - deployment dependency guard
            raise FoundryUnavailable("azure-identity is not installed") from exc
        request = build_generation_request(query, evidence)
        # Reserve before the credential/network call; failures consume the unit
        # conservatively so retries cannot exceed the configured monthly cap.
        self.reserve_cost()
        token = ManagedIdentityCredential(client_id=self.client_id).get_token(
            "https://ai.azure.com/.default"
        ).token
        schema = {
            "name": "grounded_claims",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claims"],
                "properties": {
                    "claims": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["text", "citation_chunk_ids", "evidence_quotes"],
                            "properties": {
                                "text": {"type": "string", "maxLength": 1200},
                                "citation_chunk_ids": {
                                    "type": "array", "minItems": 1, "maxItems": 4,
                                    "items": {"type": "string", "enum": list(request.allowed_chunk_ids)},
                                },
                                "evidence_quotes": {
                                    "type": "array", "minItems": 1, "maxItems": 4,
                                    "items": {"type": "string", "maxLength": 1200},
                                },
                            },
                        },
                    }
                },
            },
        }
        payload = {
            "model": self.deployment,
            "messages": [
                {"role": "system", "content": request.system_instruction},
                {"role": "user", "content": json.dumps({"query": query, "untrusted_evidence": json.loads(request.untrusted_evidence_json)}, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_schema", "json_schema": schema},
            "max_completion_tokens": 1200,
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.endpoint}/openai/v1/chat/completions", data=raw, method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(http_request, timeout=30) as response:
                raw_response = response.read(1_000_001)
                if len(raw_response) > 1_000_000:
                    raise ValueError("Foundry response exceeds size limit")
                body = json.loads(raw_response)
            parsed = json.loads(body["choices"][0]["message"]["content"])
            return GeneratedAnswer(tuple(
                Claim(
                    str(item["text"]),
                    tuple(str(value) for value in item["citation_chunk_ids"]),
                    tuple(str(value) for value in item["evidence_quotes"]),
                )
                for item in parsed["claims"]
            ))
        except Exception as exc:
            raise FoundryUnavailable("Foundry grounded generation failed") from exc


def answer(query: str, chunks: list[KnowledgeChunk], config: dict, reserve_cost: Callable[[], int]):
    repository = KnowledgeRepository(chunks)
    kwargs = {
        "minimum_score": float(config["minimum_score"]),
        "maximum_chunks": int(config["retrieval_limit"]),
        "minimum_claim_support": float(config["minimum_claim_support"]),
    }
    mode = config["generator_mode"]
    if mode == "extractive":
        return GroundedChatbot(repository, **kwargs).ask(query), "extractive"
    if mode == "azure_foundry":
        try:
            generator = AzureFoundryClaimGenerator(reserve_cost)
            return GroundedChatbot(repository, generator=generator, **kwargs).ask(query), "azure_foundry"
        except FoundryUnavailable:
            if config.get("allow_extractive_fallback"):
                return GroundedChatbot(repository, **kwargs).ask(query), "extractive_fallback"
            raise
    raise FoundryUnavailable("chatbot generator mode is OFF")
