"""The campaign config: what a campaign runs, as an immutable, hashed pydantic model.

Sections:
    scope           classes (catalog ids or folder patterns), each entry with a quota and a failure budget
    domain          COLREGS constants, vessel types and obstacle types as content (defaults from
                    backend/assets/domain_config/), the scene generation timeout, enforce_low_tcpa
    trajectories    the generator: monitor_driven_rrt with its search parameters (the wire keys of
                    TrajectoryGenerationParams) or straight with its timespan; the timeout
    execution       the runs of every case: a stack, an environment, a seed, repeats, the monitor
    resources       the nodes it may use (all when none are named), required node labels, queue depth
                    caps per stage, priority
    policy          retention, whether to keep frames, the campaign seed, stop conditions

Unknown fields are rejected everywhere. YAML is read with a safe loader that also rejects
duplicate keys. The hash is the sha256 of the config's canonical JSON with every default
filled in, so it pins the domain content too. Content strings get LF line endings, so a
config hashes the same from a Windows and a Linux checkout.

Every case seed derives from the campaign seed, the class id and the case index
(case_seed), and every run seed from the case seed and the run index unless the run fixes
one (RunConfig.seed_for).
"""

import hashlib
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Literal, Mapping, Optional, Tuple, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from scenegems_tool.cluster.node.jobs.simulation_kinematic_job import KinematicMode, UsvNavigationPayload
from scenegems_tool.cluster.node.jobs.trajectory_generation_job import PARAM_KEYS
from scenegems_tool.persistence.canonical_json import canonical_json_sha256
from scenegems_tool.persistence.schema import MonitorImplementation, PipelineStage, TrajectoryGeneratorImplementation
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import TrajectoryGenerationParams
from utils.file_system_utils import COLREGS_CONSTANTS_FOLDER, STATIC_OBSTACLE_TYPES_FOLDER, VESSEL_TYPES_FOLDER

CONFIG_FORMAT = 1
MAX_SEED = 2**31 - 1  # seeds are 31-bit, so every consumer (numpy included) takes them

DEFAULT_COLREGS_CONSTANTS_FILE = Path(COLREGS_CONSTANTS_FOLDER) / "general_maritime_constants.yaml"
DEFAULT_VESSEL_TYPES_FILE = Path(VESSEL_TYPES_FOLDER) / "vessel_types.yaml"
DEFAULT_OBSTACLE_TYPES_FILE = Path(STATIC_OBSTACLE_TYPES_FOLDER) / "static_obstacle_types.yaml"

# The generator choice travels in the trajectory parameters on the wire (P4.2); here it is its own field
GENERATOR_CHOICE_KEYS = frozenset({"generator", "timespan"})
SEARCH_PARAM_KEYS = frozenset(PARAM_KEYS) - GENERATOR_CHOICE_KEYS


