from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models.audit import AuditEvent
from app.models.project import Project
from app.routers.audit import list_events


def add_event(db: Session, event_id: str, event_type: str, stream: str, sequence: int, **payload):
    now = datetime.now(timezone.utc)
    db.add(AuditEvent(
        id=event_id, event_id=event_id, event_type=event_type,
        stream_id=stream, sequence=sequence, actor=None,
        resource_type=None, resource_id=None,
        payload={"payload": payload}, payload_hash="a" * 64,
        previous_hash="", current_hash="b" * 64,
        occurred_at=now, created_at=now,
    ))


def test_project_lookup_returns_complete_contract_chain():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Project(
            id="project-1", name="p", contract_id="contract-1",
            initiator_connector_id="connector-1", status="draft", created_by="alice",
        ))
        add_event(db, "event-1", "contract.filed", "contract:contract-1", 1, contract_id="contract-1")
        add_event(db, "event-2", "usage.decision.denied", "contract:contract-1", 2, contract_id="contract-1")
        add_event(db, "event-3", "contract.filed", "contract:contract-2", 1, contract_id="contract-2")
        db.commit()

        chain = list_events(contract_id=None, project_id="project-1", user={"username": "alice"}, db=db)
        assert {item["event_id"] for item in chain["data"]} == {"event-1", "event-2"}
