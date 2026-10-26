"""The roles of a SceneGEMS cluster, written into release.json for the deployment tool.

A cluster is one master and any number of nodes; one machine may hold several roles of
several clusters. For each role the tool installs `stacks/<stack>/` plus release.json into
a folder on the machine, writes its `.env`, runs the setup commands and starts the compose
project. The fields are the contract with the tool:

    description      shown to the operator
    count            "one" (one machine per cluster) or "many"
    stack            folder under stacks/ with the compose file
    project          compose project name
    images           images the role always needs
    env              values the tool writes into .env
    parameters       values the operator may change per machine, with defaults; a parameter
                     with `items` is a list (for example capabilities with slots), and
                     `items.images` names the extra images each item needs
    secrets          .env keys generated once on the machine (random) and kept afterwards
    requires         another role whose output's KEY=VALUE lines go into this role's .env,
                     kept afterwards like secrets (a node's pairing values)
    outputs          commands run in the role's folder whose stdout is secret KEY=VALUE lines
    setup            commands run in the role's folder before the project starts (idempotent)
    ready            services that must be running, or healthy, after the start

Text in env, parameters, commands and project may use {cluster} (the cluster id, which is
the master id), {name} (the role's instance name on that machine), {machine.vpn_ip},
{machine.name}, {release.revision} and, in outputs, {dependent.name} (the instance name of
the role that requires the output). Cluster ids and instance names follow `name_pattern`,
because they become MQTT topic levels and Docker names.
"""

from typing import Any, Dict, List

from scenegems_tool.cluster.fingerprints.job_images import GAZEBO_IMAGE, JOB_TYPE_IMAGES
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.security.scope_names import SCOPE_NAME_PATTERN

BACKEND_IMAGE = "scenegems-backend:latest"
BROKER_IMAGE = "scenegems-mqtt-broker:latest"
POSTGRES_IMAGE = "postgres:16.10-alpine"
NODE_IMAGE = "scenegems-node:latest"

# docker compose ... run of the master's one-off security tool (deploy/master/docker-compose.yml, profile tools)
_SECURITY_TOOL = ["docker", "compose", "--profile", "tools", "run", "--rm", "-T", "security"]

# Where the web UI is served from (cluster/master/settings.py)
DEFAULT_OPERATOR_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
DEFAULT_NODE_CAPABILITIES = "simulation.kinematic:2,scene_generation:1,trajectory_generation:1,monitoring.post_hoc:1"
# The artifact store on the master and the artifact cache on a node (cluster/master/settings.py, node_configuration.py)
DEFAULT_ARTIFACT_MAX_BYTES = str(256 * 1024 * 1024)
DEFAULT_ARTIFACT_SWEEP_INTERVAL_S = "600"
DEFAULT_ARTIFACT_SWEEP_GRACE_S = "3600"
DEFAULT_NODE_ARTIFACT_CACHE_MAX_BYTES = str(2 * 1024 * 1024 * 1024)


def capability_item_images() -> Dict[str, List[str]]:
    """The images a node needs for each job type it offers. A simulation.ardupilot node gets Gazebo as well, so it runs both layers."""
    images = {job_type.value: list(JOB_TYPE_IMAGES[job_type]) for job_type in JobType}
    images[JobType.SIMULATION_ARDUPILOT.value].append(GAZEBO_IMAGE)
    return images


