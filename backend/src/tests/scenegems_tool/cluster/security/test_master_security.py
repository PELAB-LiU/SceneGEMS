import ipaddress

import pytest
from cryptography import x509

from scenegems_tool.cluster.security.credentials.broker_accounts import verify_broker_login
from scenegems_tool.cluster.security.master_security import MasterSecurity
from tests.scenegems_tool.cluster.security.conftest import HOOK_SECRET, MASTER_PASSWORD, make_master_security


def _san(path):
    certificate = x509.load_pem_x509_certificate(path.read_bytes())
    return certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value


def test_init_creates_the_ca_certificates_broker_files_and_master_account(master_security):
    layout = master_security.layout
    for path in [
        layout.ca_certificate,
        layout.ca_key,
        layout.api_certificate,
        layout.api_key,
        layout.broker_config,
        layout.broker_access_rules,
        layout.broker_certificate,
        layout.broker_key,
        layout.broker_ca_certificate,
    ]:
        assert path.is_file(), path
    assert layout.broker_ca_certificate.read_bytes() == layout.ca_certificate.read_bytes()
    assert "scenegems/lab-master/${username}/#" in layout.broker_access_rules.read_text()
    assert HOOK_SECRET in layout.broker_config.read_text()
    assert verify_broker_login(master_security.store, "master", MASTER_PASSWORD)


def test_broker_folder_never_contains_the_ca_key(master_security):
    ca_key = master_security.layout.ca_key.read_bytes()
    for path in master_security.layout.broker_folder.rglob("*"):
        if path.is_file():
            assert path.read_bytes() != ca_key


def test_store_never_contains_the_master_password(master_security):
    for path in master_security.layout.store_folder.rglob("*.json"):
        assert MASTER_PASSWORD not in path.read_text()


def test_certificates_list_the_master_addresses(master_security):
    for path in [master_security.layout.api_certificate, master_security.layout.broker_certificate]:
        names = _san(path)
        assert ipaddress.ip_address("192.168.1.10") in names.get_values_for_type(x509.IPAddress)
        assert "master.lan" in names.get_values_for_type(x509.DNSName)


def test_init_again_keeps_the_ca_and_adds_new_addresses(tmp_path):
    first = make_master_security(tmp_path / "security")
    ca_before = first.layout.ca_certificate.read_bytes()
    second = make_master_security(tmp_path / "security", addresses=("192.168.1.10", "10.147.17.3"))
    assert second.layout.ca_certificate.read_bytes() == ca_before
    assert ipaddress.ip_address("10.147.17.3") in _san(second.layout.broker_certificate).get_values_for_type(x509.IPAddress)


def test_init_refuses_to_change_the_master_id(tmp_path, master_security):
    from scenegems_tool.cluster.security.broker.broker_config import ClusterBrokerSettings
    from scenegems_tool.cluster.security.master_security import initialize_master_security

    with pytest.raises(ValueError, match="belongs to master 'lab-master'"):
        initialize_master_security(
            master_security.layout.root,
            master_id="other-master",
            addresses=["192.168.1.10"],
            master_broker_username="master",
            master_broker_password=MASTER_PASSWORD,
            broker=ClusterBrokerSettings(auth_hook_url="http://master-api:8090/x", auth_hook_secret=HOOK_SECRET),
        )


def test_init_needs_an_address(tmp_path):
    with pytest.raises(ValueError, match="at least one master address"):
        make_master_security(tmp_path / "security", addresses=())


def test_load_reads_the_identity_back(master_security):
    loaded = MasterSecurity.load(master_security.layout.root)
    assert loaded.identity == master_security.identity
    assert loaded.identity.broker_public_host == "192.168.1.10"
    assert loaded.ca_certificate_pem.startswith("-----BEGIN CERTIFICATE-----")


def test_load_without_init_says_how_to_create_the_folder(tmp_path):
    with pytest.raises(FileNotFoundError, match="init"):
        MasterSecurity.load(tmp_path / "missing")
