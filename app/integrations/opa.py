"""OPA REST 客户端：发布编译后的合约数据并请求使用控制决策。"""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote

import httpx

from app.core.config import settings


class OPAError(RuntimeError):
    pass


class OPAClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=settings.opa_url.rstrip("/"), trust_env=False, timeout=5.0
        )

    def publish_contract(self, contract_id: str, document: dict) -> None:
        path = "/v1/data/bonfire/contracts/" + quote(contract_id, safe="")
        try:
            response = self._client.put(path, json=document)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OPAError(f"发布合约策略失败: {exc}") from exc

    def decide(self, decision_input: dict) -> dict:
        try:
            response = self._client.post(
                f"/v1/data/{settings.opa_decision_path}", json={"input": decision_input}
            )
            response.raise_for_status()
            result = response.json().get("result")
        except (httpx.HTTPError, ValueError) as exc:
            raise OPAError(f"OPA 决策失败: {exc}") from exc
        if not isinstance(result, dict):
            raise OPAError("OPA 未返回有效决策")
        return result


@lru_cache
def get_opa_client() -> OPAClient:
    return OPAClient()
