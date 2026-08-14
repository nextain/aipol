"""Runtime safety and provider configuration for policy-news AI calls."""

from __future__ import annotations

import os
import uuid
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit


def validate_foundry_origin(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    hostname = (parsed.hostname or "").lower()
    try:
        has_port = parsed.port is not None
    except ValueError as exc:
        raise ValueError("Azure AI Foundry endpoint port is invalid") from exc
    if (
        parsed.scheme != "https"
        or not hostname.endswith(".services.ai.azure.com")
        or hostname == "services.ai.azure.com"
        or has_port
        or parsed.path != ""
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or ":" in hostname
    ):
        raise ValueError("Azure AI Foundry endpoint must be a credential-free *.services.ai.azure.com HTTPS origin")
    return endpoint.rstrip("/")


def validate_kb_compiler_origin(endpoint: str) -> str:
    """Return a canonical, credential-free HTTPS origin for the KB service."""
    parsed = urlsplit(endpoint)
    hostname = (parsed.hostname or "").lower()
    try:
        has_port = parsed.port is not None
    except ValueError as exc:
        raise ValueError("naia-kb-compiler endpoint port is invalid") from exc
    if (
        parsed.scheme != "https"
        or not hostname
        or has_port
        or parsed.path not in ("", "/")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "naia-kb-compiler endpoint must be an exact credential-free HTTPS origin"
        )
    canonical = f"https://{hostname}"
    if endpoint != canonical:
        raise ValueError("naia-kb-compiler endpoint must use its lowercase canonical HTTPS origin")
    return canonical


def validate_anyllm_endpoint(endpoint: str) -> str:
    """Return the exact credential-free HTTPS ``/v1`` gateway endpoint."""
    parsed = urlsplit(endpoint)
    hostname = (parsed.hostname or "").lower()
    try:
        has_port = parsed.port is not None
    except ValueError as exc:
        raise ValueError("Naia AnyLLM endpoint port is invalid") from exc
    canonical = f"https://{hostname}/v1"
    if (
        parsed.scheme != "https"
        or hostname != "api.nextain.io"
        or has_port
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/v1"
        or endpoint.rstrip("/") != canonical
    ):
        raise ValueError("Naia AnyLLM endpoint must be an exact credential-free HTTPS /v1 endpoint")
    return canonical


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    if raw.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if raw.strip().lower() in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _float(name: str, default: float, minimum: float, maximum: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class RuntimeConfig:
    revision: str = "aipol-policy-news-v2"
    enabled: bool = False
    dry_run: bool = True
    max_items_per_run: int = 3
    max_provider_calls_per_run: int = 12
    max_estimated_cost_usd_per_run: float = 2.00
    estimated_analysis_cost_usd: float = 0.10
    estimated_verification_cost_usd: float = 0.10
    estimated_translation_cost_usd: float = 0.10
    estimated_review_cost_usd: float = 0.05
    estimated_kb_cost_usd: float = 0.05
    max_attempts: int = 3
    retry_base_seconds: float = 0.25
    timeout_seconds: int = 90
    foundry_region: str = ""
    foundry_endpoint: str = ""
    foundry_deployment: str = ""
    foundry_reasoning_effort: str = "low"
    foundry_max_completion_tokens: int = 1024
    foundry_auth_mode: str = "api_key"
    foundry_managed_identity_client_id: str = ""
    foundry_api_key_env: str = "AZURE_OPENAI_API_KEY"
    foundry_bearer_token_env: str = "AZURE_AI_FOUNDRY_BEARER_TOKEN"
    review_provider: str = "nemotron"
    draft_provider: str = "solar"
    anyllm_endpoint: str = ""
    anyllm_analysis_model: str = "upstage:solar-pro4"
    anyllm_verification_model: str = "azure:deepseek-v4-pro"
    anyllm_model: str = "azure:gpt-5.6-luna"
    anyllm_review_model: str = "azure:deepseek-v4-flash"
    anyllm_api_key_env: str = "ANYLLM_API_KEY"
    provider_approval: str = ""
    provider_evidence_sha256: str = ""
    require_kb_compile: bool = True
    kb_compiler_mode: str = "disabled"
    kb_compiler_endpoint: str = ""
    kb_compiler_allowed_origins: tuple[str, ...] = ()
    kb_compiler_scope: str = ""
    kb_compiler_app_client_id: str = ""
    kb_compiler_tenant_id: str = ""
    kb_compiler_uami_principal_id: str = ""
    kb_compiler_required_app_role: str = ""
    kb_compiler_receiver_version: str = ""
    kb_compiler_receiver_deployment_id: str = ""
    kb_compiler_validation_mode: str = "entra-jwt-v2-strict"
    kb_compiler_command: str = ""
    kb_compiler_timeout_seconds: int = 120
    kb_compiler_max_response_bytes: int = 1_000_000
    kb_compiler_contract_max_bytes: int = 65_536

    @property
    def estimated_draft_cost_usd(self) -> float:
        """Compatibility estimate for legacy single-stage draft adapters."""
        return self.estimated_analysis_cost_usd

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        config = cls(
            revision=os.getenv("POLICY_NEWS_CONFIG_REVISION", "aipol-policy-news-v2").strip(),
            enabled=_bool("POLICY_NEWS_ENABLED", False),
            dry_run=_bool("POLICY_NEWS_DRY_RUN", True),
            max_items_per_run=_int("POLICY_NEWS_MAX_ITEMS", 3, 1, 20),
            max_provider_calls_per_run=_int("POLICY_NEWS_MAX_CALLS", 12, 1, 100),
            max_estimated_cost_usd_per_run=_float("POLICY_NEWS_MAX_COST_USD", 2.00, 0, 100),
            estimated_analysis_cost_usd=_float("POLICY_NEWS_ESTIMATED_ANALYSIS_COST_USD", 0.10, 0, 100),
            estimated_verification_cost_usd=_float("POLICY_NEWS_ESTIMATED_VERIFICATION_COST_USD", 0.10, 0, 100),
            estimated_translation_cost_usd=_float("POLICY_NEWS_ESTIMATED_TRANSLATION_COST_USD", 0.10, 0, 100),
            estimated_review_cost_usd=_float("POLICY_NEWS_ESTIMATED_REVIEW_COST_USD", 0.05, 0, 100),
            estimated_kb_cost_usd=_float("POLICY_NEWS_ESTIMATED_KB_COST_USD", 0.05, 0, 100),
            max_attempts=_int("POLICY_NEWS_MAX_ATTEMPTS", 3, 1, 5),
            retry_base_seconds=_float("POLICY_NEWS_RETRY_BASE_SECONDS", 0.25, 0, 30),
            timeout_seconds=_int("POLICY_NEWS_TIMEOUT_SECONDS", 90, 5, 300),
            foundry_region=os.getenv("AZURE_AI_FOUNDRY_REGION", "").strip(),
            foundry_endpoint=os.getenv("AZURE_AI_FOUNDRY_ENDPOINT", "").strip().rstrip("/"),
            foundry_deployment=os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT", "").strip(),
            foundry_reasoning_effort=os.getenv("AZURE_AI_FOUNDRY_REASONING_EFFORT", "low").strip().lower(),
            foundry_max_completion_tokens=_int("AZURE_AI_FOUNDRY_MAX_COMPLETION_TOKENS", 1024, 256, 4096),
            foundry_auth_mode=os.getenv("AZURE_AI_FOUNDRY_AUTH_MODE", "api_key").strip().lower(),
            foundry_managed_identity_client_id=os.getenv("AZURE_CLIENT_ID", "").strip(),
            foundry_api_key_env=os.getenv("AZURE_AI_FOUNDRY_KEY_ENV", "AZURE_OPENAI_API_KEY").strip(),
            foundry_bearer_token_env=os.getenv("AZURE_AI_FOUNDRY_BEARER_TOKEN_ENV", "AZURE_AI_FOUNDRY_BEARER_TOKEN").strip(),
            review_provider=os.getenv("POLICY_NEWS_REVIEW_PROVIDER", "nemotron").strip().lower(),
            draft_provider=os.getenv("POLICY_NEWS_DRAFT_PROVIDER", "solar").strip().lower(),
            anyllm_endpoint=os.getenv("ANYLLM_ENDPOINT", "").strip().rstrip("/"),
            anyllm_analysis_model=os.getenv("ANYLLM_ANALYSIS_MODEL", "upstage:solar-pro4").strip(),
            anyllm_verification_model=os.getenv("ANYLLM_VERIFICATION_MODEL", "azure:deepseek-v4-pro").strip(),
            anyllm_model=os.getenv("ANYLLM_MODEL", "azure:gpt-5.6-luna").strip(),
            anyllm_review_model=os.getenv("ANYLLM_REVIEW_MODEL", "azure:deepseek-v4-flash").strip(),
            anyllm_api_key_env=os.getenv("ANYLLM_API_KEY_ENV", "ANYLLM_API_KEY").strip(),
            provider_approval=os.getenv("POLICY_NEWS_PROVIDER_APPROVAL", "").strip().lower(),
            provider_evidence_sha256=os.getenv("POLICY_NEWS_PROVIDER_EVIDENCE_SHA256", "").strip().lower(),
            require_kb_compile=_bool("POLICY_NEWS_REQUIRE_KB_COMPILE", True),
            kb_compiler_mode=os.getenv("POLICY_NEWS_KB_COMPILER_MODE", "disabled").strip().lower(),
            kb_compiler_endpoint=os.getenv("NAIA_KB_COMPILER_ENDPOINT", "").strip(),
            kb_compiler_allowed_origins=tuple(
                value.strip()
                for value in os.getenv("NAIA_KB_COMPILER_ALLOWED_ORIGINS", "").split(",")
                if value.strip()
            ),
            kb_compiler_scope=os.getenv("NAIA_KB_COMPILER_SCOPE", "").strip(),
            kb_compiler_app_client_id=os.getenv("NAIA_KB_COMPILER_APP_CLIENT_ID", "").strip(),
            kb_compiler_tenant_id=os.getenv("AZURE_TENANT_ID", "").strip(),
            kb_compiler_uami_principal_id=os.getenv("NAIA_KB_COMPILER_UAMI_PRINCIPAL_ID", "").strip(),
            kb_compiler_required_app_role=os.getenv("NAIA_KB_COMPILER_REQUIRED_APP_ROLE", "").strip(),
            kb_compiler_receiver_version=os.getenv("NAIA_KB_COMPILER_RECEIVER_VERSION", "").strip(),
            kb_compiler_receiver_deployment_id=os.getenv("NAIA_KB_COMPILER_RECEIVER_DEPLOYMENT_ID", "").strip(),
            kb_compiler_validation_mode=os.getenv("NAIA_KB_COMPILER_VALIDATION_MODE", "entra-jwt-v2-strict").strip(),
            kb_compiler_command=os.getenv("NAIA_KB_COMPILER_COMMAND", "").strip(),
            kb_compiler_timeout_seconds=_int("NAIA_KB_COMPILER_TIMEOUT_SECONDS", 120, 5, 600),
            kb_compiler_max_response_bytes=_int("NAIA_KB_COMPILER_MAX_RESPONSE_BYTES", 1_000_000, 1_024, 10_000_000),
            kb_compiler_contract_max_bytes=_int("NAIA_KB_COMPILER_CONTRACT_MAX_BYTES", 65_536, 1_024, 262_144),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.revision:
            raise ValueError("configuration revision is required")
        if self.foundry_endpoint:
            validate_foundry_origin(self.foundry_endpoint)
        if self.foundry_endpoint and not self.foundry_deployment:
            raise ValueError("Azure AI Foundry deployment is required when endpoint is configured")
        if self.foundry_endpoint and not self.foundry_region:
            raise ValueError("Azure AI Foundry region is required for provenance when endpoint is configured")
        if self.foundry_auth_mode not in {"api_key", "bearer", "managed_identity"}:
            raise ValueError("Azure AI Foundry auth mode must be api_key, bearer, or managed_identity")
        if self.foundry_auth_mode == "managed_identity" and not self.foundry_managed_identity_client_id:
            raise ValueError("AZURE_CLIENT_ID is required for managed_identity auth")
        if self.foundry_reasoning_effort not in {"low", "medium", "high"}:
            raise ValueError("Azure AI Foundry reasoning effort must be low, medium, or high")
        if self.review_provider not in {"nemotron", "anyllm", "mock"}:
            raise ValueError("review provider must be nemotron, anyllm, or mock")
        if self.draft_provider not in {"solar", "anyllm", "foundry"}:
            raise ValueError("draft provider must be solar, anyllm, or foundry")
        if self.draft_provider == "anyllm" or self.review_provider == "anyllm":
            validate_anyllm_endpoint(self.anyllm_endpoint)
        if self.draft_provider == "anyllm":
            expected_models = {
                "analysis": (self.anyllm_analysis_model, "upstage:solar-pro4"),
                "verification": (self.anyllm_verification_model, "azure:deepseek-v4-pro"),
                "translation": (self.anyllm_model, "azure:gpt-5.6-luna"),
            }
            invalid = [stage for stage, (actual, expected) in expected_models.items() if actual != expected]
            if invalid:
                raise ValueError(f"Naia AnyLLM draft pipeline has unapproved model routes: {', '.join(invalid)}")
            if not self.anyllm_api_key_env:
                raise ValueError("ANYLLM_API_KEY_ENV is required for the AnyLLM fallback")
        if self.review_provider == "anyllm":
            if self.anyllm_review_model != "azure:deepseek-v4-flash":
                raise ValueError("Naia AnyLLM independent review must use azure:deepseek-v4-flash")
            if not self.anyllm_api_key_env:
                raise ValueError("ANYLLM_API_KEY_ENV is required for AnyLLM review")
            if self.draft_provider == "anyllm" and self.anyllm_model != "azure:gpt-5.6-luna":
                raise ValueError("AnyLLM independent flow requires azure:gpt-5.6-luna for translation")
        if self.kb_compiler_mode not in {"disabled", "http", "command", "mock"}:
            raise ValueError("KB compiler mode must be disabled, http, command, or mock")
        if self.kb_compiler_mode == "http" and not self.kb_compiler_endpoint:
            raise ValueError("NAIA_KB_COMPILER_ENDPOINT is required in http mode")
        if self.kb_compiler_mode == "http" and not self.foundry_managed_identity_client_id:
            raise ValueError("AZURE_CLIENT_ID is required for KB compiler http mode")
        if self.kb_compiler_mode == "http":
            try:
                app_client_id = str(uuid.UUID(self.kb_compiler_app_client_id))
            except (ValueError, AttributeError) as exc:
                raise ValueError(
                    "NAIA_KB_COMPILER_APP_CLIENT_ID must be a canonical receiver app UUID"
                ) from exc
            if self.kb_compiler_app_client_id != app_client_id:
                raise ValueError(
                    "NAIA_KB_COMPILER_APP_CLIENT_ID must be a canonical receiver app UUID"
                )
            expected_scope = f"api://{app_client_id}/.default"
            if self.kb_compiler_scope != expected_scope:
                raise ValueError(
                    "NAIA_KB_COMPILER_SCOPE must target the approved receiver app client ID"
                )
        if self.kb_compiler_mode == "http" and not self.kb_compiler_allowed_origins:
            raise ValueError("NAIA_KB_COMPILER_ALLOWED_ORIGINS is required in http mode")
        if self.kb_compiler_mode == "http":
            required_receiver_values = {
                "AZURE_TENANT_ID": self.kb_compiler_tenant_id,
                "NAIA_KB_COMPILER_UAMI_PRINCIPAL_ID": self.kb_compiler_uami_principal_id,
                "NAIA_KB_COMPILER_REQUIRED_APP_ROLE": self.kb_compiler_required_app_role,
                "NAIA_KB_COMPILER_RECEIVER_VERSION": self.kb_compiler_receiver_version,
                "NAIA_KB_COMPILER_RECEIVER_DEPLOYMENT_ID": self.kb_compiler_receiver_deployment_id,
                "NAIA_KB_COMPILER_VALIDATION_MODE": self.kb_compiler_validation_mode,
            }
            missing = [name for name, value in required_receiver_values.items() if not value]
            if missing:
                raise ValueError(f"KB compiler HTTP receiver contract is incomplete: {', '.join(missing)}")
            deployment = self.kb_compiler_receiver_deployment_id
            if not deployment.startswith("sha256:") or len(deployment) != 71 or any(
                character not in "0123456789abcdef" for character in deployment[7:]
            ):
                raise ValueError("NAIA_KB_COMPILER_RECEIVER_DEPLOYMENT_ID must be an immutable sha256 digest")
            if self.kb_compiler_validation_mode != "entra-jwt-v2-strict":
                raise ValueError("NAIA_KB_COMPILER_VALIDATION_MODE must be entra-jwt-v2-strict")
        if self.kb_compiler_mode == "command" and not self.kb_compiler_command:
            raise ValueError("NAIA_KB_COMPILER_COMMAND is required in command mode")
        if self.kb_compiler_endpoint:
            endpoint_origin = validate_kb_compiler_origin(self.kb_compiler_endpoint)
            allowed_origins = {
                validate_kb_compiler_origin(origin)
                for origin in self.kb_compiler_allowed_origins
            }
            if endpoint_origin not in allowed_origins:
                raise ValueError("naia-kb-compiler endpoint is not in the explicit origin allowlist")
        if self.enabled and self.require_kb_compile and self.kb_compiler_mode == "disabled":
            raise ValueError("enabled policy-news requires a configured KB compiler")
        if not self.require_kb_compile and self.kb_compiler_mode != "disabled":
            raise ValueError("review-only policy-news must keep the KB compiler disabled")
        if self.enabled and not self.dry_run and self.kb_compiler_mode == "mock":
            raise ValueError("enabled non-dry-run policy-news requires http or command KB compiler mode")
        if self.enabled and not self.dry_run and not self.require_kb_compile:
            if self.provider_approval != "passed":
                raise ValueError("enabled provider calls require POLICY_NEWS_PROVIDER_APPROVAL=passed")
            digest = self.provider_evidence_sha256
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ValueError("provider quality evidence must be a lowercase SHA-256 digest")

    def safe_snapshot(self) -> dict[str, object]:
        """Safe provenance snapshot with executable and remote target details omitted."""
        snapshot = asdict(self)
        snapshot.pop("kb_compiler_endpoint", None)
        snapshot.pop("kb_compiler_allowed_origins", None)
        snapshot.pop("kb_compiler_scope", None)
        snapshot.pop("kb_compiler_app_client_id", None)
        snapshot.pop("kb_compiler_tenant_id", None)
        snapshot.pop("kb_compiler_uami_principal_id", None)
        snapshot.pop("kb_compiler_required_app_role", None)
        snapshot.pop("kb_compiler_receiver_version", None)
        snapshot.pop("kb_compiler_receiver_deployment_id", None)
        snapshot.pop("kb_compiler_command", None)
        snapshot.pop("anyllm_endpoint", None)
        snapshot.pop("anyllm_api_key_env", None)
        snapshot["anyllm_configured"] = self.draft_provider == "anyllm" or self.review_provider == "anyllm"
        snapshot["kb_compiler_configured"] = self.kb_compiler_mode in {"http", "command", "mock"}
        return snapshot

    def public_snapshot(self) -> dict[str, object]:
        """Backward-compatible alias for the safe provenance snapshot."""
        return self.safe_snapshot()


class Budget:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.calls = 0
        self.estimated_cost_usd = 0.0

    def reserve(self, *, estimated_cost_usd: float = 0.0) -> None:
        if not self.config.enabled:
            raise RuntimeError("policy-news kill switch is OFF (POLICY_NEWS_ENABLED=false)")
        if self.calls + 1 > self.config.max_provider_calls_per_run:
            raise RuntimeError("provider call quota exceeded for this run")
        if self.estimated_cost_usd + estimated_cost_usd > self.config.max_estimated_cost_usd_per_run:
            raise RuntimeError("estimated provider cost budget exceeded for this run")
        self.calls += 1
        self.estimated_cost_usd += estimated_cost_usd
