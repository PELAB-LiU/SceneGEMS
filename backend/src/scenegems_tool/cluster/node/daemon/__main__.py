"""`python -m scenegems_tool.cluster.node.daemon`: the node container's entry point.

Exit codes: 0 after SIGTERM or SIGINT, 2 for an invalid configuration, 3 when pairing is
refused or the stored pairing does not fit, 4 when the master refuses the node or cannot
talk to it. Every failure ends with one line that says what to change.
"""

import logging
import signal
import sys
import threading

from scenegems_tool.cluster.node.daemon.configuration.node_configuration import ConfigurationError, NodeConfiguration
from scenegems_tool.cluster.node.daemon.node_daemon import DaemonStopped, NodeDaemon
from scenegems_tool.cluster.node.daemon.pairing.ca_pinning import CaPinMismatch
from scenegems_tool.cluster.node.daemon.pairing.node_pairing import NotPaired
from scenegems_tool.cluster.node.daemon.pairing.pairing_client import PairingRefused
from scenegems_tool.cluster.node.daemon.pairing.pairing_state import PairingStateError
from scenegems_tool.cluster.protocol.version import ProtocolVersionMismatch

_logger = logging.getLogger("scenegems_tool.cluster.node.daemon")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    try:
        configuration = NodeConfiguration.load()
    except ConfigurationError as error:
        _logger.error("%s", error)
        return 2

    stop = threading.Event()

    def request_stop(signal_number, _frame) -> None:
        _logger.info("Signal %d: stopping", signal_number)
        stop.set()

    for signal_name in ("SIGTERM", "SIGINT"):
        signal.signal(getattr(signal, signal_name), request_stop)

    try:
        NodeDaemon(configuration).run(stop)
    except (NotPaired, PairingRefused, CaPinMismatch, PairingStateError) as error:
        _logger.error("%s", error)
        return 3
    except (DaemonStopped, ProtocolVersionMismatch) as error:
        _logger.error("%s", error)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
