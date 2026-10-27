"""The subsystem specs' shared parts: the measured facts file and the coverage check."""

import pytest

from scenegems_tool.architecture.architecture_model import GROUP_CAPABILITY
from scenegems_tool.subsystems.subsystem_spec import check_covers_enum, default_measured_facts, load_measured_facts, parse_measured_facts
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import TrajectoryGeneratorId


def test_the_measured_file_loads_and_every_fact_is_marked_measured():
    measurements = default_measured_facts()
    assert {"monitoring/colregs_monitor", "monitoring/mqtt_service"} <= set(measurements)
    for entry in measurements.values():
        assert entry.evidence and entry.facts
        assert all(fact.measured and fact.group == GROUP_CAPABILITY for fact in entry.facts)


def test_a_fact_needs_a_key_a_label_and_a_value_and_takes_no_other_field():
    with pytest.raises(ValueError, match="needs key, label and value"):
        parse_measured_facts("x", {"facts": [{"key": "k", "value": 1}]})
    with pytest.raises(ValueError, match="needs key, label and value"):
        parse_measured_facts("x", {"facts": [{"key": "k", "label": "K", "value": 1, "extra": 2}]})
    with pytest.raises(ValueError, match="unknown measured fields"):
        parse_measured_facts("x", {"fact": []})


def test_a_missing_file_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_measured_facts(str(tmp_path / "none.yaml"))


def test_the_coverage_check_names_a_missing_and_a_surplus_spec():
    everything = [member.value for member in TrajectoryGeneratorId]
    check_covers_enum(TrajectoryGeneratorId, everything, "t")
    with pytest.raises(ValueError, match="no architecture spec for straight"):
        check_covers_enum(TrajectoryGeneratorId, everything[:1], "t")
    with pytest.raises(ValueError, match="spec for phantom, which TrajectoryGeneratorId does not define"):
        check_covers_enum(TrajectoryGeneratorId, [*everything, "phantom"], "t")
