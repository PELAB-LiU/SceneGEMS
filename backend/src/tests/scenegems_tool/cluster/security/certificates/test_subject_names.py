import ipaddress

import pytest
from cryptography import x509

from scenegems_tool.cluster.security.certificates.subject_names import DEFAULT_SUBJECT_NAMES, split_address_list, subject_alternative_name, subject_alternative_names


def test_ip_addresses_become_ip_entries():
    assert subject_alternative_name("10.147.17.3") == x509.IPAddress(ipaddress.ip_address("10.147.17.3"))
    assert subject_alternative_name("fd00::1") == x509.IPAddress(ipaddress.ip_address("fd00::1"))


def test_host_names_become_dns_entries_in_lowercase():
    assert subject_alternative_name(" Master.LAN ") == x509.DNSName("master.lan")


@pytest.mark.parametrize("value", ["", "  ", "two words", "http://master/x"])
def test_malformed_names_are_rejected(value):
    with pytest.raises(ValueError):
        subject_alternative_name(value)


def test_defaults_come_first_and_duplicates_are_dropped():
    names = subject_alternative_names(["127.0.0.1", "192.168.1.10", "192.168.1.10"])
    assert len(names) == len(DEFAULT_SUBJECT_NAMES) + 1
    assert names[-1] == x509.IPAddress(ipaddress.ip_address("192.168.1.10"))
    assert x509.DNSName("cluster-broker") in names


def test_split_address_list_accepts_commas_and_spaces():
    assert split_address_list("192.168.1.10, master.lan  10.0.0.2,") == ["192.168.1.10", "master.lan", "10.0.0.2"]
