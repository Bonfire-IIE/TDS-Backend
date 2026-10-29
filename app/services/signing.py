"""Small user-bound Ed25519 signing adapter for contract signatures."""
from __future__ import annotations
import base64, hashlib, json, os, secrets
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.signing import UserSigningKey

def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

def _root() -> Path:
    # User contract keys are platform credentials, unrelated to Kuscia.
    configured = getattr(settings, "signing_key_root", None)
    root = Path(configured or ".data/signing-keys") / "user-signing"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root

def ensure_key(db: Session, subject: str) -> UserSigningKey:
    row = db.scalar(select(UserSigningKey).where(UserSigningKey.subject == subject))
    if row: return row
    key = Ed25519PrivateKey.generate()
    key_id = secrets.token_hex(16)
    path = _root() / f"{key_id}.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    os.chmod(path, 0o600)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    row = UserSigningKey(subject=subject, key_id=key_id, public_key_pem=public.decode(), public_key_sha256=hashlib.sha256(public).hexdigest(), private_key_ref=str(path))
    db.add(row); db.flush(); return row

def sign(db: Session, subject: str, payload: object) -> dict:
    row = ensure_key(db, subject)
    key = serialization.load_pem_private_key(Path(row.private_key_ref).read_bytes(), password=None)
    signature = key.sign(canonical(payload))
    return {"algorithm": row.algorithm, "key_id": row.key_id, "subject": subject, "public_key_sha256": row.public_key_sha256, "signature": base64.b64encode(signature).decode()}

def verify(row: UserSigningKey, payload: object, signature: str) -> bool:
    try:
        public = serialization.load_pem_public_key(row.public_key_pem.encode())
        public.verify(base64.b64decode(signature), canonical(payload)); return True
    except Exception: return False
