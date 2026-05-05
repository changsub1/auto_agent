"""Local FastAPI client used by the Discord adapter."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class LocalApiError(RuntimeError):
    """Raised when the local FastAPI sidecar rejects or fails a request."""


@dataclass(frozen=True)
class LocalApiClient:
    base_url: str

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/runs", payload)

    async def list_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({"limit": limit})
        return await self._request("GET", f"/runs?{query}")

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/runs/{_quote(run_id)}")

    async def list_events(self, run_id: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/runs/{_quote(run_id)}/events")

    async def get_active_step(self, run_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/runs/{_quote(run_id)}/active-step")

    async def list_logs(self, run_id: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/runs/{_quote(run_id)}/logs")

    async def read_log_tail(self, run_id: str, path: str, *, lines: int = 80) -> dict[str, Any]:
        query = urllib.parse.urlencode({"path": path, "lines": lines})
        return await self._request("GET", f"/runs/{_quote(run_id)}/logs/tail?{query}")

    async def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/runs/{_quote(run_id)}/artifacts")

    async def read_artifact(self, run_id: str, path: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"path": path})
        return await self._request("GET", f"/runs/{_quote(run_id)}/artifacts/content?{query}")

    async def approve_run(self, run_id: str, *, user_id: int | str, feedback: str = "") -> dict[str, Any]:
        return await self._post_action(f"/runs/{_quote(run_id)}/approve", user_id=user_id, feedback=feedback)

    async def request_changes(self, run_id: str, *, user_id: int | str, feedback: str) -> dict[str, Any]:
        return await self._post_action(f"/runs/{_quote(run_id)}/request-changes", user_id=user_id, feedback=feedback)

    async def cancel_run(self, run_id: str, *, user_id: int | str, feedback: str = "") -> dict[str, Any]:
        return await self._post_action(f"/runs/{_quote(run_id)}/cancel", user_id=user_id, feedback=feedback)

    async def approve_qa(self, run_id: str, *, user_id: int | str, feedback: str = "") -> dict[str, Any]:
        return await self._post_action(f"/runs/{_quote(run_id)}/qa/approve", user_id=user_id, feedback=feedback)

    async def request_qa_fix(self, run_id: str, *, user_id: int | str, feedback: str) -> dict[str, Any]:
        return await self._post_action(f"/runs/{_quote(run_id)}/qa/request-fix", user_id=user_id, feedback=feedback)

    async def _post_action(self, path: str, *, user_id: int | str, feedback: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            path,
            {
                "user_id": str(user_id),
                "feedback": feedback,
            },
        )

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        return await asyncio.to_thread(self._request_sync, method, path, payload)

    def _request_sync(self, method: str, path: str, payload: dict[str, Any] | None) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise LocalApiError(f"Local API returned {exc.code}: {details}") from exc
        except OSError as exc:
            raise LocalApiError(f"Cannot reach local API at {self.base_url}: {exc}") from exc
        if not raw:
            return {}
        return json.loads(raw)


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")
