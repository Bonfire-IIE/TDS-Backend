"""Normalize legacy privacy-computing requests for the generic execution plane.

The historical privacy project stores an ``application`` object and two
provider/consumer fields. The project DAG stores ``applications`` and an
explicit participant list. This adapter only adds deterministic aliases; it
never invents engine identifiers or changes resource ownership.
"""
from __future__ import annotations
from typing import Any


def normalize_execution_request(request: dict[str, Any], *, scheduling_mode: str | None = None) -> dict[str, Any]:
    value = dict(request or {})
    if scheduling_mode and not value.get("scheduling_mode"):
        value["scheduling_mode"] = scheduling_mode
    application = value.get("application")
    applications = value.get("applications")
    if isinstance(application, dict) and not isinstance(applications, dict):
        code = str(application.get("code") or application.get("name") or "legacy-application")
        names={str(node.get("app_image")) for node in (value.get("workflow") or {}).get("nodes",[]) if node.get("app_image")}
        value["applications"] = {name: application for name in names or {code}}
    participants = value.get("participants")
    if not isinstance(participants, list) or not participants:
        generated = []
        for role in ("provider", "consumer"):
            connector = value.get(f"{role}_connector_id")
            if connector:
                generated.append({
                    "connector_id": connector,
                    "execution_node_ref": value.get(f"{role}_execution_node_ref"),
                    "gateway_endpoint": value.get(f"{role}_gateway_endpoint"),
                    "connector_endpoint": value.get(f"{role}_connector_endpoint"),
                    "execution_storage_ref": value.get(f"{role}_execution_storage_ref"),
                    "business_role": role,
                })
        if generated:
            value["participants"] = generated
    # Legacy privacy requests use input_* names in the public API. Keep the
    # canonical resource aliases available to compilers and artifact cleanup.
    for role in ("provider", "consumer"):
        old = value.get(f"input_{role}_ref")
        if old and not value.get(f"{role}_resource_ref"):
            value[f"{role}_resource_ref"] = old
    return value


def materialize_execution_request(request: dict[str, Any], appimages: dict[str, Any], *, project_id: str, run_id: str) -> dict[str, Any]:
    """Use the project runtime compiler and lifecycle for legacy single apps."""
    from app.services.project import _runtime_workflow
    value=normalize_execution_request(request)
    from copy import deepcopy
    source=deepcopy(value.get('workflow') or {})
    for node in source.get('nodes',[]):
        for party in node.get('parties',[]):
            party.setdefault('domain_id',party.get('connector_id'))
        for binding in node.get('input_bindings',[]):
            binding.setdefault('domain_id',binding.get('connector_id'))
        ports={p['name']:p for p in (appimages[node['app_image']].io_schema or {}).get('outputs',[])}
        for binding in node.get('output_bindings',[]):
            if binding.get('domain_id'):continue
            role=ports.get(binding['port'],{}).get('role')
            owners={p['domain_id'] for p in node.get('parties',[]) if p.get('role')==role}
            if role in {'provider','consumer'}:owners={value.get(role+'_connector_id')}
            # Historical single-application API's result belongs to the
            # consumer when no output role was declared; retain that contract.
            if not role:owners={value.get('consumer_connector_id')}
            if len(owners)!=1 or not next(iter(owners)):
                raise ValueError('应用输出缺少唯一参与方归属')
            binding['domain_id']=next(iter(owners))
    workflow=_runtime_workflow(source,appimages,project_id,run_id)
    value.update(workflow=workflow,request_id=run_id)
    value['artifact_plan']=[{'connector_id':out['domain_id'],'node':node['id'],'port':out['port'],
        'relative_uri':out['relative_uri'],'retention':'result'}
        for node in workflow['nodes'] for out in node.get('output_bindings',[])]
    return value
