from __future__ import annotations

"""Center-orchestrated execution across two connector Portals."""

import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import settings
from app.core.execution_signatures import center_dispatch_request
from app.services.execution_compat import normalize_execution_request


class DispatchError(Exception):
    def __init__(self, connector_id: str, message: str, *, retryable: bool = False, status_code: int | None = None):
        super().__init__(message)
        self.connector_id, self.message, self.retryable = connector_id, message, retryable
        self.status_code = status_code


def _endpoint(value: Any, connector_id: str) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    parsed = urlsplit(endpoint)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment):
        raise DispatchError(connector_id, "连接器 Portal 地址必须是无凭据、无路径的 HTTP(S) 根地址")
    return endpoint


def _post(endpoint: str, run_id: str, connector_id: str, action: str,
          body: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
    if not endpoint:
        raise DispatchError(connector_id, "连接器 Portal 地址缺失")
    url = endpoint + f"/portal/integrations/privacy-compute/execution-requests/{run_id}/{action}"
    raw, headers = center_dispatch_request(url, connector_id, body)
    try:
        response = httpx.post(
            url, headers=headers, content=raw,
            timeout=timeout or settings.execution_dispatch_timeout_seconds,
            follow_redirects=False, trust_env=False,
        )
        payload = response.json()
    except httpx.HTTPError as exc:
        raise DispatchError(connector_id, f"连接器执行网关不可达: {exc}", retryable=True) from exc
    except ValueError as exc:
        raise DispatchError(connector_id, f"连接器执行网关返回非 JSON 响应: {exc}") from exc
    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        raise DispatchError(
            connector_id,
            f"HTTP {response.status_code}: {detail or response.text[:1000]}",
            retryable=response.status_code >= 500 or (response.status_code == 409 and detail == "compute_inputs_preparing"),
            status_code=response.status_code,
        )
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(data, dict):
        raise DispatchError(connector_id, "连接器执行网关返回了无效响应")
    return data


def dispatch_run(run_id: str, request: dict[str, Any]) -> dict[str, Any]:
    request = normalize_execution_request(request, scheduling_mode=settings.pets_scheduler_mode)
    if settings.pets_scheduler_mode == "master-lite":
        from app.services.master_execution import dispatch_master_run
        return dispatch_master_run(run_id, request)
    provider = str(request.get("provider_connector_id") or "")
    consumer = str(request.get("consumer_connector_id") or "")
    dispatch = str(request.get("dispatch_connector_id") or "")
    endpoints = {
        provider: _endpoint(request.get("provider_connector_endpoint"), provider),
        consumer: _endpoint(request.get("consumer_connector_endpoint"), consumer),
    }
    if not provider or not consumer or provider == consumer or dispatch not in endpoints:
        raise DispatchError(dispatch, "执行请求的参与方或调度方无效")

    base_body = {"execution_request": request}
    identities = {
        connector_id: _post(endpoint, run_id, connector_id, "identity", {
            "connector_id": connector_id, **base_body,
        }, 30)
        for connector_id, endpoint in endpoints.items()
    }
    prepared: dict[str, dict[str, Any]] = {}
    for connector_id, endpoint in endpoints.items():
        peer_id = consumer if connector_id == provider else provider
        prepared[connector_id] = _post(endpoint, run_id, connector_id, "prepare", {
            "connector_id": connector_id,
            "execution_request": request,
            "peer_identity": identities[peer_id],
        })

    peer_id = consumer if dispatch == provider else provider
    result = _post(endpoints[dispatch], run_id, dispatch, "execute", {
        "connector_id": dispatch,
        "execution_request": request,
        "peer_prepared": prepared[peer_id],
    })
    deadline = time.monotonic() + settings.execution_dispatch_timeout_seconds
    while time.monotonic() < deadline:
        if str(result.get("status") or "") in {"succeeded", "failed", "cancelled"}:
            return result
        time.sleep(max(0.1, settings.execution_status_poll_seconds))
        try:
            result = _post(endpoints[dispatch], run_id, dispatch, "sync", {
                "connector_id": dispatch,
                "execution_request": request,
            }, min(30, settings.execution_dispatch_timeout_seconds))
        except DispatchError as exc:
            if not exc.retryable:
                raise
            # A submitted KusciaJob remains authoritative. A temporary polling
            # failure must not compensate usage or overwrite it with a false
            # failed terminal state; Connector recovery continues reporting it.
            continue
    return {**result, "polling_deferred": True}
