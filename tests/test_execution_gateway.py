"""HTTP + ORM regression for execution snapshots and report ownership.

Identity claims are supplied by the dependency fixture. Real JWT verification is
covered by the isolated dispatch verification script, not claimed by this test.
"""
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.db import Base, get_db
from app.core.execution_auth import dispatch_authorized
from app.core.security import get_optional_current_user
from app.models import Connector, PrivacyComputeRun, ProjectRun
from app.routers.privacy_compute import router

SECRET = "test-execution-secret-" + "x" * 40
REQUEST = {"provider_connector_id": "a", "consumer_connector_id": "b", "dispatch_connector_id": "b",
           "provider_resource": {"version": "1"}, "application": {"implementation_ref": "psi"}}


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setattr(settings, "execution_auth_mode", "shared-secret")
    monkeypatch.setattr(settings, "execution_dispatch_secret", SECRET)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Connector.__table__, PrivacyComputeRun.__table__, ProjectRun.__table__])
    with Session(engine) as db:
        for name in ("a", "b", "other"):
            db.add(Connector(id=name, name=name, created_by="owner-" + name, status="active",
                             csr_pem="test", csr_fingerprint=name, public_key_fingerprint=name))
        db.add(PrivacyComputeRun(id="privacy", project_id="absent", created_by="owner-b", status="pending-dispatch",
                                 evidence={"execution_request": REQUEST}))
        db.add(ProjectRun(id="workflow", project_id="absent", workflow_version_id="v1", created_by="owner-b",
                          kuscia_job_id="exec-workflow", status="pending-dispatch",
                          job_snapshot={"execution_request": REQUEST}))
        db.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def database():
        with Session(engine) as db:
            yield db

    def user(authorization: str | None = Header(default=None)):
        if authorization is None:
            return None
        if not authorization.startswith("Bearer owner-") and authorization != "Bearer operator":
            raise HTTPException(401)
        return {"username": authorization.removeprefix("Bearer "), "roles": ["operator"] if authorization == "Bearer operator" else []}

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_optional_current_user] = user
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def url(run):
    return "/api/v1/privacy-computing/gateway/runs/" + run


@pytest.mark.parametrize("run", ["privacy", "workflow"])
def test_stored_snapshot_requires_owner_or_explicit_service_credential(gateway, run):
    client, _ = gateway
    for headers in ({}, {"X-Bonfire-Execution-Secret": ""}, {"X-Bonfire-Execution-Secret": "bonfire-dev-execution-dispatch"},
                    {"Authorization": "Bearer operator"}, {"Authorization": "Bearer owner-other"}):
        assert client.get(url(run), params={"connector_id": "a"}, headers=headers).status_code == 403
    for headers in ({"Authorization": "Bearer owner-a"}, {"X-Bonfire-Execution-Secret": SECRET}):
        response = client.get(url(run), params={"connector_id": "a"}, headers=headers)
        assert response.status_code == 200
        assert response.json()["data"]["execution_request"] == REQUEST
        assert response.json()["data"]["run_id"] == run
        assert "execution_snapshot" in response.json()["data"]
        assert "result_guidance" in response.json()["data"]
    assert client.get(url(run), params={"connector_id": "other"}, headers={"X-Bonfire-Execution-Secret": SECRET}).status_code == 403


@pytest.mark.parametrize("run", ["privacy", "workflow"])
def test_revoked_and_deleted_connectors_cannot_read_or_report(gateway, run):
    client, engine = gateway
    for change in ("revoked", "deleted"):
        with Session(engine) as db:
            connector = db.get(Connector, "b")
            connector.status = "revoked" if change == "revoked" else "active"
            connector.deleted_at = datetime.now(timezone.utc) if change == "deleted" else None
            db.commit()
        headers = {"X-Bonfire-Execution-Secret": SECRET}
        assert client.get(url(run), params={"connector_id": "b"}, headers=headers).status_code == 403
        assert client.post(url(run) + "/report", headers=headers, json={"connector_id": "b", "status": "running"}).status_code == 403


