from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services.connector_identity import parse_csr


def _csr() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "test-connector")])
    csr = x509.CertificateSigningRequestBuilder().subject_name(name).sign(key, hashes.SHA256())
    return csr.public_bytes(serialization.Encoding.PEM).decode()


def test_parse_csr_proves_private_key_and_returns_stable_fingerprints():
    csr, csr_fp, public_fp = parse_csr(_csr())
    assert csr.subject.rfc4514_string() == "CN=test-connector"
    assert len(csr_fp) == 64
    assert len(public_fp) == 64


def test_parse_csr_rejects_invalid_request():
    import pytest
    from app.services.connector_identity import IdentityError

    with pytest.raises(IdentityError):
        parse_csr("-----BEGIN CERTIFICATE REQUEST-----\ninvalid\n-----END CERTIFICATE REQUEST-----")
