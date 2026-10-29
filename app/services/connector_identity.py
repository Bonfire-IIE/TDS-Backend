"""PKCS#10 校验与连接器机器身份证书签发。"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.core.config import settings


class IdentityError(ValueError):
    pass


def parse_csr(pem: str) -> tuple[x509.CertificateSigningRequest, str, str]:
    try:
        csr = x509.load_pem_x509_csr(pem.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise IdentityError("CSR 不是有效的 PEM PKCS#10 请求") from exc
    if not csr.is_signature_valid:
        raise IdentityError("CSR 签名无效，无法证明私钥持有权")
    key = csr.public_key()
    if isinstance(key, rsa.RSAPublicKey) and key.key_size < 2048:
        raise IdentityError("RSA 密钥长度不得小于 2048 位")
    if not isinstance(key, (rsa.RSAPublicKey, ec.EllipticCurvePublicKey)):
        raise IdentityError("CSR 仅支持 RSA 或 EC 公钥")
    csr_fp = hashlib.sha256(csr.public_bytes(serialization.Encoding.DER)).hexdigest()
    pub_der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return csr, csr_fp, hashlib.sha256(pub_der).hexdigest()


def _ca_files() -> tuple[Path, Path]:
    root = Path(settings.connector_ca_dir)
    return root / "ca-key.pem", root / "ca-cert.pem"


def _load_or_create_ca():
    key_path, cert_path = _ca_files()
    if key_path.exists() and cert_path.exists():
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        return key, x509.load_pem_x509_certificate(cert_path.read_bytes())
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    now = datetime.now(timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Bonfire Connector Root CA")])
    cert = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    os.chmod(key_path, 0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key, cert


def issue_certificate(csr: x509.CertificateSigningRequest, connector_id: str, tds_code: str, org_name: str | None):
    ca_key, ca_cert = _load_or_create_ca()
    now = datetime.now(timezone.utc)
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, connector_id), x509.NameAttribute(NameOID.SERIAL_NUMBER, tds_code)]
    if org_name:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, org_name[:64]))
    cert = (
        x509.CertificateBuilder().subject_name(x509.Name(attrs)).issuer_name(ca_cert.subject)
        .public_key(csr.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=settings.connector_certificate_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return (
        cert,
        cert.public_bytes(serialization.Encoding.PEM).decode("ascii"),
        ca_cert.public_bytes(serialization.Encoding.PEM).decode("ascii"),
        cert.fingerprint(hashes.SHA256()).hex(),
    )


def ca_certificate_pem() -> str:
    _, cert = _load_or_create_ca()
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def certificate_fingerprint(pem: str) -> str:
    return x509.load_pem_x509_certificate(pem.encode("ascii")).fingerprint(hashes.SHA256()).hex()
