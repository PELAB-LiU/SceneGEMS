import pytest

from scenegems_tool.cluster.security.broker.broker_config import BROKER_CONFIG_MOUNT, ClusterBrokerSettings, render_broker_config

HOOK_SECRET = "test-hook-secret-0123456789abcdefghij"


@pytest.fixture
def config() -> str:
    return render_broker_config(ClusterBrokerSettings(auth_hook_url="http://master-api:8090/cluster/broker/auth", auth_hook_secret=HOOK_SECRET))


def test_only_tls_listens_on_all_interfaces(config):
    assert 'bind = "0.0.0.0:8883"' in config
    assert "listeners.tcp" not in config and "listeners.ws " not in config
    assert 'bind = "127.0.0.1:8086/mqtt"' in config


def test_anonymous_clients_and_unmatched_topics_are_refused(config):
    assert "allow_anonymous = false" in config
    assert "no_match = deny" in config
    assert f'acl = {{include "{BROKER_CONFIG_MOUNT}/nanomq_acl.conf"}}' in config


def test_logins_are_checked_by_the_master_hook_with_the_shared_secret(config):
    assert 'url = "http://master-api:8090/cluster/broker/auth"' in config
    assert f'headers.authorization = "Bearer {HOOK_SECRET}"' in config
    assert 'params = {clientid = "%c", username = "%u", password = "%P"}' in config


def test_tls_files_come_from_the_read_only_mount(config):
    for name in ["server_key.pem", "server_certificate.pem", "ca_certificate.pem"]:
        assert f'"{BROKER_CONFIG_MOUNT}/tls/{name}"' in config


@pytest.mark.parametrize("secret", ["short", 'has"quote-0123456789abcdefghijklmnop', "x" * 31])
def test_hook_secret_must_be_long_and_plain(secret):
    with pytest.raises(ValueError):
        ClusterBrokerSettings(auth_hook_url="http://master-api:8090/x", auth_hook_secret=secret)


@pytest.mark.parametrize("url", ["master-api:8090/x", 'http://master-api/"x', "ftp://master-api/x", "http://master api/x"])
def test_hook_url_must_be_a_plain_http_url(url):
    with pytest.raises(ValueError):
        ClusterBrokerSettings(auth_hook_url=url, auth_hook_secret=HOOK_SECRET)


def test_settings_repr_hides_the_secret():
    settings = ClusterBrokerSettings(auth_hook_url="http://master-api:8090/x", auth_hook_secret=HOOK_SECRET)
    assert HOOK_SECRET not in repr(settings)
