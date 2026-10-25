"""Version of the master-node protocol.

Master and node must speak the same version. Every frame carries it, and a frame of
another version is rejected before its body is read, so a version change can reshape
any message without producing confusing validation errors on the other side.
"""

PROTOCOL_VERSION = 1


class ProtocolVersionMismatch(ValueError):
    """Raised when the other side speaks a different protocol version."""

    def __init__(self, received: object, expected: int = PROTOCOL_VERSION) -> None:
        self.received = received
        self.expected = expected
        super().__init__(f"Incompatible cluster protocol version: received {received!r}, this side speaks {expected}. Update the master and every node to the same SceneGEMS revision.")


def ensure_compatible(received: object) -> None:
    if received != PROTOCOL_VERSION:
        raise ProtocolVersionMismatch(received)
