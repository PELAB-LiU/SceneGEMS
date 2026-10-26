"""The roles of release.json agree with the stacks they install and the .env templates."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scenegems_tool.cluster.release.bundle import STACK_COMPOSE_FILES
from scenegems_tool.cluster.release.roles import POSTGRES_IMAGE, scenegems_roles

REPO_ROOT = Path(__file__).resolve().parents[6]
ENV_TEMPLATES = {"master": "deploy/master/.env.example", "node": "deploy/node/.env.example"}
# Read by the master's security tool, not by compose; both may stay empty
SECURITY_TOOL_OPTIONAL = {"SCENEGEMS_MASTER_URL", "SCENEGEMS_BROKER_PUBLIC_HOST"}
_INTERPOLATION = re.compile(r"(?<!\$)\$\{([A-Z_][A-Z0-9_]*)(:?[-?][^}]*)?\}")


def _compose_text(role: str) -> str:
    return (REPO_ROOT / STACK_COMPOSE_FILES[role]).read_text(encoding="utf-8")


def _compose(role: str) -> dict:
    return yaml.safe_load(_compose_text(role))


def _role_keys(role: dict) -> set:
    return set(role["env"]) | set(role["parameters"]) | set(role["secrets"]) | set(role.get("requires", {}).get("keys", []))


def _template_keys(role: str) -> set:
    lines = (REPO_ROOT / ENV_TEMPLATES[role]).read_text(encoding="utf-8").splitlines()
    return {line.split("=", 1)[0] for line in lines if re.match(r"^[A-Z_][A-Z0-9_]*=", line)}


def _compose_variables(role: str):
    """(name, has_default) for every ${...} the compose file interpolates."""
    for match in _INTERPOLATION.finditer(_compose_text(role)):
        yield match.group(1), bool(match.group(2)) and match.group(2).lstrip(":").startswith("-")


@pytest.mark.parametrize("role_name", sorted(STACK_COMPOSE_FILES))
def test_every_variable_without_a_default_is_written_by_the_role(role_name):
    role = scenegems_roles()[role_name]
    needed = {name for name, has_default in _compose_variables(role_name) if not has_default}
    assert needed <= _role_keys(role)


@pytest.mark.parametrize("role_name", sorted(ENV_TEMPLATES))
def test_the_env_template_lists_every_key_the_role_writes_and_nothing_unknown(role_name):
    role = scenegems_roles()[role_name]
    template = _template_keys(role_name)
    assert _role_keys(role) <= template
    known = _role_keys(role) | {name for name, _ in _compose_variables(role_name)} | SECURITY_TOOL_OPTIONAL
    assert template <= known


@pytest.mark.parametrize("role_name", sorted(STACK_COMPOSE_FILES))
def test_ready_services_exist(role_name):
    services = _compose(role_name)["services"]
    ready = scenegems_roles()[role_name]["ready"]
    assert set(ready.get("healthy", [])) | set(ready.get("running", [])) <= set(services)
    for name in ready.get("healthy", []):
        assert "healthcheck" in services[name], name


def test_the_master_stack_has_the_security_tool_the_commands_run():
    services = _compose("master")["services"]
    assert services["security"]["profiles"] == ["tools"]
    role = scenegems_roles()["master"]
    for command in role["setup"] + [output["command"] for output in role["outputs"].values()]:
        assert command[command.index("run") + 1 :][:3] == ["--rm", "-T", "security"]


def test_postgres_is_the_same_image_everywhere():
    assert _compose("master")["services"]["postgres"]["image"] == POSTGRES_IMAGE
    build_script = (REPO_ROOT / "deploy" / "scripts" / "build.sh").read_text(encoding="utf-8")
    assert f'RELEASE_PULLED_IMAGES=("{POSTGRES_IMAGE}")' in build_script


def test_stacks_mount_no_checkout():
    for role_name in STACK_COMPOSE_FILES:
        for service in _compose(role_name)["services"].values():
            for volume in service.get("volumes", []):
                assert not str(volume).startswith(".."), volume


def _example_env(role_name: str) -> str:
    role = scenegems_roles()[role_name]
    values = {key: "value" for key in _role_keys(role)}
    values.update({key: parameter["default"] for key, parameter in role["parameters"].items()})
    values.update(
        {key: text.replace("{cluster}", "lab").replace("{name}", "worker-1").replace("{machine.vpn_ip}", "10.88.0.2").replace("{release.revision}", "abc") for key, text in role["env"].items()}
    )
    values.update({"SCENEGEMS_MASTER_ID": "lab", "SCENEGEMS_MASTER_CA_SHA256": "0" * 64, "SCENEGEMS_MASTER_URL": "https://10.88.0.2:8443"})
    return "".join(f"{key}={value}\n" for key, value in sorted(values.items()))


@pytest.mark.docker
@pytest.mark.parametrize("role_name", sorted(STACK_COMPOSE_FILES))
def test_docker_compose_accepts_the_stack_with_the_role_env(role_name, tmp_path):
    if shutil.which("docker") is None:
        pytest.skip("needs the docker CLI")
    shutil.copyfile(REPO_ROOT / STACK_COMPOSE_FILES[role_name], tmp_path / "docker-compose.yml")
    (tmp_path / ".env").write_text(_example_env(role_name), encoding="utf-8")
    (tmp_path / "release.json").write_text("{}", encoding="utf-8")
    completed = subprocess.run(["docker", "compose", "--profile", "tools", "config", "-q"], cwd=tmp_path, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_the_master_keeps_artifacts_on_their_own_volume():
    compose = _compose("master")
    service = compose["services"]["master-api"]
    folder = service["environment"]["SCENEGEMS_ARTIFACT_DIR"]
    assert f"artifacts:{folder}" in service["volumes"]
    assert compose["volumes"]["artifacts"]["name"] == "scenegems-${SCENEGEMS_MASTER_ID}-artifacts"
    for key in ("SCENEGEMS_ARTIFACT_MAX_BYTES", "SCENEGEMS_ARTIFACT_SWEEP_INTERVAL_S", "SCENEGEMS_ARTIFACT_SWEEP_GRACE_S"):
        assert service["environment"][key] == f"${{{key}:-{scenegems_roles()['master']['parameters'][key]['default']}}}"


def test_the_master_passes_the_allowed_origins_to_master_api_with_the_roles_default():
    service = _compose("master")["services"]["master-api"]
    default = scenegems_roles()["master"]["parameters"]["SCENEGEMS_OPERATOR_ALLOWED_ORIGINS"]["default"]
    assert service["environment"]["SCENEGEMS_OPERATOR_ALLOWED_ORIGINS"] == f"${{SCENEGEMS_OPERATOR_ALLOWED_ORIGINS:-{default}}}"
    assert f"SCENEGEMS_OPERATOR_ALLOWED_ORIGINS={default}" in (REPO_ROOT / ENV_TEMPLATES["master"]).read_text(encoding="utf-8").splitlines()


def test_the_node_passes_its_machine_on_and_lists_it_in_its_env_template():
    service = _compose("node")["services"]["node"]
    assert service["environment"]["SCENEGEMS_NODE_MACHINE"] == "${SCENEGEMS_NODE_MACHINE:-}"  # optional for a hand-written .env
    assert "SCENEGEMS_NODE_MACHINE" in _template_keys("node") and "SCENEGEMS_NODE_MACHINE" in scenegems_roles()["node"]["env"]


def test_the_node_caches_artifacts_in_its_state_volume():
    service = _compose("node")["services"]["node"]
    state = service["environment"]["SCENEGEMS_NODE_STATE_DIR"]
    assert f"state:{state}" in service["volumes"]
    assert service["environment"]["SCENEGEMS_NODE_ARTIFACT_CACHE_DIR"].startswith(state + "/")
    default = scenegems_roles()["node"]["parameters"]["SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES"]["default"]
    assert service["environment"]["SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES"] == f"${{SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES:-{default}}}"
