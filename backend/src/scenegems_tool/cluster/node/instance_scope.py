"""Identity of one subsystem instance on a node, and every name derived from it.

Contract with the broker access rules (design doc 13.7, "Cluster topic scope"):
    topic prefix      scenegems/<master_id>/<node_id>/<instance_id>/
    docker names      scenegems-<master_id>-<node_id>-<instance_id> (compose project, containers, networks)
    instance id       <subsystem>-<index> for a pooled service, job-<job_id> for a per-job stack

The ids are lowercase letters, digits, '-' and '_', so every derived name is valid as an
MQTT topic level, a Docker container name and a compose project name. The workbench has
no scope: its launchers keep the fixed names and the empty topic prefix of a single machine.
"""

import re
from dataclasses import dataclass

from utils.file_system_utils import RUNTIME_ASSETS_FOLDER

SCOPE_ROOT = "scenegems"
INSTANCES_FOLDER = f"{RUNTIME_ASSETS_FOLDER}/instances"  # compose files and generated files of scoped instances, one folder each
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_UNSAFE_ID_CHARACTERS = re.compile(r"[^a-z0-9_-]+")
_DOCKER_NAME_MAX = 128


def _require_id(kind: str, value: str) -> str:
    if not _ID_PATTERN.match(value):
        raise ValueError(f"Invalid {kind} {value!r}: use lowercase letters, digits, '-' and '_', starting with a letter or digit")
    return value


def safe_id(value: str) -> str:
    """An id usable in a scope from any string, such as a job id: lowercase, other characters replaced by '-'."""
    cleaned = _UNSAFE_ID_CHARACTERS.sub("-", value.lower()).strip("-_")
    if not cleaned:
        raise ValueError(f"Cannot derive a scope id from {value!r}")
    return cleaned


def node_topic_scope(master_id: str, node_id: str) -> str:
    """The topic subtree a node's broker account may use: every instance prefix of the node lies under it."""
    return f"{SCOPE_ROOT}/{_require_id('master id', master_id)}/{_require_id('node id', node_id)}/"


@dataclass(frozen=True)
class InstanceScope:
    master_id: str
    node_id: str
    instance_id: str

    def __post_init__(self) -> None:
        _require_id("master id", self.master_id)
        _require_id("node id", self.node_id)
        _require_id("instance id", self.instance_id)
        if len(self.docker_name) > _DOCKER_NAME_MAX:
            raise ValueError(f"Scope name {self.docker_name!r} is longer than {_DOCKER_NAME_MAX} characters")

    @classmethod
    def pooled(cls, master_id: str, node_id: str, subsystem: str, index: int = 0) -> "InstanceScope":
        """A long-lived service instance; index tells apart several pools of one subsystem on a node."""
        if index < 0:
            raise ValueError(f"Pool index must not be negative: {index}")
        return cls(master_id, node_id, f"{_require_id('subsystem', subsystem)}-{index}")

    @classmethod
    def per_job(cls, master_id: str, node_id: str, job_id: str) -> "InstanceScope":
        return cls(master_id, node_id, f"job-{safe_id(job_id)}")

    @property
    def topic_prefix(self) -> str:
        return f"{node_topic_scope(self.master_id, self.node_id)}{self.instance_id}/"

    @property
    def docker_name(self) -> str:
        return f"{SCOPE_ROOT}-{self.master_id}-{self.node_id}-{self.instance_id}"

    @property
    def compose_project(self) -> str:
        return self.docker_name

    def container_name(self, service: str) -> str:
        """Name of one service's container; a single-service instance uses the bare scope name."""
        return f"{self.docker_name}-{safe_id(service)}"

    def network_name(self, key: str) -> str:
        return f"{self.docker_name}-{safe_id(key)}"

    @property
    def folder(self) -> str:
        """Local folder of the instance's compose file and generated files, on the runtime assets volume."""
        return f"{INSTANCES_FOLDER}/{self.docker_name}"
