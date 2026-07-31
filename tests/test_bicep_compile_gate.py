from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_compile_gate_covers_all_deployment_units_and_ci_invokes_it() -> None:
    script = (ROOT / "scripts" / "verify_azure_bicep.py").read_text(encoding="utf-8")
    tree = ast.parse(script)
    assert sum(
        isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith(".bicep")
        for node in ast.walk(tree)
    ) == 4
    assert '"bicep", "build"' in script
    assert '"deployment",' in script and '"validate",' in script
    assert "DEV_VALIDATION_CASES" in script
    assert '"environment=dev"' in script
    assert '"deployFoundry=true"' in script
    assert '"deployInfrastructure=true"' in script
    assert '"policyNewsEnabled=false"' in script
    assert "ARM_VALIDATE_RECEIPT" in script
    assert "protected ARM validation is restricted to rg-aipol-dev" in script
    workflow = (ROOT / ".github" / "workflows" / "verify-azure-bicep.yml").read_text(encoding="utf-8")
    assert "python scripts/verify_azure_bicep.py" in workflow
    assert "environment: aipol-dev" in workflow
    assert "run_group_validate" in workflow


def test_all_azure_units_fail_closed_on_their_expected_resource_group() -> None:
    public = (ROOT / "deploy" / "azure" / "public-site.bicep").read_text(encoding="utf-8")
    policy_ai = (ROOT / "deploy" / "azure" / "policy-ai.bicep").read_text(encoding="utf-8")
    policy_news = (ROOT / "deploy" / "azure" / "policy-news-job.bicep").read_text(encoding="utf-8")
    assert "'rg-aipol-${environment}'" in public
    assert "resourceGroupNameValidated" in public
    for template in (policy_ai, policy_news):
        assert "expectedResourceGroupName = 'rg-aipol-dev'" in template
        assert "resourceGroupNameValidated" in template
        assert "output resourceGroupScopeAccepted bool" in template


def test_policy_news_bicep_origin_guard_matches_runtime_exact_origin_policy() -> None:
    bicep = (ROOT / "deploy" / "azure" / "policy-news-job.bicep").read_text(encoding="utf-8")
    for forbidden in ("'/'", "':'", "'@'", "'?'", "'#'", "' '"):
        assert f"!contains(kbCompilerAuthority, {forbidden})" in bicep
    assert "kbCompilerEndpoint == toLower(kbCompilerEndpoint)" in bicep
    assert "kbCompilerReceiverDeploymentId" in bicep
    assert "kbCompilerRequiredAppRole" in bicep
