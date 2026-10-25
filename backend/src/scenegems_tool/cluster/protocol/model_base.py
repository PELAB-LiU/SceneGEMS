"""Base classes of the protocol models.

Every model is immutable and rejects unknown fields, so a sender's typo fails loudly
instead of being dropped. A frame is a top-level message on the wire and carries the
protocol version; nested parts do not.
"""

from pydantic import BaseModel, ConfigDict, field_validator

from scenegems_tool.cluster.protocol.version import PROTOCOL_VERSION, ensure_compatible


class ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProtocolFrame(ProtocolModel):
    protocol_version: int = PROTOCOL_VERSION

    @field_validator("protocol_version")
    @classmethod
    def _same_version(cls, value: int) -> int:
        ensure_compatible(value)
        return value
