"""Declarative specs of the adapter graph.

Nodes are layer implementations (LayerSpec): one ASV software, control layer or simulation
layer. Edges are adapters (AdapterSpec) that connect an implementation of one role to an
implementation of the next role down the stack. A connection the design rules out is
declared as an UnsupportedConnection, so the resolver can say why it is missing.
"""

import dataclasses
from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional, Tuple

from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import LayerRef, Role


class SpecStatus(str, Enum):
    AVAILABLE = "available"
    PLANNED = "planned"  # part of the design, not implemented yet


@dataclass(frozen=True)
class ContainerSpec:
    """A container a spec adds to a per-job stack."""

    image: str  # compose image reference, overridable through the environment variable it names
    build_fingerprint_source: str  # repo path whose content stamps the image build
    entrypoint: str
    cpus: Optional[float] = None


@dataclass(frozen=True)
class LayerSpec:
    layer: LayerRef
    description: str
    capabilities: Capabilities = Capabilities()
    provides_ports: FrozenSet[Port] = frozenset()
    requires_ports: FrozenSet[Port] = frozenset()
    containers: Tuple[ContainerSpec, ...] = ()
    status: SpecStatus = SpecStatus.AVAILABLE
    planned_phase: Optional[int] = None

    @property
    def id(self) -> str:
        return str(self.layer)

    def with_capabilities(self, capabilities: Capabilities) -> "LayerSpec":
        return dataclasses.replace(self, capabilities=capabilities)


@dataclass(frozen=True)
class AdapterSpec:
    id: str
    source: LayerRef
    target: LayerRef
    description: str
    capabilities: Capabilities = Capabilities()
    provides_ports: FrozenSet[Port] = frozenset()
    requires_ports: FrozenSet[Port] = frozenset()
    containers: Tuple[ContainerSpec, ...] = ()
    status: SpecStatus = SpecStatus.AVAILABLE
    planned_phase: Optional[int] = None

    @property
    def from_role(self) -> Role:
        return self.source.role

    @property
    def from_impl(self) -> str:
        return self.source.impl

    @property
    def to_role(self) -> Role:
        return self.target.role

    @property
    def to_impl(self) -> str:
        return self.target.impl

    def with_capabilities(self, capabilities: Capabilities) -> "AdapterSpec":
        return dataclasses.replace(self, capabilities=capabilities)


@dataclass(frozen=True)
class UnsupportedConnection:
    """A connection the design rules out, with the reason shown to the user."""

    source: LayerRef
    target: LayerRef
    reason: str
