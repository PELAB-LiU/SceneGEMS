"""Validation of a campaign config against the class catalog and the vessel stack resolver.

A config is accepted only as a whole: every scope entry must name classes the catalog has
(a pattern must match at least one), no class may be named by two entries, and every run's
stack must be available on the resolver for an unattended run in its environment. Every
problem is reported with its reason; nothing is dropped silently.

The result carries what creating the campaign needs: the config as JSON and its hash, and
the classes with their pinned content hashes, quotas and failure budgets.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from scenegems_tool.assurance.campaign.campaign_config import CampaignConfig, CampaignConfigError, RunConfig, StackConfig
from scenegems_tool.assurance.campaign.class_catalog import ClassCatalog
from scenegems_tool.cluster.node.jobs.simulation_kinematic_job import KinematicMode
from scenegems_tool.persistence.stores import ClassSpec
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, SimulationInstanceConfig, VesselConfig, VesselStackConfig, WaveConfig
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.registry.resolver import StackResolver

OWN_SHIP, TARGET_SHIP = "own_ship", "target_ship"


class CampaignConfigRejected(CampaignConfigError):
    """The config is well formed, but the catalog or the resolver refuses it."""


@dataclass(frozen=True)
class RunStacks:
    """The stacks of one run as the resolver accepted them."""

    run_index: int
    vessels: Dict[str, VesselStackConfig]  # own_ship, and target_ship for the other vessels
    repeatability_tier: Optional[str]  # exact, bounded or none
    environment: Dict  # the environment the run applies (wind, waves), for the run record; the seed is per case
    warnings: Tuple[str, ...]


@dataclass(frozen=True)
class ValidatedCampaign:
    config: CampaignConfig
    config_json: Dict
    config_hash: str
    classes: Tuple[ClassSpec, ...]  # in scope order, each class once
    runs: Tuple[RunStacks, ...]

    @property
    def total_quota(self) -> int:
        return sum(spec.quota for spec in self.classes)


def vessel_stacks(stack: StackConfig) -> Dict[str, VesselStackConfig]:
    """The triple of the own ship and of the target ships for a run's stack."""
    replay = VesselStackConfig(AsvSoftwareId.REPLAY, ControlLayerId.NONE, SimulationLayerId.KINEMATIC)
    if stack.mode == KinematicMode.USV_NAVIGATION:
        return {OWN_SHIP: VesselStackConfig(AsvSoftwareId.USV_NAVIGATION, ControlLayerId.NONE, SimulationLayerId.KINEMATIC), TARGET_SHIP: replay}
    return {OWN_SHIP: replay, TARGET_SHIP: replay}


def _environment(run: RunConfig) -> EnvironmentConfig:
    waves = run.environment.waves
    wave = WaveConfig(amplitude=0.0, period=0.0, steepness=0.0, direction=np.zeros(2))
    if waves is not None:
        wave = WaveConfig(amplitude=waves.amplitude, period=waves.period, steepness=waves.steepness, direction=np.array(waves.direction, dtype=float))
    return EnvironmentConfig(wind_vector=np.array(run.environment.wind_vector, dtype=float), wave=wave)


def resolve_run(run: RunConfig, run_index: int, resolver: StackResolver) -> Tuple[Optional[RunStacks], List[str]]:
    """The run's stacks on the resolver, as an unattended run; the reasons when it refuses them."""
    stacks = vessel_stacks(run.stack)
    instance = SimulationInstanceConfig(
        simulation_layer=SimulationLayerId(run.stack.simulation_layer),
        environment=_environment(run),
        vessels={agent_id: VesselConfig(agent_id=agent_id, stack=stack) for agent_id, stack in stacks.items()},
    )
    resolution = resolver.resolve_instance(instance, attended=False)
    if not resolution.accepted:
        label = f"execution.runs.{run_index}" + (f" ({run.name})" if run.name else "")
        return None, [f"{label}: {error}" for error in resolution.errors]
    tier = resolution.repeatability_tier
    environment = {key: value for key, value in resolution.effective_environment().items() if key != "seed"}
    return RunStacks(run_index, stacks, None if tier is None else tier.value, environment, resolution.warnings), []


def resolve_scope(config: CampaignConfig, catalog: ClassCatalog) -> Tuple[Tuple[ClassSpec, ...], List[str]]:
    """The classes of the scope in order, each once, with their entry's quota and failure budget."""
    reasons: List[str] = []
    chosen: Dict[str, Tuple[int, ClassSpec]] = {}
    for entry_index, entry in enumerate(config.scope):
        named = []
        for class_id in entry.classes:
            if class_id in catalog:
                named.append(catalog.get(class_id))
            else:
                reasons.append(f"scope.{entry_index}: no class {class_id!r} in the catalog")
        for pattern in entry.patterns:
            matched = catalog.expand(pattern)
            if not matched:
                reasons.append(f"scope.{entry_index}: the pattern {pattern!r} matches no class")
            named.extend(matched)
        for scenario_class in named:
            earlier = chosen.get(scenario_class.class_id)
            if earlier is not None:
                if earlier[0] != entry_index:
                    reasons.append(f"scope.{entry_index}: class {scenario_class.class_id!r} is in scope.{earlier[0]} already")
                continue
            spec = ClassSpec(
                class_id=scenario_class.class_id,
                content_hash=scenario_class.content_hash,
                vessel_count=scenario_class.vessel_count,
                obstacle_count=scenario_class.obstacle_count,
                quota=entry.quota,
                failure_budget=entry.failure_budget,
            )
            chosen[scenario_class.class_id] = (entry_index, spec)
    return tuple(spec for _, spec in chosen.values()), reasons


def validate_campaign_config(config: CampaignConfig, catalog: Optional[ClassCatalog] = None, resolver: Optional[StackResolver] = None) -> ValidatedCampaign:
    """Checks the config against the catalog and the resolver; raises CampaignConfigRejected with every reason."""
    catalog = catalog or ClassCatalog.default()
    resolver = resolver or default_resolver()
    classes, reasons = resolve_scope(config, catalog)
    runs = []
    for run_index, run in enumerate(config.execution.runs):
        resolved, run_reasons = resolve_run(run, run_index, resolver)
        reasons.extend(run_reasons)
        if resolved is not None:
            runs.append(resolved)
    if reasons:
        raise CampaignConfigRejected(reasons)
    config_json = config.to_json()
    return ValidatedCampaign(config=config, config_json=config_json, config_hash=config.config_hash(), classes=classes, runs=tuple(runs))
