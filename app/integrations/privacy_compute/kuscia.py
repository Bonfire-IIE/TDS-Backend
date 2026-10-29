"""Compatibility helpers for legacy adapter-boundary tests.

Runtime Kuscia execution lives in the connector Portal execution gateway.
This module intentionally contains no client, endpoint, certificate, Domain or
job submission logic. The small pure helpers remain available to migration
code that normalizes downstream schemas and result references.
"""
from __future__ import annotations

import json
from typing import Any


class KusciaPrivacyComputeAdapter:
    system_type = "privacy-compute"

    _COLUMN_TYPE_MAP = {
        "string": "str", "text": "str", "varchar": "str",
        "integer": "int64", "int": "int64", "long": "int64",
        "double": "float64", "float": "float64", "boolean": "bool",
        "datetime": "str", "date": "str",
    }

    def __init__(self, client=None):
        # Kept only for compatibility with old pure result tests. It is never
        # used to contact a Kuscia endpoint.
        self.client = client

    @classmethod
    def _columns_for_execution_system(cls, columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for column in columns:
            item = dict(column)
            raw_type = str(item.get("type") or "str").lower()
            item["type"] = cls._COLUMN_TYPE_MAP.get(raw_type, raw_type)
            normalized.append(item)
        return normalized

    def result(self, context: Any, external_run_ref: str) -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError("结果必须由连接器执行网关回报")
        job = self.client.query_job(external_run_ref)
        tasks = job.get("tasks") or []
        task_config = json.loads(tasks[0].get("task_input_config") or "{}") if tasks else {}
        parties = [p.get("domain_id") for p in (tasks[0].get("parties") or []) if p.get("domain_id")] if tasks else []
        outputs = []
        seen = set()
        for resource_ref, uri in zip(task_config.get("sf_output_ids") or [], task_config.get("sf_output_uris") or []):
            key = (resource_ref, uri)
            if key in seen:
                continue
            seen.add(key)
            outputs.append({"resource_ref": resource_ref, "uri": uri, "format": uri.rsplit(".", 1)[-1].lower() if "." in uri else None, "parties": parties})
        return {"external_run_ref": external_run_ref, "outputs": outputs}
