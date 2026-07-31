"""Fail-closed Azure Container Apps Job control for the AIPOL admin."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote


ARM_SCOPE = "https://management.azure.com/.default"
API_VERSION = "2025-01-01"
JOB_ID = re.compile(
    r"^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.App/jobs/([^/]+)$",
    re.IGNORECASE,
)
TERMINAL = {"succeeded", "failed", "stopped"}


class BatchDispatchError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class JobExecution:
    name: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None


class AzureContainerAppsJob:
    def __init__(
        self,
        *,
        enabled: bool,
        job_resource_id: str,
        managed_identity_client_id: str = "",
        credential: Any | None = None,
        opener: Any = urllib.request.urlopen,
    ) -> None:
        self.enabled = enabled
        self.job_resource_id = job_resource_id.rstrip("/")
        self.managed_identity_client_id = managed_identity_client_id
        self._credential = credential
        self._opener = opener

    @classmethod
    def from_environment(cls) -> "AzureContainerAppsJob":
        return cls(
            enabled=os.environ.get("AIPOL_BATCH_AZURE_ENABLED", "false").lower() == "true",
            job_resource_id=os.environ.get("AIPOL_BATCH_AZURE_JOB_RESOURCE_ID", ""),
            managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID", ""),
        )

    def _guard(self) -> None:
        if not self.enabled:
            raise BatchDispatchError("batch_disabled", "Azure 배치 실행 스위치가 OFF입니다")
        if not JOB_ID.fullmatch(self.job_resource_id):
            raise BatchDispatchError("job_resource_id_invalid", "명시적인 Container Apps Job resource ID가 필요합니다")

    def _get_credential(self):
        if self._credential is None:
            try:
                from azure.identity import ManagedIdentityCredential
            except ImportError as exc:
                raise BatchDispatchError("managed_identity_unavailable", "managed identity 라이브러리를 사용할 수 없습니다") from exc
            kwargs = {"client_id": self.managed_identity_client_id} if self.managed_identity_client_id else {}
            self._credential = ManagedIdentityCredential(**kwargs)
        return self._credential

    def _request(self, method: str, suffix: str) -> dict:
        self._guard()
        try:
            token = self._get_credential().get_token(ARM_SCOPE).token
            url = f"https://management.azure.com{self.job_resource_id}{suffix}"
            request = urllib.request.Request(
                url,
                method=method,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                data=b"{}" if method == "POST" else None,
            )
            with self._opener(request, timeout=15) as response:
                payload = response.read()
            return json.loads(payload.decode("utf-8")) if payload else {}
        except BatchDispatchError:
            raise
        except urllib.error.HTTPError as exc:
            raise BatchDispatchError(f"azure_http_{exc.code}", "Azure Job 요청이 거절되었습니다") from exc
        except (OSError, ValueError, KeyError) as exc:
            raise BatchDispatchError("azure_unavailable", "Azure Job 상태를 확인할 수 없습니다") from exc

    @staticmethod
    def _execution(payload: dict) -> JobExecution:
        properties = payload.get("properties") or {}
        name = str(payload.get("name") or "").strip()
        status = str(properties.get("status") or payload.get("status") or "Processing").lower()
        if not name:
            raise BatchDispatchError("azure_response_invalid", "Azure Job execution 이름이 없습니다")
        return JobExecution(
            name=name,
            status=status,
            started_at=properties.get("startTime"),
            finished_at=properties.get("endTime"),
        )

    def start(self) -> JobExecution:
        return self._execution(self._request("POST", f"/start?api-version={API_VERSION}"))

    def status(self, execution_name: str) -> JobExecution:
        if not execution_name or "/" in execution_name or "\\" in execution_name:
            raise BatchDispatchError("execution_name_invalid", "올바른 Azure execution 이름이 필요합니다")
        return self._execution(
            self._request("GET", f"/executions/{quote(execution_name, safe='')}?api-version={API_VERSION}")
        )


def runner_from_environment() -> AzureContainerAppsJob:
    return AzureContainerAppsJob.from_environment()
