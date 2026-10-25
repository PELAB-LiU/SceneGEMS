from pathlib import Path

import pytest

from scenegems_tool.cluster.master.settings import Listener, MasterSettings, SettingMissing

REQUIRED = {
    "SCENEGEMS_SECURITY_DIR": "/etc/scenegems/security",
    "SCENEGEMS_DATABASE_URL": "postgresql+psycopg://scenegems:secret@postgres:5432/scenegems",
    "SCENEGEMS_BROKER_AUTH_HOOK_SECRET": "hook-secret-0123456789abcdefghijklmnop",
}


def test_defaults():
    settings = MasterSettings.from_environment(REQUIRED)
    assert settings.security_dir == Path("/etc/scenegems/security")
    assert (settings.node_api, settings.operator, settings.broker_hook) == (Listener("0.0.0.0", 8443), Listener("127.0.0.1", 5174), Listener("127.0.0.1", 8090))
    assert settings.fingerprint_repo_root is None


def test_overrides():
    environ = dict(
        REQUIRED,
        SCENEGEMS_API_LISTEN_PORT="9443",
        SCENEGEMS_OPERATOR_LISTEN_HOST="0.0.0.0",
        SCENEGEMS_BROKER_HOOK_LISTEN_HOST="0.0.0.0",
        SCENEGEMS_BROKER_HOOK_LISTEN_PORT="8091",
        SCENEGEMS_FINGERPRINT_REPO_ROOT="/repo",
    )
    settings = MasterSettings.from_environment(environ)
    assert settings.node_api == Listener("0.0.0.0", 9443) and settings.operator == Listener("0.0.0.0", 5174) and settings.broker_hook == Listener("0.0.0.0", 8091)
    assert settings.fingerprint_repo_root == Path("/repo")


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
