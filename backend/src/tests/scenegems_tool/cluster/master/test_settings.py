from pathlib import Path

import pytest

from scenegems_tool.cluster.master.settings import DEFAULT_OPERATOR_ALLOWED_ORIGINS, ArtifactSettings, BrokerClientSettings, Listener, MasterSettings, SettingMissing, parse_allowed_origins

REQUIRED = {
    "SCENEGEMS_SECURITY_DIR": "/etc/scenegems/security",
    "SCENEGEMS_DATABASE_URL": "postgresql+psycopg://scenegems:secret@postgres:5432/scenegems",
    "SCENEGEMS_BROKER_AUTH_HOOK_SECRET": "hook-secret-0123456789abcdefghijklmnop",
}


def test_defaults():
    settings = MasterSettings.from_environment(REQUIRED)
    assert settings.security_dir == Path("/etc/scenegems/security")
    assert (settings.node_api, settings.operator, settings.broker_hook) == (Listener("0.0.0.0", 8443), Listener("127.0.0.1", 5174), Listener("127.0.0.1", 8090))
    assert settings.release_manifest is None
    assert settings.artifacts == ArtifactSettings(Path("/var/lib/scenegems/artifacts"), 256 * 1024 * 1024, 600.0, 3600.0)
    assert settings.broker is None


def test_the_operator_allows_the_ui_dev_server_by_default():
    assert MasterSettings.from_environment(REQUIRED).operator_allowed_origins == ("http://localhost:5173", "http://127.0.0.1:5173") == DEFAULT_OPERATOR_ALLOWED_ORIGINS
    assert MasterSettings.from_environment(dict(REQUIRED, SCENEGEMS_OPERATOR_ALLOWED_ORIGINS="  ")).operator_allowed_origins == DEFAULT_OPERATOR_ALLOWED_ORIGINS


def test_the_allowed_origins_are_a_comma_separated_list():
    environ = dict(REQUIRED, SCENEGEMS_OPERATOR_ALLOWED_ORIGINS="https://ui.lab.example, http://10.88.0.9:8080/ ,,https://ui.lab.example")
    assert MasterSettings.from_environment(environ).operator_allowed_origins == ("https://ui.lab.example", "http://10.88.0.9:8080")
    assert parse_allowed_origins("") == DEFAULT_OPERATOR_ALLOWED_ORIGINS
    assert parse_allowed_origins("http://a, http://b") == ("http://a", "http://b")


def test_artifact_settings():
    environ = dict(REQUIRED, SCENEGEMS_ARTIFACT_DIR="/data/artifacts", SCENEGEMS_ARTIFACT_MAX_BYTES="1048576", SCENEGEMS_ARTIFACT_SWEEP_INTERVAL_S="0", SCENEGEMS_ARTIFACT_SWEEP_GRACE_S="60")
    assert MasterSettings.from_environment(environ).artifacts == ArtifactSettings(Path("/data/artifacts"), 1048576, 0.0, 60.0)
    for name, value in (("SCENEGEMS_ARTIFACT_MAX_BYTES", "lots"), ("SCENEGEMS_ARTIFACT_MAX_BYTES", "0"), ("SCENEGEMS_ARTIFACT_SWEEP_GRACE_S", "-1")):
        with pytest.raises(ValueError):
            MasterSettings.from_environment(dict(REQUIRED, **{name: value}))


def test_overrides():
    environ = dict(
        REQUIRED,
        SCENEGEMS_API_LISTEN_PORT="9443",
        SCENEGEMS_OPERATOR_LISTEN_HOST="0.0.0.0",
        SCENEGEMS_BROKER_HOOK_LISTEN_HOST="0.0.0.0",
        SCENEGEMS_BROKER_HOOK_LISTEN_PORT="8091",
        SCENEGEMS_RELEASE_MANIFEST="/etc/scenegems/release.json",
    )
    settings = MasterSettings.from_environment(environ)
    assert settings.node_api == Listener("0.0.0.0", 9443) and settings.operator == Listener("0.0.0.0", 5174) and settings.broker_hook == Listener("0.0.0.0", 8091)
    assert settings.release_manifest == Path("/etc/scenegems/release.json")


@pytest.mark.parametrize("missing", sorted(REQUIRED))
def test_required_settings(missing):
    environ = {key: value for key, value in REQUIRED.items() if key != missing}
    with pytest.raises(SettingMissing, match=missing):
        MasterSettings.from_environment(environ)


def test_a_relative_security_folder_is_relative_to_the_env_file(tmp_path):
    settings = MasterSettings.from_environment(dict(REQUIRED, SCENEGEMS_SECURITY_DIR="./security_data"), env_file_folder=tmp_path)
    assert settings.security_dir == tmp_path / "security_data"


def test_secrets_stay_out_of_the_repr():
    text = repr(MasterSettings.from_environment(REQUIRED))
    assert REQUIRED["SCENEGEMS_DATABASE_URL"] not in text and REQUIRED["SCENEGEMS_BROKER_AUTH_HOOK_SECRET"] not in text


def test_the_broker_login_needs_a_host_and_the_masters_password():
    assert MasterSettings.from_environment(dict(REQUIRED, SCENEGEMS_BROKER_HOST="cluster-broker")).broker is None
    assert MasterSettings.from_environment(dict(REQUIRED, SCENEGEMS_BROKER_MASTER_PASSWORD="broker-secret-0123456789")).broker is None
    environ = dict(REQUIRED, SCENEGEMS_BROKER_HOST="cluster-broker", SCENEGEMS_BROKER_MASTER_PASSWORD="broker-secret-0123456789")
    assert MasterSettings.from_environment(environ).broker == BrokerClientSettings("cluster-broker", 8883, "", "broker-secret-0123456789")
    environ.update(SCENEGEMS_BROKER_PORT="18883", SCENEGEMS_BROKER_MASTER_USERNAME="observer")
    settings = MasterSettings.from_environment(environ)
    assert (settings.broker.port, settings.broker.username) == (18883, "observer")
    assert "broker-secret" not in repr(settings)
    with pytest.raises(ValueError, match="SCENEGEMS_BROKER_PORT"):
        MasterSettings.from_environment(dict(environ, SCENEGEMS_BROKER_PORT="tls"))
