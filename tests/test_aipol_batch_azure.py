from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest


MODULE = Path(__file__).parents[1] / "event-tool" / "aipol_batch.py"
SPEC = importlib.util.spec_from_file_location("aipol_batch_unit", MODULE)
assert SPEC and SPEC.loader
batch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = batch
SPEC.loader.exec_module(batch)

JOB_ID = "/subscriptions/000/resourceGroups/rg-aipol-dev/providers/Microsoft.App/jobs/caj-aipol-policy-news-daily-dev"


class Credential:
    def get_token(self, scope: str):
        assert scope == batch.ARM_SCOPE
        return type("Token", (), {"token": "managed-identity-token"})()


class Response:
    def __init__(self, value: dict):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self) -> bytes:
        return json.dumps(self.value).encode()


def test_default_off_fails_before_identity_or_network() -> None:
    runner = batch.AzureContainerAppsJob(enabled=False, job_resource_id="", opener=lambda *_a, **_k: pytest.fail("network"))
    with pytest.raises(batch.BatchDispatchError, match="OFF") as caught:
        runner.start()
    assert caught.value.code == "batch_disabled"


def test_managed_identity_starts_and_reads_explicit_job_execution() -> None:
    requests = []
    payloads = iter([
        {"name": "job-exec-1", "properties": {"status": "Running", "startTime": "2026-07-29T00:00:00Z"}},
        {"name": "job-exec-1", "properties": {"status": "Succeeded", "endTime": "2026-07-29T00:01:00Z"}},
    ])

    def open_request(request, timeout):
        requests.append((request, timeout))
        return Response(next(payloads))

    runner = batch.AzureContainerAppsJob(enabled=True, job_resource_id=JOB_ID, credential=Credential(), opener=open_request)
    assert runner.start().status == "running"
    assert runner.status("job-exec-1").status == "succeeded"
    assert requests[0][0].full_url.endswith("/start?api-version=2025-01-01")
    assert requests[1][0].full_url.endswith("/executions/job-exec-1?api-version=2025-01-01")
    assert requests[0][0].headers["Authorization"] == "Bearer managed-identity-token"


def test_transient_failure_does_not_poison_later_recovery() -> None:
    calls = 0

    def recover(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.URLError("temporary")
        return Response({"name": "job-exec-2", "properties": {"status": "Running"}})

    runner = batch.AzureContainerAppsJob(enabled=True, job_resource_id=JOB_ID, credential=Credential(), opener=recover)
    with pytest.raises(batch.BatchDispatchError) as caught:
        runner.start()
    assert caught.value.code == "azure_unavailable"
    assert runner.start().name == "job-exec-2"


def test_resource_and_execution_identifiers_are_fail_closed() -> None:
    bad = batch.AzureContainerAppsJob(enabled=True, job_resource_id="https://evil.example/job", credential=Credential())
    with pytest.raises(batch.BatchDispatchError) as caught:
        bad.start()
    assert caught.value.code == "job_resource_id_invalid"

    good = batch.AzureContainerAppsJob(enabled=True, job_resource_id=JOB_ID, credential=Credential())
    with pytest.raises(batch.BatchDispatchError) as caught:
        good.status("../other")
    assert caught.value.code == "execution_name_invalid"
