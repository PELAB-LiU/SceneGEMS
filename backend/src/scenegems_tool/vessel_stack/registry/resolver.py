"""Resolver: does a stack combination exist, what does it support, and is a request valid on it.

For a requested (ASV software, control layer, simulation layer) the resolver looks up the
two adapters that connect the three layers. A missing adapter makes the combination
unavailable, with the reason of the ruled-out connection when the design declares one.
When the chain exists, its capabilities are the weakest link over its three layers and two
adapters. A request (environment, speedup, attended or not) is then checked against them:
unsupported wind or waves, and a speedup the chain cannot run, are rejected with a reason
and never dropped silently.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, AnySpec, SpecStatus
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, EnvironmentSupport, RepeatabilityTier, weakest_link
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, LayerRef, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, SimulationInstanceConfig, VesselStackConfig
from scenegems_tool.vessel_stack.registry.adapter_registry import AdapterRegistry


class StackUnavailableError(ValueError):
    def __init__(self, reasons: Iterable[str]):
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons))


@dataclass(frozen=True)
class ChainResolution:
    stack: VesselStackConfig
    specs: Tuple[AnySpec, ...]  # registered layers and adapters on the chain, from ASV software down
    complete: bool  # every layer and adapter of the chain exists, implemented or planned
    reasons: Tuple[str, ...]  # why the combination cannot be used now; empty when available

    @property
    def available(self) -> bool:
        return self.complete and not self.reasons

    @property
    def planned_specs(self) -> Tuple[AnySpec, ...]:
        return tuple(spec for spec in self.specs if spec.status == SpecStatus.PLANNED)

    @property
    def adapters(self) -> Tuple[AdapterSpec, ...]:
        return tuple(spec for spec in self.specs if isinstance(spec, AdapterSpec))

    @property
    def capabilities(self) -> Optional[Capabilities]:
        """Weakest link over the chain; None when the chain does not exist."""
        if not self.complete:
            return None
        return weakest_link(spec.capabilities for spec in self.specs)

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)

    @property
    def design_status(self) -> str:
        """The availability the design promises once every planned adapter exists."""
        capabilities = self.capabilities
        if capabilities is None:
            return "no"
        return "yes, interactive only" if capabilities.interactive_only else "yes"

    @property
    def status(self) -> str:
        if self.available:
            return "available"
        if self.complete:
            phases = sorted({spec.planned_phase for spec in self.planned_specs if spec.planned_phase is not None})
            return f"planned (phase {', '.join(str(phase) for phase in phases)})" if phases else "planned"
        return "unavailable"


@dataclass(frozen=True)
class InstanceResolution:
    instance: SimulationInstanceConfig
    chains: Mapping[str, ChainResolution]  # by agent id, simulated vessels only
    capabilities: Optional[Capabilities]  # weakest link over every vessel chain, since all share one clock
    errors: Tuple[str, ...]
    warnings: Tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return not self.errors

    @property
    def reason(self) -> str:
        return "; ".join(self.errors)

    @property
    def repeatability_tier(self) -> Optional[RepeatabilityTier]:
        """Tier of this run at the requested speedup."""
        if self.capabilities is None:
            return None
        return self.capabilities.repeatability_at(self.instance.speedup)

    def require(self) -> "InstanceResolution":
        if self.errors:
            raise StackUnavailableError(self.errors)
        return self

    def effective_environment(self) -> Dict[str, Any]:
        """Environment the run applies, for the run record. Only an accepted request has one."""
        environment = self.instance.environment
        wave = environment.wave
        return {
            "wind_vector": [float(component) for component in environment.wind_vector] if environment.wind_requested else None,
            "waves": (
                {"amplitude": wave.amplitude, "period": wave.period, "steepness": wave.steepness, "direction": [float(component) for component in wave.direction]}
                if environment.waves_requested
                else None
            ),
            "seed": environment.seed,
        }


class StackResolver:
    def __init__(self, registry: AdapterRegistry):
        self.registry = registry

    def resolve(self, stack: VesselStackConfig) -> ChainResolution:
        refs = (LayerRef.of(stack.asv_software), LayerRef.of(stack.control_layer), LayerRef.of(stack.simulation_layer))
        connections = tuple(zip(refs, refs[1:]))
        layers = [self.registry.layer(ref) for ref in refs]
        adapters = [self.registry.adapter_between(upper, lower) for upper, lower in connections]
        reasons = [f"{ref} is not registered" for ref, layer in zip(refs, layers) if layer is None]
        for (upper, lower), adapter in zip(connections, adapters):
            if adapter is None:
                unsupported = self.registry.unsupported_between(upper, lower)
                reasons.append(f"no adapter from {upper} to {lower}: {unsupported.reason}" if unsupported else f"no adapter from {upper} to {lower} is registered")
        chain = (layers[0], adapters[0], layers[1], adapters[1], layers[2])
        specs = tuple(spec for spec in chain if spec is not None)
        complete = len(specs) == len(chain)
        if complete:
            for spec in specs:
                if spec.status == SpecStatus.PLANNED:
                    phase = f" for phase {spec.planned_phase}" if spec.planned_phase is not None else ""
                    reasons.append(f"{spec.id} is planned{phase} and not implemented yet")
        return ChainResolution(stack=stack, specs=specs, complete=complete, reasons=tuple(reasons))

    def resolve_instance(self, instance: SimulationInstanceConfig, *, attended: bool = True) -> InstanceResolution:
        """Validate a whole simulation instance. attended=False is an unattended campaign run."""
        errors: List[str] = []
        warnings: List[str] = []
        chains: Dict[str, ChainResolution] = {}
        for agent_id, vessel in instance.simulated_vessels.items():
            if vessel.stack.simulation_layer != instance.simulation_layer:
                errors.append(f"vessel {agent_id} uses simulation layer {vessel.stack.simulation_layer.value}, but all vessels of one instance share {instance.simulation_layer.value}")
            chain = self.resolve(vessel.stack)
            chains[agent_id] = chain
            if not chain.available:
                errors.append(f"vessel {agent_id} ({vessel.stack}): {chain.reason}")
        if errors or not chains:
            return InstanceResolution(instance=instance, chains=chains, capabilities=None, errors=tuple(errors), warnings=tuple(warnings))

        specs = _unique(spec for chain in chains.values() for spec in chain.specs)
        capabilities = weakest_link(spec.capabilities for spec in specs)
        _check_environment(specs, instance.environment, errors, warnings)
        _check_speedup(specs, instance.speedup, errors, warnings)
        if capabilities.interactive_only and not attended:
            for spec in specs:
                if spec.capabilities.interactive_only:
                    errors.append(_with_note(f"{spec.id} is interactive only and is rejected for unattended runs", spec, "interactive_only"))
        return InstanceResolution(instance=instance, chains=chains, capabilities=capabilities, errors=tuple(errors), warnings=tuple(warnings))

    def require_instance(self, instance: SimulationInstanceConfig, *, attended: bool = True) -> InstanceResolution:
        return self.resolve_instance(instance, attended=attended).require()

    def availability_matrix(self) -> List[ChainResolution]:
        """Every combination of the three roles, in the order of the design's availability table."""
        return [
            self.resolve(VesselStackConfig(asv_software=asv_software, control_layer=control_layer, simulation_layer=simulation_layer))
            for asv_software in AsvSoftwareId
            for simulation_layer in SimulationLayerId
            for control_layer in ControlLayerId
        ]


