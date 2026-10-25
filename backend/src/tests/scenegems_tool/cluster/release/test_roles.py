import re

from scenegems_tool.cluster.fingerprints.job_images import GAZEBO_IMAGE, JOB_TYPE_IMAGES
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.release.roles import NAME_PATTERN, NODE_IMAGE, POSTGRES_IMAGE, capability_item_images, role_images, scenegems_roles

FIELDS = {"description", "count", "stack", "project", "images", "env", "parameters", "secrets", "setup", "outputs", "ready"}
PLACEHOLDERS = {"cluster", "name", "machine.vpn_ip", "machine.name", "release.revision", "dependent.name"}


def _texts(role):
    yield role["project"]
    yield from role["env"].values()
    yield from (parameter["default"] for parameter in role["parameters"].values())
    for command in role["setup"]:
        yield from command
    for output in role["outputs"].values():
        yield from output["command"]


def test_every_role_has_the_contract_fields():
    for name, role in scenegems_roles().items():
        assert FIELDS <= set(role), name
        assert role["count"] in ("one", "many")


def test_placeholders_are_the_documented_ones():
    for role in scenegems_roles().values():
        for text in _texts(role):
            assert set(re.findall(r"\{([^{}]+)\}", text)) <= PLACEHOLDERS, text


def test_secrets_parameters_and_fixed_values_do_not_overlap():
    for role in scenegems_roles().values():
        env, parameters, secrets = set(role["env"]), set(role["parameters"]), set(role["secrets"])
        required = set(role.get("requires", {}).get("keys", []))
        groups = [env, parameters, secrets, required]
        assert sum(len(group) for group in groups) == len(set().union(*groups))


def test_the_node_requires_an_output_the_master_has():
    roles = scenegems_roles()
    requires = roles["node"]["requires"]
    assert requires["output"] in roles[requires["role"]]["outputs"]
    assert roles[requires["role"]]["count"] == "one"


def test_capability_items_cover_every_job_type_and_ardupilot_gets_gazebo():
    images = capability_item_images()
    assert set(images) == {job_type.value for job_type in JobType}
    for job_type in JobType:
        assert set(JOB_TYPE_IMAGES[job_type]) <= set(images[job_type.value])
    assert GAZEBO_IMAGE in images[JobType.SIMULATION_ARDUPILOT.value]


def test_role_images_include_every_image_a_role_may_need():
    images = role_images(scenegems_roles())
    assert NODE_IMAGE in images and POSTGRES_IMAGE in images and GAZEBO_IMAGE in images
    assert images == sorted(set(images))


def test_the_default_capabilities_name_known_job_types():
    capabilities = scenegems_roles()["node"]["parameters"]["SCENEGEMS_NODE_CAPABILITIES"]
    items = [item.split(":")[0] for item in capabilities["default"].split(",")]
    assert set(items) <= set(capabilities["items"]["images"])


def test_cluster_ids_and_names_are_single_scope_names():
    pattern = re.compile(NAME_PATTERN)
    assert pattern.fullmatch("master-1") and pattern.fullmatch("worker-2")
    assert not pattern.fullmatch("Master_1") and not pattern.fullmatch("a/b")
