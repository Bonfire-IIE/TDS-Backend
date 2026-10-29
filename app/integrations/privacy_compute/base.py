"""Generic privacy-computing adapter contract.

The platform domain depends on this interface. Kuscia-specific request
shapes and identifiers are confined to the concrete adapter implementation.
"""
from __future__ import annotations

from typing import Any, Protocol


class PrivacyComputeAdapter(Protocol):
    system_type: str

    def check_capability(self, connector_ref: str, capability_code: str) -> dict[str, Any]: ...
    def provision(self, connector_ref: str) -> dict[str, Any]: ...

    def register_resource(self, connector_ref: str, resource: dict[str, Any]) -> dict[str, Any]: ...

    def delete_resource(self, connector_ref: str, external_ref: str) -> None: ...

    def submit(self, context: Any, project: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]: ...

    def status(self, context: Any, external_run_ref: str) -> dict[str, Any]: ...

    def result(self, context: Any, external_run_ref: str) -> dict[str, Any]: ...
