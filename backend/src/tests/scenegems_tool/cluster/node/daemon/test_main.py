"""Exit codes of the node container's entry point."""

import pytest

from scenegems_tool.cluster.node.daemon import __main__ as entry_point
from scenegems_tool.cluster.node.daemon.node_daemon import DaemonStopped
from scenegems_tool.cluster.protocol.version import ProtocolVersionMismatch
from tests.scenegems_tool.cluster.node.daemon.configuration.test_node_configuration import VALID


@pytest.fixture
def environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no ./.env
    for key in VALID:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("SCENEGEMS_ENV_FILE", raising=False)
    monkeypatch.setattr(entry_point.signal, "signal", lambda *_: None)


def test_an_invalid_configuration_exits_with_2(environment, caplog):
    assert entry_point.main() == 2
    assert "SCENEGEMS_MASTER_URL is not set" in caplog.text


@pytest.mark.parametrize("error, code", [(DaemonStopped("another master"), 4), (ProtocolVersionMismatch(2), 4), (None, 0)])
def test_daemon_outcomes_map_to_exit_codes(environment, monkeypatch, error, code, caplog):
    for key, value in VALID.items():
        monkeypatch.setenv(key, value)

    class Daemon:
        def __init__(self, configuration):
            assert configuration.node_name == "worker-1"

        def run(self, stop):
            if error is not None:
                raise error

    monkeypatch.setattr(entry_point, "NodeDaemon", Daemon)
    assert entry_point.main() == code
    if error is not None:
        assert str(error) in caplog.text
