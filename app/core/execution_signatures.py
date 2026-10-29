"""HTTP execution signatures bound to registered connector keys and exact bytes."""
import base64
import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.models.connector import Connector
from app.models.execution_auth import ExecutionRequestNonce
from app.services.connector_identity import _ca_files

PREFIX = "bonfire-execution-v1"
CENTER = "@center"
WINDOW = 60


def message(signer, recipient, timestamp, nonce, method, target, body):
    return "\n".join([PREFIX, signer, recipient, timestamp, nonce, method.upper(),
                      target, hashlib.sha256(body).hexdigest()]).encode("utf-8")


def sign_headers(key, signer, recipient, method, target, body, *, timestamp=None, nonce=None):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    nonce = nonce or secrets.token_hex(24)
    payload = message(signer, recipient, timestamp, nonce, method, target, body)
    if isinstance(key, rsa.RSAPrivateKey):
        signature = key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
    elif isinstance(key, ec.EllipticCurvePrivateKey):
        signature = key.sign(payload, ec.ECDSA(hashes.SHA256()))
    else:
        raise ValueError("unsupported execution signing key")
    return {"X-Bonfire-Signer": signer, "X-Bonfire-Recipient": recipient,
            "X-Bonfire-Timestamp": timestamp, "X-Bonfire-Nonce": nonce,
            "X-Bonfire-Signature": base64.b64encode(signature).decode("ascii")}


def center_dispatch_request(url, recipient, body):
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if settings.execution_auth_mode == "shared-secret":
        headers = {"X-Bonfire-Execution-Secret": settings.execution_dispatch_secret}
    else:
        key_file, _ = _ca_files()
        key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
        parsed = urlsplit(url)
        target = parsed.path + (("?" + parsed.query) if parsed.query else "")
        headers = sign_headers(key, CENTER, recipient, "POST", target, raw)
    return raw, {"Content-Type": "application/json", **headers}


def active_certificate(connector: Connector | None):
    if not connector or connector.deleted_at is not None or connector.status != "active" or not connector.certificate_pem:
        raise HTTPException(403, "连接器机器身份不可用或已撤销")
    try:
        cert = x509.load_pem_x509_certificate(connector.certificate_pem.encode("ascii"))
        now = datetime.now(timezone.utc)
        # cryptography < 42 exposes naive validity timestamps, while newer
        # releases add timezone-aware `_utc` properties. Normalize both.
        not_before = getattr(cert, "not_valid_before_utc", None)
        not_after = getattr(cert, "not_valid_after_utc", None)
        if not_before is None:
            not_before = cert.not_valid_before.replace(tzinfo=timezone.utc)
        if not_after is None:
            not_after = cert.not_valid_after.replace(tzinfo=timezone.utc)
        if not not_before <= now < not_after:
            raise ValueError("expired certificate")
        der = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        if hashlib.sha256(der).hexdigest() != connector.public_key_fingerprint:
            raise ValueError("certificate key changed")
        if format(cert.serial_number, "x") != connector.certificate_serial:
            raise ValueError("certificate serial changed")
        return cert
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(403, "连接器机器证书无效或已过期") from exc


async def execution_signer(request: Request, db: Session = Depends(get_db)) -> str | None:
    # A supplied invalid signature must never fall back to browser or legacy auth.
    headers = request.headers
    if not any(name in headers for name in ("x-bonfire-signer", "x-bonfire-signature")):
        return None
    if settings.execution_auth_mode != "signature":
        raise HTTPException(401, "当前执行通道未启用签名认证")
    signer = headers.get("x-bonfire-signer", "")
    recipient = headers.get("x-bonfire-recipient", "")
    timestamp = headers.get("x-bonfire-timestamp", "")
    nonce = headers.get("x-bonfire-nonce", "")
    signature = headers.get("x-bonfire-signature", "")
    if (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", signer) or recipient != CENTER
            or not re.fullmatch(r"[0-9]{10}", timestamp) or abs(time.time() - int(timestamp)) > WINDOW
            or not re.fullmatch(r"[a-f0-9]{48}", nonce) or len(signature) > 2048):
        raise HTTPException(401, "执行签名上下文无效或已过期")
    cert = active_certificate(db.get(Connector, signer))
    target = request.scope["raw_path"].decode("ascii")
    if request.scope["query_string"]:
        target += "?" + request.scope["query_string"].decode("ascii")
    payload = message(signer, recipient, timestamp, nonce, request.method, target, await request.body())
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
        key = cert.public_key()
        if isinstance(key, rsa.RSAPublicKey):
            key.verify(signature_bytes, payload, padding.PKCS1v15(), hashes.SHA256())
        elif isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(signature_bytes, payload, ec.ECDSA(hashes.SHA256()))
        else:
            raise ValueError("unsupported key")
    except (InvalidSignature, ValueError) as exc:
        raise HTTPException(401, "执行请求签名无效") from exc
    nonce_id = hashlib.sha256((signer + "\n" + nonce).encode()).hexdigest()
    db.execute(delete(ExecutionRequestNonce).where(ExecutionRequestNonce.expires_at < int(time.time())))
    db.add(ExecutionRequestNonce(id=nonce_id, expires_at=int(timestamp) + WINDOW + 1))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "执行签名已使用，请重新签名后重试") from exc
    return signer
