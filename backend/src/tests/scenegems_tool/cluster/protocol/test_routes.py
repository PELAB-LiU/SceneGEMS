from scenegems_tool.cluster.protocol.routes import ARTIFACTS_PATH, JOBS_PATH, NODE_CONTROL_PATH, NODE_ID_HEADER


def test_paths_are_distinct_and_under_cluster():
    paths = [NODE_CONTROL_PATH, JOBS_PATH, ARTIFACTS_PATH]
    assert len(set(paths)) == len(paths)
    assert all(path.startswith("/cluster/") for path in paths)


def test_the_node_names_itself_in_a_plain_header():
    assert NODE_ID_HEADER == "X-Node-Id"  # the artifact routes' only identification: master and nodes trust the VPN