def master_role() -> Dict[str, Any]:
    return {
        "description": "Master: node API, scheduler, Postgres and the cluster broker",
        "count": "one",
        "stack": "master",
        "project": "scenegems-{cluster}",
        "images": [BACKEND_IMAGE, BROKER_IMAGE, POSTGRES_IMAGE],
        "env": {
            "COMPOSE_PROJECT_NAME": "scenegems-{cluster}",
            "SCENEGEMS_MASTER_ID": "{cluster}",
            "SCENEGEMS_MASTER_ADDRESSES": "{machine.vpn_ip}",
            "SCENEGEMS_SECURITY_DIR": "./security_data",
            "SCENEGEMS_BROKER_MASTER_USERNAME": "master",
            "SCENEGEMS_BROKER_AUTH_HOOK_URL": "http://master-api:8090/cluster/broker/auth",
            "POSTGRES_DB": "scenegems",
            "POSTGRES_USER": "scenegems",
        },
        "parameters": {
            "SCENEGEMS_API_PORT": {"default": "8443", "description": "HTTPS port of the node API"},
            "SCENEGEMS_BROKER_TLS_PORT": {"default": "8883", "description": "TLS port of the cluster broker"},
            "SCENEGEMS_OPERATOR_PORT": {"default": "5174", "description": "operator API and workbench gateway, published on 127.0.0.1 only"},
            "SCENEGEMS_OPERATOR_ALLOWED_ORIGINS": {
                "default": DEFAULT_OPERATOR_ALLOWED_ORIGINS,
                "description": "browser origins the operator API allows (CORS), comma separated: where the web UI is served from",
            },
            "POSTGRES_HOST_PORT": {"default": "5432", "description": "Postgres, published on 127.0.0.1 only"},
            "SCENEGEMS_API_BIND_ADDRESS": {"default": "0.0.0.0", "description": "host address the node API is published on"},
            "SCENEGEMS_BROKER_BIND_ADDRESS": {"default": "0.0.0.0", "description": "host address the cluster broker is published on"},
            "SCENEGEMS_ARTIFACT_MAX_BYTES": {"default": DEFAULT_ARTIFACT_MAX_BYTES, "description": "largest artifact a node may upload, uncompressed, in bytes"},
            "SCENEGEMS_ARTIFACT_SWEEP_INTERVAL_S": {"default": DEFAULT_ARTIFACT_SWEEP_INTERVAL_S, "description": "seconds between sweeps of unreferenced artifacts; 0 turns the sweep off"},
            "SCENEGEMS_ARTIFACT_SWEEP_GRACE_S": {"default": DEFAULT_ARTIFACT_SWEEP_GRACE_S, "description": "seconds an unreferenced artifact is kept after its last use"},
        },
        "secrets": ["POSTGRES_PASSWORD", "SCENEGEMS_BROKER_MASTER_PASSWORD", "SCENEGEMS_BROKER_AUTH_HOOK_SECRET"],
        "setup": [_SECURITY_TOOL + ["init"]],
        "outputs": {"pairing": {"command": _SECURITY_TOOL + ["pairing-token", "create", "--note", "{dependent.name}"]}},
        "ready": {"healthy": ["master-api"], "running": ["postgres", "cluster-broker"]},
    }


def node_role() -> Dict[str, Any]:
    return {
        "description": "Node: the node daemon, which leases jobs from its master and runs them in subsystem containers",
        "count": "many",
        "stack": "node",
        "project": "scenegems-node-{cluster}-{name}",
        "images": [NODE_IMAGE],
        "requires": {
            "role": "master",
            "output": "pairing",
            "keys": ["SCENEGEMS_MASTER_ID", "SCENEGEMS_MASTER_URL", "SCENEGEMS_PAIRING_TOKEN", "SCENEGEMS_MASTER_CA_SHA256"],
        },
        "env": {
            "SCENEGEMS_NODE_NAME": "{name}",
            "SCENEGEMS_NODE_MACHINE": "{machine.name}",
            "SCENEGEMS_SOFTWARE_REVISION": "{release.revision}",
        },
        "parameters": {
            "SCENEGEMS_NODE_CAPABILITIES": {
                "default": DEFAULT_NODE_CAPABILITIES,
                "description": "job types and how many of each run at once, as type:slots separated by commas",
                "items": {"separator": ",", "key_separator": ":", "images": capability_item_images()},
            },
            "SCENEGEMS_NODE_LABELS": {"default": "", "description": "optional labels jobs can require, as key=value separated by commas"},
            "SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES": {"default": DEFAULT_NODE_ARTIFACT_CACHE_MAX_BYTES, "description": "bound of the node's artifact cache in bytes; 0 turns it off"},
        },
        "secrets": [],
        "setup": [],
        "outputs": {},
        "ready": {"running": ["node"]},
    }


def scenegems_roles() -> Dict[str, Any]:
    return {"master": master_role(), "node": node_role()}


def role_images(roles: Dict[str, Any]) -> List[str]:
    """Every image any role may need, sorted."""
    images = set()
    for role in roles.values():
        images.update(role["images"])
        for parameter in role["parameters"].values():
            for item_images in parameter.get("items", {}).get("images", {}).values():
                images.update(item_images)
    return sorted(images)


NAME_PATTERN = SCOPE_NAME_PATTERN.pattern
