from __future__ import annotations

from typing import Any


class ConnectorGatewayAdapter:
    """Center-side facade for connector execution gateways.

    The center intentionally has no Kuscia client. Runtime work is dispatched
    through the gateway request endpoints owned by each connector Portal.
    """
    system_type = "privacy-compute"

    def provision(self, connector_ref: str) -> dict[str, Any]:
        return {"adapter_type": self.system_type, "implementation_ref": connector_ref, "mode": "p2p", "node_type": "autonomy"}

    def check_capability(self, connector_ref: str, capability_code: str) -> dict[str, Any]:
        return {"available": False, "capability": capability_code, "reason": "必须由连接器 Portal 提交本地执行网关探活结果"}


def get_privacy_compute_adapter(system_type: str = "privacy-compute"):
    if system_type in {"privacy-compute", "privacy-compute.kuscia"}:
        return ConnectorGatewayAdapter()
    raise ValueError(f"不支持的数据利用系统: {system_type}")
