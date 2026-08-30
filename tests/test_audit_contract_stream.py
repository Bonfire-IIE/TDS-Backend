from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent, AuditOutbox
from app.services.audit import append, contract_stream


def test_contract_related_events_share_one_hash_chain():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AuditEvent.__table__.create(engine)
    AuditOutbox.__table__.create(engine)

    with Session(engine) as db:
        stream = contract_stream("contract-1")
        contract = append(db, event_type="contract.filed", stream_id=stream, payload={"contract_id": "contract-1"})
        usage = append(db, event_type="usage.reserved", stream_id=stream, payload={"contract_id": "contract-1"})
        project = append(db, event_type="project.run.submitted", stream_id=stream, payload={"contract_id": "contract-1"})
        db.commit()

        events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.sequence)))
        assert [event.stream_id for event in events] == ["contract:contract-1"] * 3
        assert [event.sequence for event in events] == [1, 2, 3]
        assert contract.previous_hash == ""
        assert usage.previous_hash == contract.current_hash
        assert project.previous_hash == usage.current_hash


def test_contract_stream_rejects_empty_contract_id():
    try:
        contract_stream("")
    except ValueError as exc:
        assert "contract_id" in str(exc)
    else:
        raise AssertionError("empty contract id must be rejected")
