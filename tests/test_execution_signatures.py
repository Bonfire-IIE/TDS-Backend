import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.execution_signatures import sign_headers
from app.models import Connector, ExecutionRequestNonce
from app.core.db import Base
from test_execution_gateway import gateway, url


@pytest.fixture
def signed_gateway(gateway, monkeypatch):
    client, engine = gateway
    monkeypatch.setattr(settings, "execution_auth_mode", "signature")
    Base.metadata.create_all(engine, tables=[ExecutionRequestNonce.__table__])
    keys = {}
    with Session(engine) as db:
        for party in ("a", "b", "other"):
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, party)])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                    .not_valid_after(now + timedelta(hours=1)).sign(key, hashes.SHA256()))
            row = db.get(Connector, party)
            row.certificate_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
            row.public_key_fingerprint = hashlib.sha256(key.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
            row.certificate_serial = format(cert.serial_number, "x")
            keys[party] = key
        db.commit()
    return client, engine, keys


def signed(keys, sender, method, target, body=b"", **options):
    return sign_headers(keys[sender], sender, "@center", method, target, body, **options)


def test_machine_signature_is_bound_to_connector_and_replay_is_persistent(signed_gateway):
    client, engine, keys = signed_gateway
    target = url("workflow") + "?connector_id=b"
    headers = signed(keys, "b", "GET", target)
    assert client.get(target, headers=headers).status_code == 200
    assert client.get(target, headers=headers).status_code == 409
    assert client.get(target, headers=signed(keys, "a", "GET", target)).status_code == 403
    wrong = signed(keys, "a", "GET", target); wrong["X-Bonfire-Signer"] = "b"
    assert client.get(target, headers=wrong).status_code == 401
    assert client.get(target, headers={"X-Bonfire-Execution-Secret": settings.execution_dispatch_secret}).status_code == 403
    with Session(engine) as db:
        db.get(Connector, "b").status = "revoked"; db.commit()
    assert client.get(target, headers=signed(keys, "b", "GET", target)).status_code == 403


def test_machine_signature_rejects_modified_query_body_and_expiry(signed_gateway):
    client, _, keys = signed_gateway
    target = url("privacy") + "?connector_id=b"
    assert client.get(target + "&extra=1", headers=signed(keys, "b", "GET", target)).status_code == 401
    assert client.get(target, headers=signed(keys, "b", "GET", target, timestamp=int(time.time()) - 61)).status_code == 401
    route = url("privacy") + "/report"
    body = json.dumps({"connector_id": "b", "status": "running"}).encode()
    headers = {"Content-Type": "application/json", **signed(keys, "b", "POST", route, body)}
    assert client.post(route, headers=headers, content=body + b" ").status_code == 401
    assert client.get(target, headers=signed(keys, "b", "POST", target)).status_code == 401


def test_peer_certificate_is_visible_only_to_run_participants_and_rotation_revokes_old_keys(signed_gateway):
    client, engine, keys = signed_gateway
    route = url("workflow") + "/identity?connector_id=b&peer_connector_id=a"
    assert client.get(route, headers=signed(keys, "b", "GET", route)).status_code == 200
    assert client.get(route, headers=signed(keys, "other", "GET", route)).status_code == 403
    target = url("workflow") + "?connector_id=b"
    with Session(engine) as db:
        row = db.get(Connector, "b")
        row.certificate_pem = db.get(Connector, "a").certificate_pem
        # Keep the registered fingerprint: an inconsistent rotation fails closed.
        db.commit()
    assert client.get(target, headers=signed(keys, "b", "GET", target)).status_code == 403
