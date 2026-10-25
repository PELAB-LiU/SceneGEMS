"""A master and a node of one cluster on this host, deployed from a release bundle the way the
deployment tool deploys them (cluster/release/roles.py).

Each role gets a folder of its own with its stack and release.json, and a .env made of the
role's values, its parameters and secrets generated here. The master's setup commands run in
its folder, the master's pairing output goes into the node's .env, and each compose project
is started and waited for until the role's ready services are up. Nodes reach the master
through host.docker.internal, which stands in for the master's VPN address.
"""

import json
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from scenegems_tool.cluster.release.manifest import Release

MASTER_ADDRESS = "host.docker.internal"


def render(text: str, context: Mapping[str, str]) -> str:
    for placeholder, value in context.items():
        text = text.replace("{" + placeholder + "}", value)
    return text


def run(command: List[str], cwd: Path, timeout_s: float = 600) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout_s)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed in {cwd} ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


@dataclass
class LocalRole:
    """One deployed role: its folder, compose project and ready services."""

    name: str
    folder: Path
    ready: Mapping[str, List[str]]

    def compose(self, *arguments: str, timeout_s: float = 600) -> str:
        return run(["docker", "compose", *arguments], self.folder, timeout_s)

    def services(self) -> Dict[str, Dict[str, Any]]:
        output = self.compose("ps", "--all", "--format", "json")
        lines = [json.loads(line) for line in output.splitlines() if line.strip()]
        return {line["Service"]: line for line in lines}

    def is_ready(self) -> bool:
        services = self.services()
        running = all(services.get(service, {}).get("State") == "running" for service in self.ready.get("running", []))
        healthy = all(services.get(service, {}).get("Health") == "healthy" for service in self.ready.get("healthy", []))
        return running and healthy

    def wait_ready(self, timeout_s: float = 300) -> None:
        deadline = time.monotonic() + timeout_s
        while not self.is_ready():
            if time.monotonic() > deadline:
                raise TimeoutError(f"{self.name} is not ready after {timeout_s:.0f} s: {self.services()}")
            time.sleep(2)

    def down(self) -> None:
        try:
            self.compose("down", "--volumes", "--remove-orphans", timeout_s=300)
        except RuntimeError:
            pass


def _install(release_dir: Path, role: Mapping[str, Any], folder: Path) -> None:
    if folder.exists():
        shutil.rmtree(folder)
    shutil.copytree(release_dir / "stacks" / role["stack"], folder)
    shutil.copy(release_dir / "release.json", folder / "release.json")


def _write_env(folder: Path, values: Mapping[str, str]) -> None:
    (folder / ".env").write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8", newline="\n")


def _role_env(role: Mapping[str, Any], context: Mapping[str, str], parameters: Optional[Mapping[str, str]]) -> Dict[str, str]:
    values = {key: render(value, context) for key, value in role["env"].items()}
    values.update({key: definition["default"] for key, definition in role["parameters"].items()})
    values.update(parameters or {})
    values.update({key: secrets.token_urlsafe(32) for key in role["secrets"]})
    return values


def deploy_master(release_dir: Path, release: Release, work_dir: Path, cluster: str, parameters: Optional[Mapping[str, str]] = None) -> LocalRole:
    role = release.roles["master"]
    context = {"cluster": cluster, "name": cluster, "machine.vpn_ip": MASTER_ADDRESS, "machine.name": "local", "release.revision": release.revision}
    folder = work_dir / f"master-{cluster}"
    _install(release_dir, role, folder)
    _write_env(folder, _role_env(role, context, parameters))
    master = LocalRole(name=f"master {cluster}", folder=folder, ready=role["ready"])
    for command in role["setup"]:
        run([render(part, context) for part in command], folder)
    master.compose("up", "--detach")
    master.wait_ready()
    return master


def pairing_values(release: Release, master: LocalRole, cluster: str, dependent_name: str) -> Dict[str, str]:
    """The master's pairing output for one node, as the KEY=VALUE lines the node's .env needs."""
    command = release.roles["master"]["outputs"]["pairing"]["command"]
    context = {"cluster": cluster, "dependent.name": dependent_name}
    output = run([render(part, context) for part in command], master.folder)
    keys = release.roles["node"]["requires"]["keys"]
    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    return {key: values[key] for key in keys}


def deploy_node(release_dir: Path, release: Release, work_dir: Path, cluster: str, name: str, pairing: Mapping[str, str], parameters: Optional[Mapping[str, str]] = None) -> LocalRole:
    role = release.roles["node"]
    context = {"cluster": cluster, "name": name, "machine.vpn_ip": MASTER_ADDRESS, "machine.name": "local", "release.revision": release.revision}
    folder = work_dir / f"node-{cluster}-{name}"
    _install(release_dir, role, folder)
    _write_env(folder, {**_role_env(role, context, parameters), **pairing})
    node = LocalRole(name=f"node {name}", folder=folder, ready=role["ready"])
    node.compose("up", "--detach")
    node.wait_ready()
    return node


def remove_cluster_containers(cluster: str) -> None:
    """Subsystem containers a node started for this cluster and left behind."""
    names = subprocess.run(["docker", "ps", "--all", "--quiet", "--filter", f"name=scenegems-{cluster}-"], capture_output=True, text=True).stdout.split()
    if names:
        subprocess.run(["docker", "rm", "--force", *names], capture_output=True)
