"""Declarative specs of the adapter graph.

Nodes are layer implementations (LayerSpec): one ASV software, control layer or simulation
layer. Edges are adapters (AdapterSpec) that connect an implementation of one role to an
implementation of the next role down the stack. A connection the design rules out is
declared as an UnsupportedConnection, so the resolver can say why it is missing.
"""

import dataclasses
from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional, Tuple, Union

from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import LayerRef, Role


class SpecStatus(str, Enum):
    AVAILABLE = "available"
    PLANNED = "planned"  # part of the design, not implemented yet


UPSTREAM_PINS_FILE = "deploy/images/upstream_pins.env"  # upstream commits the simulator images build from


@dataclass(frozen=True)
class ContainerSpec:
    """A container a spec adds to a per-job stack."""

    image: str  # compose image reference, overridable through the environment variable it names
    build_fingerprint_source: str  # repo path whose content stamps the image build
    entrypoint: str
    cpus: Optional[float] = None
    upstream_pins_file: Optional[str] = None  # repo path of the upstream pins the image builds from, also part of the stamp

    @property
    def build_fingerprint_sources(self) -> Tuple[str, ...]:
        """Every repo path whose content stamps the image build."""
        return tuple(source for source in (self.build_fingerprint_source, self.upstream_pins_file) if source)


@dataclass(frozen=True)
class LayerSpec:
    layer: LayerRef
    description: str
    capabilities: Capabilities = Capabilities()
    # (capability field, reason) pairs, shown when that capability rejects a request.
    restriction_notes: Tuple[Tuple[str, str], ...] = ()
    provides_ports: FrozenSet[Port] = frozenset()
    requires_ports: FrozenSet[Port] = frozenset()
    containers: Tuple[ContainerSpec, ...] = ()
    status: SpecStatus = SpecStatus.AVAILABLE
    planned_phase: Optional[int] = None

    @property
    def id(self) -> str:
        return str(self.layer)

    def note_for(self, capability: str) -> Optional[str]:
        return dict(self.restriction_notes).get(capability)

    def with_capabilities(self, capabilities: Capabilities, restriction_notes: Tuple[Tuple[str, str], ...] = ()) -> "LayerSpec":
        return dataclasses.replace(self, capabilities=capabilities, restriction_notes=_merge_notes(self.restriction_notes, restriction_notes))


@dataclass(frozen=True)
class AdapterSpec:
    id: str
    source: LayerRef
    target: LayerRef
    description: str
    capabilities: Capabilities = Capabilities()
    restriction_notes: Tuple[Tuple[str, str], ...] = ()
    provides_ports: FrozenSet[Port] = frozenset()
    requires_ports: FrozenSet[Port] = frozenset()
    containers: Tuple[ContainerSpec, ...] = ()
    status: SpecStatus = SpecStatus.AVAILABLE
    planned_phase: Optional[int] = None

    def note_for(self, capability: str) -> Optional[str]:
        return dict(self.restriction_notes).get(capability)

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

    def with_capabilities(self, capabilities: Capabilities, restriction_notes: Tuple[Tuple[str, str], ...] = ()) -> "AdapterSpec":
        return dataclasses.replace(self, capabilities=capabilities, restriction_notes=_merge_notes(self.restriction_notes, restriction_notes))


def _merge_notes(base: Tuple[Tuple[str, str], ...], override: Tuple[Tuple[str, str], ...]) -> Tuple[Tuple[str, str], ...]:
    merged = dict(base)
    merged.update(override)
    return tuple(merged.items())


@dataclass(frozen=True)
class UnsupportedConnection:
    """A connection the design rules out, with the reason shown to the user."""

    source: LayerRef
    target: LayerRef
    reason: str


AnySpec = Union[LayerSpec, AdapterSpec]
