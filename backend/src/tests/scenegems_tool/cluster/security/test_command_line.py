from datetime import timedelta

import pytest

from scenegems_tool.cluster.protocol.pairing import PairingRequest
from scenegems_tool.cluster.security.certificates.certificate_pinning import certificate_sha256
from scenegems_tool.cluster.security.command_line import load_env_file, main, master_url, parse_duration
from scenegems_tool.cluster.security.credentials.broker_accounts import verify_broker_login
from scenegems_tool.cluster.security.credentials.pairing_tokens import consume_pairing_token
from scenegems_tool.cluster.security.master_security import MasterSecurity
from scenegems_tool.cluster.security.pairing import pair_node
from tests.scenegems_tool.cluster.security.conftest import HOOK_SECRET, MASTER_PASSWORD, make_master_security


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / "master" / ".env"
    path.parent.mkdir()
    path.write_text(
        "\n".join(
            [
                "# a comment",
                "SCENEGEMS_MASTER_ID=lab-master",
                "SCENEGEMS_MASTER_ADDRESSES=192.168.1.10, master.lan",
                "SCENEGEMS_SECURITY_DIR=./security_data",
                f'SCENEGEMS_BROKER_MASTER_PASSWORD="{MASTER_PASSWORD}"',
                "SCENEGEMS_BROKER_AUTH_HOOK_URL=http://master-api:8090/cluster/broker/auth",
                f"SCENEGEMS_BROKER_AUTH_HOOK_SECRET={HOOK_SECRET}",
                "SCENEGEMS_BROKER_PUBLIC_HOST=",
            ]
        )
    )
    return path


def _run(env_file, *arguments):
    return main(["--env-file", str(env_file), *arguments], environ={})


def test_init_then_create_token_then_pair(env_file, capsys):
    assert _run(env_file, "init") == 0
    output = capsys.readouterr()
    assert MASTER_PASSWORD not in output.out + output.err and HOOK_SECRET not in output.out + output.err

    security_dir = env_file.parent / "security_data"
    security = MasterSecurity.load(security_dir)
    assert security.identity.addresses == ("192.168.1.10", "master.lan")
    assert verify_broker_login(security.store, "master", MASTER_PASSWORD)

    assert _run(env_file, "pairing-token", "create", "--lifetime", "10m", "--note", "lab-1") == 0
    output = capsys.readouterr()
    node_env = dict(line.split("=", 1) for line in output.out.splitlines())
    assert list(node_env) == ["SCENEGEMS_MASTER_ID", "SCENEGEMS_MASTER_URL", "SCENEGEMS_PAIRING_TOKEN", "SCENEGEMS_MASTER_CA_SHA256"]
    assert node_env["SCENEGEMS_MASTER_ID"] == "lab-master"
    token = node_env["SCENEGEMS_PAIRING_TOKEN"]
    assert len(token) >= 43 and "valid once until" in output.err and token not in output.err
    assert node_env["SCENEGEMS_MASTER_URL"] == "https://192.168.1.10:8443"
    assert node_env["SCENEGEMS_MASTER_CA_SHA256"] == certificate_sha256(security.ca_certificate_pem)
    response = pair_node(security, PairingRequest(token=token, node_name="lab 1"))

    assert _run(env_file, "node", "revoke", response.node_id) == 0
    assert not verify_broker_login(security.store, response.node_id, response.broker.password)
    assert _run(env_file, "node", "revoke", response.node_id) == 1


def test_missing_settings_are_reported_without_a_traceback(tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("SCENEGEMS_MASTER_ID=lab-master\nSCENEGEMS_SECURITY_DIR=sec\n")
    assert _run(env_file, "init") == 2
    assert "SCENEGEMS_BROKER_MASTER_PASSWORD is not set" in capsys.readouterr().err


def test_pairing_token_before_init_is_reported(env_file, capsys):
    assert _run(env_file, "pairing-token", "create") == 2
    assert "init" in capsys.readouterr().err


def test_purge_counts_expired_tokens(env_file, capsys):
    _run(env_file, "init")
    capsys.readouterr()
    assert _run(env_file, "pairing-token", "purge") == 0
    assert "Removed 0" in capsys.readouterr().out


def test_environment_wins_over_the_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("A=from-file\nB='quoted value'\nnot a setting\n")
    environ = {"A": "from-environment"}
    load_env_file(env_file, environ)
    assert environ == {"A": "from-environment", "B": "quoted value"}


@pytest.mark.parametrize("text,expected", [("30m", timedelta(minutes=30)), ("2h", timedelta(hours=2)), ("1d", timedelta(days=1)), ("90s", timedelta(seconds=90))])
def test_parse_duration(text, expected):
    assert parse_duration(text) == expected


def test_token_from_the_command_line_is_one_time(env_file, capsys):
    _run(env_file, "init")
    capsys.readouterr()
    _run(env_file, "pairing-token", "create", "--token-only")
    token = capsys.readouterr().out.strip()
    assert len(token.splitlines()) == 1 and len(token) >= 43
    security = MasterSecurity.load(env_file.parent / "security_data")
    consume_pairing_token(security.store, token)
    with pytest.raises(ValueError):
        consume_pairing_token(security.store, token)


@pytest.mark.parametrize(
    "environ, expected",
    [
        ({}, "https://192.168.1.10:8443"),
        ({"SCENEGEMS_API_PORT": "9443"}, "https://192.168.1.10:9443"),
        ({"SCENEGEMS_MASTER_URL": "https://master.lan:8443/"}, "https://master.lan:8443"),
    ],
)
def test_master_url(master_security, environ, expected):
    assert master_url(master_security, environ) == expected


def test_master_url_of_an_ipv6_address(tmp_path):
    assert master_url(make_master_security(tmp_path / "v6", addresses=("fd00::10",)), {}) == "https://[fd00::10]:8443"