def _unique(specs: Iterable[AnySpec]) -> Tuple[AnySpec, ...]:
    seen: Dict[str, AnySpec] = {}
    for spec in specs:
        seen.setdefault(spec.id, spec)
    return tuple(seen.values())


def _with_note(message: str, spec: AnySpec, capability: str) -> str:
    note = spec.note_for(capability)
    return f"{message}: {note}" if note else message


def _check_environment(specs: Iterable[AnySpec], environment: EnvironmentConfig, errors: List[str], warnings: List[str]) -> None:
    for capability, requested in (("wind", environment.wind_requested), ("waves", environment.waves_requested)):
        if not requested:
            continue
        for spec in specs:
            support = getattr(spec.capabilities, capability)
            if support == EnvironmentSupport.UNSUPPORTED:
                errors.append(_with_note(f"{capability} requested, but {spec.id} does not support {capability}", spec, capability))
            elif support == EnvironmentSupport.UNMEASURED:
                warnings.append(_with_note(f"{capability} requested, but support for {capability} in {spec.id} is unmeasured", spec, capability))


def _check_speedup(specs: Iterable[AnySpec], speedup: float, errors: List[str], warnings: List[str]) -> None:
    if speedup < 1:
        errors.append(f"speedup {speedup:g} is below 1; slower than real time is not supported")
        return
    if speedup == 1:
        return
    real_time_only = [spec.id for spec in specs if not spec.capabilities.faster_than_real_time]
    if real_time_only:
        errors.append(f"speedup {speedup:g} requested, but {', '.join(real_time_only)} cannot run faster than real time, so this stack is capped at 1x")
        return
    exceeded = [spec for spec in specs if spec.capabilities.max_speedup is not None and speedup > spec.capabilities.max_speedup]
    for spec in exceeded:
        errors.append(f"speedup {speedup:g} exceeds the measured max_speedup {spec.capabilities.max_speedup:g} of {spec.id}")
    unmeasured = [spec.id for spec in specs if spec.capabilities.max_speedup is None]
    if unmeasured and not exceeded:
        warnings.append(f"speedup {speedup:g} is unverified: max_speedup of {', '.join(unmeasured)} is not measured yet")
