"""The architecture document model: validation of references and the plain-data conversion."""

import json

import pytest

from scenegems_tool.architecture.architecture_model import (
    UNBOUNDED,
    ArchitectureDocument,
    ArchitectureEdge,
    ArchitectureNode,
    Combination,
    Fact,
    Lane,
    MetamodelEdge,
    MetamodelNode,
    UnsupportedLink,
    to_plain,
)


def document(**changes) -> ArchitectureDocument:
    values = dict(
        id="doc",
        title="Doc",
        summary="s",
        lanes=(Lane("top", "Top", ""), Lane("bottom", "Bottom", "")),
        metamodel_nodes=(MetamodelNode("m/top", "top", "Top", ""), MetamodelNode("m/bottom", "bottom", "Bottom", "")),
        metamodel_edges=(MetamodelEdge("m/link", "m/top", "m/bottom", "link", ""),),
        nodes=(ArchitectureNode("a", "top", "A", "", "m/top"), ArchitectureNode("b", "bottom", "B", "", "m/bottom")),
        edges=(ArchitectureEdge("a__b", "a", "b", "link", "", "m/link"),),
    )
    values.update(changes)
    return ArchitectureDocument(**values)


def test_a_consistent_document_validates():
    assert document().validate().id == "doc"


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"nodes": (ArchitectureNode("a", "nowhere", "A", ""),)}, "unknown lane nowhere"),
        ({"nodes": (ArchitectureNode("a", "top", "A", "", "m/missing"),)}, "implements unknown m/missing"),
        ({"edges": (ArchitectureEdge("a__x", "a", "x", "link", ""),)}, "joins unknown nodes"),
        ({"edges": (ArchitectureEdge("a__b", "a", "b", "link", "", "m/missing"),)}, "implements unknown m/missing"),
        ({"metamodel_edges": (MetamodelEdge("m/link", "m/top", "m/gone", "link", ""),)}, "metamodel edge m/link joins unknown nodes"),
        ({"unsupported": (UnsupportedLink("a", "gone", "why"),)}, "unsupported link a to gone"),
        ({"combinations": (Combination(("a", "gone"), "available"),)}, "names an unknown node"),
        ({"lanes": (Lane("top", "Top", ""), Lane("top", "Again", ""))}, "duplicate lane ids: top"),
        ({"nodes": (ArchitectureNode("a", "top", "A", ""), ArchitectureNode("a", "bottom", "A2", ""))}, "duplicate node ids: a"),
    ],
)
def test_a_dangling_reference_or_duplicate_fails(changes, message):
    with pytest.raises(ValueError, match=message):
        document(**changes).validate()


def test_the_plain_form_is_json_and_turns_infinity_into_unbounded():
    node = ArchitectureNode("a", "top", "A", "", facts=(Fact("max_speedup", "Max speedup", float("inf")), Fact("floor", "Floor", float("-inf"))), tags=("x",))
    plain = to_plain(document(nodes=(node, ArchitectureNode("b", "bottom", "B", "")), edges=()))
    facts = plain["nodes"][0]["facts"]
    assert [fact["value"] for fact in facts] == [UNBOUNDED, "-" + UNBOUNDED]
    assert plain["nodes"][0]["tags"] == ["x"]
    assert json.loads(json.dumps(plain)) == plain
