"""Compile every deployable AIPOL Bicep unit; optionally validate in a guarded RG."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = (
    ROOT / "deploy" / "azure" / "public-site.bicep",
    ROOT / "deploy" / "azure" / "policy-ai.bicep",
    ROOT / "deploy" / "azure" / "policy-news-job.bicep",
    ROOT / "deploy" / "azure" / "event-tool-dev" / "main.bicep",
)

DEV_VALIDATION_CASES = {
    TEMPLATES[0]: {
        "parameters": ("environment=dev",),
        "active": ("dev static-site resource", "rg-aipol-dev guard"),
        "inactive": (),
    },
    TEMPLATES[1]: {
        "parameters": ("deployFoundry=true", "deployModel=false"),
        "active": ("Foundry account", "rg-aipol-dev guard"),
        "inactive": ("model deployment pending model/quota discovery", "inference role pending principal"),
    },
    TEMPLATES[2]: {
        "parameters": (
            "deployInfrastructure=true",
            "deployJob=true",
            "policyNewsEnabled=false",
            "enableSchedule=false",
            "containerImage=example.invalid/aipol/policy-news@sha256:" + "0" * 64,
        ),
        "active": ("storage", "ACR", "Container Apps environment", "UAMI", "job", "scoped RBAC", "rg-aipol-dev guard"),
        "inactive": ("runtime kill switch", "schedule", "HTTP compiler pending receiver attestation", "OpenRouter secret pending versioned URI", "container image existence/pull is outside ARM validation"),
    },
    TEMPLATES[3]: {
        "parameters": ("deployInfrastructure=true", "deployApp=false"),
        "active": ("storage", "ACR", "Container Apps environment", "UAMI", "Key Vault", "scoped RBAC", "rg-aipol-dev guard"),
        "inactive": ("application pending pinned image and versioned secrets",),
    },
}


def _run(arguments: list[str]) -> None:
    subprocess.run(arguments, cwd=ROOT, check=True)


def _run_expected_failure(arguments: list[str], *, expected_message: str) -> None:
    completed = subprocess.run(arguments, cwd=ROOT, capture_output=True, text=True)
    if completed.returncode == 0:
        raise RuntimeError("negative ARM validation unexpectedly accepted an invalid guard value")
    if expected_message not in completed.stdout + completed.stderr:
        raise RuntimeError(
            "negative ARM validation failed for an unexpected reason; digest guard was not observed"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--validate-resource-group",
        help="Optional existing development RG. This invokes validate only and never create.",
    )
    args = parser.parse_args()
    az = shutil.which("az")
    if not az:
        raise SystemExit("Azure CLI (az) is required for Bicep verification")
    missing = [str(path.relative_to(ROOT)) for path in TEMPLATES if not path.is_file()]
    if missing:
        raise SystemExit(f"missing Bicep templates: {', '.join(missing)}")
    if args.validate_resource_group and args.validate_resource_group != "rg-aipol-dev":
        raise SystemExit("protected ARM validation is restricted to rg-aipol-dev")
    for template in TEMPLATES:
        relative = str(template.relative_to(ROOT))
        print(f"Compiling {relative}", flush=True)
        _run([az, "bicep", "build", "--file", str(template), "--stdout"])
        if args.validate_resource_group:
            case = DEV_VALIDATION_CASES[template]
            receipt = {
                "schema_version": "aipol-arm-validate-receipt-v1",
                "resource_group": args.validate_resource_group,
                "template": relative.replace("\\", "/"),
                "parameters": list(case["parameters"]),
                "active_branches": list(case["active"]),
                "intentionally_inactive_branches": list(case["inactive"]),
            }
            print("ARM_VALIDATE_RECEIPT " + json.dumps(receipt, sort_keys=True), flush=True)
            _run(
                [
                    az,
                    "deployment",
                    "group",
                    "validate",
                    "--resource-group",
                    args.validate_resource_group,
                    "--template-file",
                    str(template),
                    "--parameters",
                    *case["parameters"],
                ]
            )
            if template == TEMPLATES[2]:
                negative_parameters = (
                    "deployInfrastructure=false",
                    "deployJob=false",
                    "policyNewsEnabled=true",
                    "kbCompilerMode=http",
                    "kbCompilerEndpoint=https://kb.aipol.example",
                    "kbCompilerAllowedOrigin=https://kb.aipol.example",
                    "kbCompilerAppClientId=11111111-1111-4111-8111-111111111111",
                    "kbCompilerScope=api://11111111-1111-4111-8111-111111111111/.default",
                    "kbCompilerRequiredAppRole=Aipol.PolicyNews.Compile",
                    "kbCompilerReceiverVersion=1.2.3",
                    "kbCompilerReceiverDeploymentId=sha256:" + "z" * 64,
                )
                print(
                    "ARM_NEGATIVE_GUARD_RECEIPT "
                    + json.dumps(
                        {
                            "schema_version": "aipol-arm-negative-guard-receipt-v1",
                            "resource_group": args.validate_resource_group,
                            "template": relative.replace("\\", "/"),
                            "attack": "nonhex_receiver_deployment_digest",
                            "expected": "rejected",
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                _run_expected_failure(
                    [
                        az,
                        "deployment",
                        "group",
                        "validate",
                        "--resource-group",
                        args.validate_resource_group,
                        "--template-file",
                        str(template),
                        "--parameters",
                        *negative_parameters,
                    ],
                    expected_message=(
                        "kbCompilerReceiverDeploymentId must be an immutable lowercase sha256 digest"
                    ),
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
