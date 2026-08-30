"""OPA REST 客户端：发布编译后的合约数据并请求使用控制决策。"""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote

import httpx

from app.core.config import settings


class OPAError(RuntimeError):
    def __init__(self, message: str, *, code: str = "OPA_ERROR", diagnostic: str | None = None):
        super().__init__(message)
        self.code = code
        self.diagnostic = diagnostic


def _request_error(action: str, exc: httpx.HTTPError) -> OPAError:
    if isinstance(exc, httpx.TimeoutException):
        return OPAError(f"OPA {action}超时，请稍后重试", code="OPA_TIMEOUT", diagnostic=repr(exc))
    if isinstance(exc, httpx.ConnectError):
        return OPAError(f"无法连接 OPA，暂时不能完成{action}", code="OPA_UNREACHABLE", diagnostic=repr(exc))
    if isinstance(exc, httpx.HTTPStatusError):
        return OPAError(f"OPA {action}返回异常状态（HTTP {exc.response.status_code}）", code="OPA_UPSTREAM_ERROR", diagnostic=repr(exc))
    return OPAError(f"OPA {action}失败", diagnostic=repr(exc))


class OPAClient:
    def __init__(self) -> None:
        if not settings.opa_url or not settings.opa_url.startswith(("http://", "https://")):
            raise OPAError("平台未正确配置 OPA 服务地址", code="OPA_NOT_CONFIGURED")
        self._client = httpx.Client(
            base_url=settings.opa_url.rstrip("/"), trust_env=False, timeout=5.0
        )

    def publish_contract(self, contract_id: str, document: dict) -> None:
        path = "/v1/data/bonfire/contracts/" + quote(contract_id, safe="")
        try:
            response = self._client.put(path, json=document)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise _request_error("发布合约策略", exc) from exc

    def decide(self, decision_input: dict) -> dict:
        try:
            response = self._client.post(
                f"/v1/data/{settings.opa_decision_path}", json={"input": decision_input}
            )
            response.raise_for_status()
            result = response.json().get("result")
        except (httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, httpx.HTTPError):
                raise _request_error("策略决策", exc) from exc
            raise OPAError("OPA 返回了无法解析的决策结果", code="OPA_INVALID_RESPONSE", diagnostic=repr(exc)) from exc
        if not isinstance(result, dict):
            raise OPAError("OPA 未返回有效决策")
        return result


@lru_cache
def get_opa_client() -> OPAClient:
    return OPAClient()