@pytest.mark.parametrize("run", ["privacy", "workflow"])
def test_participant_cannot_report_scheduler_result_or_regress_terminal_state(gateway, run):
    client, engine = gateway
    # No project row is needed: gateway report may reconcile an orphaned historical run.
    # These tables are queried by the route when updating project state.
    from app.models import Project, PrivacyComputeProject
    Base.metadata.create_all(engine, tables=[Project.__table__, PrivacyComputeProject.__table__])
    route = url(run) + "/report"
    headers = {"X-Bonfire-Execution-Secret": SECRET}
    assert client.post(route, headers={"Authorization": "Bearer owner-other"}, json={"connector_id": "b", "status": "running"}).status_code == 403
    assert client.post(route, headers=headers, json={"connector_id": "a", "status": "succeeded"}).status_code == 403
    assert client.post(route, headers=headers, json={"connector_id": "a", "status": "accepted", "result": {"uri": "forged"}}).status_code == 403
    assert client.post(route, headers=headers, json={"connector_id": "a", "status": "accepted"}).status_code == 200
    report = {"connector_id": "b", "status": "running", "external_run_ref": "actual-job"}
    assert client.post(route, headers=headers, json=report).status_code == 200
    assert client.post(route, headers=headers, json={**report, "external_run_ref": "another-job"}).status_code == 409
    assert client.post(route, headers=headers, json={"connector_id": "a", "status": "accepted"}).status_code == 409
    report["status"] = "succeeded"
    assert client.post(route, headers=headers, json=report).status_code == 200
    assert client.post(route, headers=headers, json=report).status_code == 200
    for status in ("running", "accepted", "cancelled", "failed"):
        assert client.post(route, headers=headers, json={**report, "status": status}).status_code == 409


def test_older_run_report_cannot_regress_project_status(gateway):
    from datetime import timedelta
    from app.models import PrivacyComputeProject

    client, engine = gateway
    Base.metadata.create_all(engine, tables=[PrivacyComputeProject.__table__])
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add(PrivacyComputeProject(
            id="project-1", name="Project", contract_id="contract-1", contract_version=1,
            contract_document_hash="a" * 64, application_code="generic", status="completed",
            created_by="owner-b",
        ))
        old = db.get(PrivacyComputeRun, "privacy")
        old.project_id = "project-1"
        old.created_at = now - timedelta(hours=1)
        db.add(PrivacyComputeRun(
            id="latest", project_id="project-1", created_by="owner-b", status="succeeded",
            evidence={"execution_request": REQUEST}, created_at=now,
        ))
        db.commit()

    response = client.post(
        url("privacy") + "/report",
        headers={"X-Bonfire-Execution-Secret": SECRET},
        json={"connector_id": "b", "status": "running", "external_run_ref": "old-job"},
    )
    assert response.status_code == 200
    with Session(engine) as db:
        assert db.get(PrivacyComputeProject, "project-1").status == "completed"


@pytest.mark.parametrize("secret", ["", " ", "short", "bonfire-dev-execution-dispatch"])
def test_unconfigured_or_legacy_channel_is_disabled(monkeypatch, secret):
    monkeypatch.setattr(settings, "execution_dispatch_secret", secret)
    assert not dispatch_authorized(secret)
    assert not dispatch_authorized(None)


@pytest.mark.parametrize("endpoint,body", [
    ("/api/v1/projects/unknown/runs", {}),
    ("/api/v1/privacy-computing/projects/unknown/runs",
     {"input_provider_ref": "source-a", "input_consumer_ref": "source-b", "join_keys": ["id"]}),
])
def test_start_without_channel_configuration_fails_before_creating_a_run(monkeypatch, endpoint, body):
    from app.core.security import get_current_user
    from app.routers.projects import router as project_router
    monkeypatch.setattr(settings, "execution_auth_mode", "shared-secret")
    monkeypatch.setattr(settings, "execution_dispatch_secret", "")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.include_router(project_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {"username": "owner-b", "roles": []}
    class UnusedDatabase:
        def __getattr__(self, _):
            raise AssertionError("must reject before reading or creating business data")
    app.dependency_overrides[get_db] = lambda: UnusedDatabase()
    with TestClient(app) as client:
        response = client.post(endpoint, json=body)
        assert response.status_code == 503
        assert "执行通道未配置" in response.json()["detail"]


@pytest.fixture(autouse=True)
def legacy_gateway_mode(monkeypatch):
    # These regression tests describe retained historical autonomy reports.
    monkeypatch.setattr(settings, 'pets_scheduler_mode', 'autonomy')

@pytest.mark.parametrize('run', ['privacy', 'workflow'])
def test_master_lite_rejects_edge_job_reports(gateway, monkeypatch, run):
    monkeypatch.setattr(settings, 'pets_scheduler_mode', 'master-lite')
    client, _ = gateway
    response = client.post(url(run)+'/report', headers={'X-Bonfire-Execution-Secret': SECRET},
                           json={'connector_id':'b','status':'succeeded','external_run_ref':'forged-job'})
    assert response.status_code == 409
