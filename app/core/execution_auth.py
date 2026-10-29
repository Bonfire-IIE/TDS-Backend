"""Explicitly provisioned internal channel; no development password fallback."""
import secrets
from pathlib import Path

from app.core.config import settings


def dispatch_configured() -> bool:
    if settings.execution_auth_mode == "signature":
        root = Path(settings.connector_ca_dir)
        return (root / "ca-key.pem").is_file() and (root / "ca-cert.pem").is_file()
    value = settings.execution_dispatch_secret
    return settings.execution_auth_mode == "shared-secret" and len(value.strip()) >= 32 and value != "bonfire-dev-execution-dispatch"


def dispatch_authorized(value: str | None) -> bool:
    return bool(settings.execution_auth_mode == "shared-secret" and dispatch_configured() and value and secrets.compare_digest(
        value.encode("utf-8"), settings.execution_dispatch_secret.encode("utf-8")
    ))