def normalize_newlines(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


def read_domain_file(path: Path) -> str:
    return normalize_newlines(path.read_text(encoding="utf-8"))


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# Scope


class ScopeEntry(ConfigModel):
    """Classes by id (`3vessel_0obstacle_scenarios/functional_model5`) or pattern, with their quota and failure budget.

    A pattern without a slash matches catalog folders (`3vessel_*_scenarios`), one with a
    slash matches class ids (`2vessel_*/functional_model1`), both with shell wildcards.
    """

    classes: Tuple[str, ...] = ()
    patterns: Tuple[str, ...] = ()
    quota: int = Field(ge=1)  # complete cases (with a verdict per run) the class needs
    failure_budget: int = Field(default=0, ge=0)  # dropped and failed cases the class may use up before it is abandoned

    @model_validator(mode="after")
    def _names_classes(self) -> "ScopeEntry":
        if not self.classes and not self.patterns:
            raise ValueError("a scope entry needs classes or patterns")
        return self


# Domain


class DomainConfig(ConfigModel):
    colregs_constants: str = Field(default_factory=lambda: read_domain_file(DEFAULT_COLREGS_CONSTANTS_FILE))  # YAML content
    vessel_types: str = Field(default_factory=lambda: read_domain_file(DEFAULT_VESSEL_TYPES_FILE))
    obstacle_types: str = Field(default_factory=lambda: read_domain_file(DEFAULT_OBSTACLE_TYPES_FILE))
    scene_generation_timeout_s: int = Field(default=60, gt=0)  # the generation's own time limit
    enforce_low_tcpa: bool = False

    @field_validator("colregs_constants", "vessel_types", "obstacle_types")
    @classmethod
    def _yaml_mapping(cls, content: str) -> str:
        content = normalize_newlines(content)
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as error:
            raise ValueError(f"not valid YAML ({error})") from error
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("expected a YAML mapping with at least one entry")
        return content


# Trajectories


class TrajectoriesConfig(ConfigModel):
    generator: TrajectoryGeneratorImplementation = TrajectoryGeneratorImplementation.MONITOR_DRIVEN_RRT
    # monitor_driven_rrt only: search parameters by their wire keys (timeStep, maxIterations, ...); search defaults when absent
    params: Dict[str, Union[bool, int, float]] = Field(default_factory=dict)
    timespan_s: Optional[float] = Field(default=None, gt=0)  # straight only, required there: how far every vessel goes straight on
    timeout_s: float = Field(default=1800.0, gt=0)  # how long a trajectory generation job may take

    @model_validator(mode="after")
    def _parameters_of_the_generator(self) -> "TrajectoriesConfig":
        if self.generator == TrajectoryGeneratorImplementation.STRAIGHT:
            if self.timespan_s is None:
                raise ValueError("the straight generator needs timespan_s")
            if self.params:
                raise ValueError("the straight generator takes no search parameters")
            return self
        if self.timespan_s is not None:
            raise ValueError("timespan_s applies to the straight generator only")
        unknown = sorted(set(self.params) - SEARCH_PARAM_KEYS)
        if unknown:
            raise ValueError(f"unknown search parameters {unknown}; known are {sorted(SEARCH_PARAM_KEYS)}")
        try:
            TrajectoryGenerationParams.from_wire(dict(self.params))
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid search parameters ({error})") from error
        return self


# Execution


class WaveSettings(ConfigModel):
    amplitude: float = Field(ge=0)
    period: float = Field(ge=0)
    steepness: float = Field(ge=0)
    direction: Tuple[float, float]  # propagation vector [east, north]; its norm is the wave speed


class EnvironmentSettings(ConfigModel):
    wind_vector: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # [east, north, up] m/s
    waves: Optional[WaveSettings] = None


class KinematicStackConfig(ConfigModel):
    """A run on the kinematic layer: every vessel replays, or the own ship runs USV Navigation.

    Stacks on other simulation layers (ArduPilot) join as a union on simulation_layer.
    """

    simulation_layer: Literal["kinematic"] = "kinematic"
    mode: KinematicMode = KinematicMode.REPLAY
    usv_navigation: Optional[UsvNavigationPayload] = None  # usv_navigation only; derived from each scene when absent
    dt: Optional[float] = Field(default=None, gt=0)  # the trajectories' time step when absent
    steps: Optional[int] = Field(default=None, ge=1)  # the trajectories' timespan when absent

    @model_validator(mode="after")
    def _usv_navigation_needs_its_mode(self) -> "KinematicStackConfig":
        if self.usv_navigation is not None and self.mode != KinematicMode.USV_NAVIGATION:
            raise ValueError("usv_navigation parameters apply only to mode usv_navigation")
        return self


StackConfig = KinematicStackConfig


class RunConfig(ConfigModel):
    name: Optional[str] = None
    stack: StackConfig = Field(default_factory=KinematicStackConfig)
    environment: EnvironmentSettings = Field(default_factory=EnvironmentSettings)
    seed: Optional[int] = Field(default=None, ge=0, le=MAX_SEED)  # one run seed for every case; derived per case when absent
    repeats: int = Field(default=1, ge=1)  # runs with the same seed, for calibration
    monitor: MonitorImplementation = MonitorImplementation.POST_HOC
    early_stop: bool = False  # live only: stop the run once every rule is decided

    @model_validator(mode="after")
    def _early_stop_needs_the_live_monitor(self) -> "RunConfig":
        if self.early_stop and self.monitor != MonitorImplementation.LIVE:
            raise ValueError("early_stop needs the live monitor")
        return self

    def seed_for(self, case_seed_value: int, run_index: int) -> int:
        return self.seed if self.seed is not None else run_seed(case_seed_value, run_index)


class ExecutionConfig(ConfigModel):
    runs: Tuple[RunConfig, ...] = Field(default_factory=lambda: (RunConfig(),), min_length=1)


# Resources


class QueueDepthCaps(ConfigModel):
    """Queued jobs of the campaign per stage; a new case starts only while every stage is under its cap."""

    generate_scene: int = Field(default=16, ge=1)
    generate_trajectories: int = Field(default=16, ge=1)
    simulate: int = Field(default=32, ge=1)
    monitor: int = Field(default=32, ge=1)
    calibrate: int = Field(default=8, ge=1)

    def cap(self, stage: PipelineStage) -> int:
        if stage == PipelineStage.VERDICT:
            raise ValueError("the verdict stage queues no jobs")
        return getattr(self, stage.value)


class ResourcesConfig(ConfigModel):
    nodes: Tuple[str, ...] = ()  # node ids the campaign's jobs may run on; empty: every node, also those that join later
    required_labels: Dict[str, str] = Field(default_factory=dict)  # every job of the campaign needs these node labels
    queue_depth: QueueDepthCaps = Field(default_factory=QueueDepthCaps)
    priority: int = 0  # base priority of the campaign's jobs; later stages run above it

    @field_validator("nodes")
    @classmethod
    def _distinct_node_ids(cls, nodes: Tuple[str, ...]) -> Tuple[str, ...]:
        if any(not node.strip() for node in nodes):
            raise ValueError("a node id must not be empty")
        if len(set(nodes)) != len(nodes):
            raise ValueError("node ids must be distinct")
        return nodes


# Policy


class RetentionPolicy(str, Enum):
    ALL = "all"  # keep every artifact
    FAILURES = "failures"  # trajectories and state logs only of failed verdicts and failed cases
    VERDICTS_ONLY = "verdicts_only"  # no artifacts once a case has its verdicts


class StopConditions(ConfigModel):
    max_cases: Optional[int] = Field(default=None, ge=1)  # no new cases after this many over all classes
    max_failed_verdicts: Optional[int] = Field(default=None, ge=1)  # drain once this many verdicts failed
    max_duration_s: Optional[float] = Field(default=None, gt=0)  # drain after this long running


class PolicyConfig(ConfigModel):
    retention: RetentionPolicy = RetentionPolicy.ALL
    keep_frames: bool = False  # store the monitor's frames as artifacts
    seed: int = Field(default=0, ge=0, le=MAX_SEED)  # the campaign seed
    stop: StopConditions = Field(default_factory=StopConditions)


# The config


class CampaignConfig(ConfigModel):
    format: Literal[1] = CONFIG_FORMAT
    name: str = Field(min_length=1, max_length=256)
    description: str = ""
    scope: Tuple[ScopeEntry, ...] = Field(min_length=1)
    domain: DomainConfig = Field(default_factory=DomainConfig)
    trajectories: TrajectoriesConfig = Field(default_factory=TrajectoriesConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    resources: ResourcesConfig = Field(default_factory=ResourcesConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)

    def to_json(self) -> Dict[str, Any]:
        """The config as JSON with every default filled in: what the database stores and the hash covers."""
        return self.model_dump(mode="json")

    def config_hash(self) -> str:
        return canonical_json_sha256(self.to_json())

    def case_seed(self, class_id: str, case_index: int) -> int:
        return case_seed(self.policy.seed, class_id, case_index)


# Seeds


def _seed_of(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:4], "big") & MAX_SEED


def case_seed(campaign_seed: int, class_id: str, case_index: int) -> int:
    """The seed of a case: the first 31 bits of sha256 over the campaign seed, the class id and the index."""
    if case_index < 0:
        raise ValueError(f"case indexes start at 0, got {case_index}")
    return _seed_of(f"{campaign_seed}:{class_id}:{case_index}")


def run_seed(case_seed_value: int, run_index: int) -> int:
    """The seed of a case's run, derived from the case seed and the run index in the same way."""
    if run_index < 0:
        raise ValueError(f"run indexes start at 0, got {run_index}")
    return _seed_of(f"{case_seed_value}:run:{run_index}")


# Loading


class CampaignConfigError(ValueError):
    """A config that does not load or is not valid; reasons lists every problem found."""

    def __init__(self, reasons):
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons))


