import datetime
import ipaddress
import socket
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID
from cryptography.x509.verification import PolicyBuilder, Store, VerificationError

from scenegems_tool.cluster.security.certificates.certificate_authority import SERVER_CERTIFICATE_VALIDITY, CertificateAuthority


@pytest.fixture(scope="module")
def authority() -> CertificateAuthority:
    return CertificateAuthority.create("lab-master")


@pytest.fixture(scope="module")
def issued(authority):
    return authority.issue_server_certificate("SceneGEMS master lab-master broker", ["192.168.1.10", "master.lan"])


def _verifier(authority, name, at=None):
    builder = PolicyBuilder().store(Store([authority.certificate]))
    if at is not None:
        builder = builder.time(at)
    return builder.build_server_verifier(name)


def test_ca_is_a_self_signed_ca_for_this_master(authority):
    certificate = authority.certificate
    assert certificate.issuer == certificate.subject
    assert "lab-master" in certificate.subject.rfc4514_string()
    constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints)
    assert constraints.critical and constraints.value.ca and constraints.value.path_length == 0
    assert certificate.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign


def test_server_certificate_lists_the_master_addresses_and_defaults(issued):
    names = issued.certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert ipaddress.ip_address("192.168.1.10") in names.get_values_for_type(x509.IPAddress)
    assert ipaddress.ip_address("127.0.0.1") in names.get_values_for_type(x509.IPAddress)
    assert {"master.lan", "localhost", "cluster-broker", "master-api"} <= set(names.get_values_for_type(x509.DNSName))


def test_server_certificate_is_for_servers_only(issued):
    certificate = issued.certificate
    assert not certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value == x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH])


@pytest.mark.parametrize("name", [x509.DNSName("master.lan"), x509.IPAddress(ipaddress.ip_address("192.168.1.10")), x509.DNSName("cluster-broker")])
def test_server_certificate_chains_to_the_ca_for_each_name(authority, issued, name):
    _verifier(authority, name).verify(issued.certificate, [])


def test_server_certificate_does_not_verify_for_an_unlisted_name(authority, issued):
    with pytest.raises(VerificationError):
        _verifier(authority, x509.DNSName("other.lan")).verify(issued.certificate, [])


def test_server_certificate_does_not_verify_under_another_ca(issued):
    stranger = CertificateAuthority.create("other-master")
    with pytest.raises(VerificationError):
        _verifier(stranger, x509.DNSName("master.lan")).verify(issued.certificate, [])


def test_server_certificate_expires(authority):
    now = datetime.datetime(2026, 10, 25, tzinfo=datetime.timezone.utc)
    issued = authority.issue_server_certificate("api", ["master.lan"], now=now)
    assert issued.certificate.not_valid_after_utc == now + SERVER_CERTIFICATE_VALIDITY
    with pytest.raises(VerificationError):
        _verifier(authority, x509.DNSName("master.lan"), at=now + SERVER_CERTIFICATE_VALIDITY + datetime.timedelta(days=1)).verify(issued.certificate, [])


def test_save_and_load_round_trip(tmp_path, authority):
    authority.save(tmp_path / "ca.pem", tmp_path / "ca_key.pem")
    loaded = CertificateAuthority.load(tmp_path / "ca.pem", tmp_path / "ca_key.pem")
    assert loaded.certificate == authority.certificate
    reissued = loaded.issue_server_certificate("api", ["master.lan"])
    _verifier(authority, x509.DNSName("master.lan")).verify(reissued.certificate, [])


def test_load_rejects_a_key_of_another_ca(tmp_path, authority):
    authority.save(tmp_path / "ca.pem", tmp_path / "ca_key.pem")
    CertificateAuthority.create("other-master").save(tmp_path / "other.pem", tmp_path / "other_key.pem")
    with pytest.raises(ValueError, match="does not belong"):
        CertificateAuthority.load(tmp_path / "ca.pem", tmp_path / "other_key.pem")


def _tls_handshake(tmp_path, authority, issued, server_hostname):
    (tmp_path / "server.pem").write_bytes(issued.certificate_pem)
    (tmp_path / "server_key.pem").write_bytes(issued.private_key_pem)
    (tmp_path / "ca.pem").write_bytes(authority.certificate_pem)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(tmp_path / "server.pem", tmp_path / "server_key.pem")
    client_context = ssl.create_default_context(cafile=str(tmp_path / "ca.pem"))
    # The strict X.509 checks Python 3.13 turns on by default, so newer clients accept it too.
    client_context.verify_flags |= ssl.VERIFY_X509_STRICT

    listener = socket.create_server(("127.0.0.1", 0))
    listener.settimeout(10)
    port = listener.getsockname()[1]

    def serve():
        try:
            connection, _ = listener.accept()
            with server_context.wrap_socket(connection, server_side=True) as tls:
                tls.recv(1)
        except (OSError, ssl.SSLError):
            pass

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=10) as raw:
            with client_context.wrap_socket(raw, server_hostname=server_hostname) as tls:
                tls.sendall(b"x")
                return tls.version()
    finally:
        server.join(timeout=10)
        listener.close()


def test_python_tls_client_accepts_the_certificate_by_ip_address(tmp_path, authority, issued):
    assert _tls_handshake(tmp_path, authority, issued, "127.0.0.1") in {"TLSv1.2", "TLSv1.3"}


def test_python_tls_client_rejects_an_unlisted_host_name(tmp_path, authority, issued):
    with pytest.raises(ssl.SSLCertVerificationError):
        _tls_handshake(tmp_path, authority, issued, "other.lan")
