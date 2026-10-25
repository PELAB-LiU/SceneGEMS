import hashlib
import ssl

import pytest

from scenegems_tool.cluster.security.certificates.certificate_pinning import certificate_sha256, matches_pinned_sha256, normalize_sha256
from tests.scenegems_tool.cluster.security.conftest import make_master_security


def test_the_hash_is_of_the_der_bytes_in_lowercase_hex(master_security):
    pem = master_security.ca_certificate_pem
    expected = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
    assert certificate_sha256(pem) == expected == expected.lower() and len(expected) == 64
    assert certificate_sha256(pem.encode("ascii")) == expected


def test_the_hash_ignores_pem_line_endings_and_surrounding_space(master_security):
    pem = master_security.ca_certificate_pem
    assert certificate_sha256("\n  " + pem.replace("\n", "\r\n") + "\n\n") == certificate_sha256(pem)


def test_pinned_values_as_openssl_prints_them_are_accepted(master_security):
    digest = certificate_sha256(master_security.ca_certificate_pem)
    openssl_style = ":".join(digest[index : index + 2] for index in range(0, 64, 2)).upper()
    assert normalize_sha256(openssl_style) == digest
    assert matches_pinned_sha256(master_security.ca_certificate_pem, openssl_style)


def test_another_certificate_or_a_malformed_pin_does_not_match(master_security, tmp_path):
    other = make_master_security(tmp_path / "other").ca_certificate_pem
    assert not matches_pinned_sha256(other, certificate_sha256(master_security.ca_certificate_pem))
    assert not matches_pinned_sha256(master_security.ca_certificate_pem, "")
    assert not matches_pinned_sha256(master_security.ca_certificate_pem, certificate_sha256(master_security.ca_certificate_pem)[:-1])


def test_not_a_certificate():
    with pytest.raises(ValueError):
        certificate_sha256("not a certificate")