class _UniqueKeyLoader(yaml.SafeLoader):
    """yaml.safe_load that refuses a mapping with a key twice instead of keeping the last value."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    keys = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in keys:
            raise yaml.constructor.ConstructorError("while constructing a mapping", node.start_mark, f"found the key {key!r} twice", key_node.start_mark)
        keys.add(key)
    return loader.construct_mapping(node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def _reasons(error: ValidationError) -> Tuple[str, ...]:
    return tuple(f"{'.'.join(str(part) for part in issue['loc']) or 'config'}: {issue['msg']}" for issue in error.errors())


def campaign_config_from_dict(data: Mapping[str, Any]) -> CampaignConfig:
    try:
        return CampaignConfig.model_validate(dict(data))
    except ValidationError as error:
        raise CampaignConfigError(_reasons(error)) from error


def parse_campaign_config(text: str) -> CampaignConfig:
    """A config from YAML text (JSON is YAML too)."""
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 (a SafeLoader subclass)
    except yaml.YAMLError as error:
        raise CampaignConfigError([f"not valid YAML: {error}"]) from error
    if not isinstance(data, dict):
        raise CampaignConfigError(["a campaign config is a mapping of its sections"])
    return campaign_config_from_dict(data)


def load_campaign_config(path: Union[str, Path]) -> CampaignConfig:
    return parse_campaign_config(Path(path).read_text(encoding="utf-8"))
