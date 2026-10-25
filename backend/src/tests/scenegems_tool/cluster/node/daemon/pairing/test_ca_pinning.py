import hashlib
import ssl

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from scenegems_tool.cluster.node.daemon.pairing.ca_pinning import CaPinMismatch, certificate_sha256, ensure_pinned, fetch_ca_certificate, pinned_ca_certificate, single_certificate, verified_context
from scenegems_tool.cluster.security.certificates.certificate_authority import CertificateAuthority


@pytest.fixture(scope="module")
def ca_pem() -> str:
    return CertificateAuthority.create("pin-test").certificate_pem.decode("ascii")


def test_the_hash_is_sha256_of_the_der_bytes_in_lowercase_hex(ca_pem):
    der = x509.load_pem_x509_certificate(ca_pem.encode()).public_bytes(serialization.Encoding.DER)
    assert certificate_sha256(ca_pem) == hashlib.sha256(der).hexdigest()
    assert certificate_sha256(ca_pem.replace("\n", "\r\n")) == certificate_sha256(ca_pem)  # line endings do not matter


def test_a_pem_text_must_hold_exactly_one_certificate(ca_pem):
    assert single_certificate("noise\n" + ca_pem + "trailer").startswith("-----BEGIN CERTIFICATE-----")
    with pytest.raises(CaPinMismatch, match="found 2"):
        single_certificate(ca_pem + ca_pem)
    with pytest.raises(CaPinMismatch, match="found 0"):
        single_certificate("not a certificate")


def test_a_different_certificate_is_refused(ca_pem):
    other = CertificateAuthority.create("other").certificate_pem.decode("ascii")
    ensure_pinned(ca_pem, certificate_sha256(ca_pem))
    with pytest.raises(CaPinMismatch, match="Refusing to pair"):
        ensure_pinned(other, certificate_sha256(ca_pem))


def test_the_verified_context_trusts_only_the_ca_and_checks_host_names(ca_pem):
    context = verified_context(ca_pem)
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert [entry["subject"] for entry in context.get_ca_certs()] == [((("organizationName", "SceneGEMS"),), (("commonName", "SceneGEMS master pin-test CA"),))]


def test_fetch_and_pin_against_the_fake_master(fake_master):
    served = fetch_ca_certificate(fake_master.url)
    assert single_certificate(served) == single_certificate(fake_master.security.ca_certificate_pem)
    expected = certificate_sha256(fake_master.security.ca_certificate_pem)
    assert certificate_sha256(pinned_ca_certificate(fake_master.url, expected)) == expected
    with pytest.raises(CaPinMismatch):
        pinned_ca_certificate(fake_master.url, "0" * 64)
