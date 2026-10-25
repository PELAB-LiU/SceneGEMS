import json

import pytest

from scenegems_tool.cluster.security.broker.access_rules import AccessRule, cluster_access_rules, master_topic_scope, node_topic_scope, render_access_rules
from scenegems_tool.cluster.security.scope_names import InvalidScopeName


def test_topic_scopes_follow_the_cluster_contract():
    assert master_topic_scope("lab-master") == "scenegems/lab-master"
    assert node_topic_scope("lab-master", "lab-1-a1b2c3") == "scenegems/lab-master/lab-1-a1b2c3"


@pytest.mark.parametrize("node_id", ["+", "#", "a/b", "", "Lab"])
def test_scopes_refuse_wildcards_and_separators(node_id):
    with pytest.raises(InvalidScopeName):
        node_topic_scope("lab-master", node_id)


def test_master_gets_the_whole_master_tree_nodes_their_own_scope_and_the_rest_is_denied():
    master_rule, node_rule, deny_rule = cluster_access_rules("lab-master", "master")
    assert master_rule == AccessRule(permit="allow", username="master", action="pubsub", topics=("scenegems/lab-master/#",))
    assert node_rule == AccessRule(permit="allow", action="pubsub", topics=("scenegems/lab-master/${username}/#",))
    assert deny_rule == AccessRule(permit="deny")


def test_rendered_rules_are_nanomq_entries_in_order():
    text = render_access_rules(cluster_access_rules("lab-master", "master"))
    lines = text.splitlines()
    assert lines[1] == "rules = [" and lines[-1] == "]"
    entries = [json.loads(line) for line in lines[2:-1]]
    assert entries == [
        {"permit": "allow", "username": "master", "action": "pubsub", "topics": ["scenegems/lab-master/#"]},
        {"permit": "allow", "action": "pubsub", "topics": ["scenegems/lab-master/${username}/#"]},
        {"permit": "deny"},
    ]


def test_rules_do_not_depend_on_paired_nodes():
    # Pairing must never require new broker rules: the rules are a function of the master only.
    assert render_access_rules(cluster_access_rules("lab-master", "master")) == render_access_rules(cluster_access_rules("lab-master", "master"))
    assert "lab-1" not in render_access_rules(cluster_access_rules("lab-master", "master"))
