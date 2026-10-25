"""Measured entries: the shape of measured_capabilities.yaml, checked by the registry loader."""

import math

import pytest
import yaml

from scenegems_tool.vessel_stack.calibration.measured_entry import MeasuredEntry, evidence, host_label, merge_entries, render_yaml, write_yaml
from scenegems_tool.vessel_stack.registry.catalog import build_registry
from scenegems_tool.vessel_stack.registry.measured_capabilities import load_capability_measurements


def entry(spec_id="sitl_internal_physics", **fields) -> MeasuredEntry:
    return MeasuredEntry(spec_id, fields)


class TestValidation:
    def test_an_entry_the_loader_accepts(self):
        measurement = entry(repeatability_tier="bounded", max_speedup=20.0, deviation_bounds_m={1: 0.0, 5: 0.07}).parsed()
        assert dict(measurement.overrides) == {"repeatability_tier": measurement.overrides[0][1], "max_speedup": 20.0}
        assert measurement.deviation_bounds_m == ((1.0, 0.0), (5.0, 0.07))

    def test_an_unknown_field_is_rejected_like_the_registry_does(self):
        with pytest.raises(ValueError, match="unknown measured capability fields"):
            entry(max_speedupp=3).parsed()

    def test_an_invalid_value_is_rejected(self):
        with pytest.raises(ValueError):
            entry(repeatability_tier="approximately").parsed()

    def test_a_registered_spec_id_passes(self):
        entry("replay_mavlink_lockstep").check_registered()

    def test_an_unregistered_spec_id_is_rejected_with_the_known_ones(self):
        with pytest.raises(ValueError, match="No registered spec sitl_internal_physic; known ids: .*sitl_internal_physics"):
            entry("sitl_internal_physic").check_registered()

    def test_invalid_entries_do_not_merge(self):
        with pytest.raises(ValueError):
            merge_entries([entry(nonsense=1)])


class TestMerge:
    def test_one_entry_per_spec_in_first_seen_order(self):
        merged = merge_entries([entry("b", max_speedup=1.0), entry("a", max_speedup=2.0), entry("b", max_speedup=3.0)])
        assert [item.spec_id for item in merged] == ["b", "a"]

    def test_deviation_bounds_keep_the_largest_per_speedup(self):
        merged = merge_entries([entry(deviation_bounds_m={1: 0.1, 5: 0.5}), entry(deviation_bounds_m={5: 0.3, 20: 2.0})])
        assert merged[0].fields["deviation_bounds_m"] == {1: 0.1, 5: 0.5, 20: 2.0}

    def test_layer_bounds_merge_per_layer_and_speedup(self):
        first = entry("replay_mavlink_lockstep", deviation_bounds_m_by_layer={"simulation_layer/gazebo": {1: 0.2}})
        second = entry("replay_mavlink_lockstep", deviation_bounds_m_by_layer={"simulation_layer/gazebo": {1: 0.1, 2: 0.4}, "simulation_layer/ardupilot_sim": {1: 0.0}})
        bounds = merge_entries([first, second])[0].fields["deviation_bounds_m_by_layer"]
        assert bounds == {"simulation_layer/gazebo": {1: 0.2, 2: 0.4}, "simulation_layer/ardupilot_sim": {1: 0.0}}

    def test_the_weaker_tier_wins(self):
        assert merge_entries([entry(repeatability_tier="exact"), entry(repeatability_tier="bounded")])[0].fields["repeatability_tier"] == "bounded"
        assert merge_entries([entry(repeatability_tier="none"), entry(repeatability_tier="exact")])[0].fields["repeatability_tier"] == "none"

    def test_a_speed_limit_is_the_highest_speedup_that_tracked(self):
        merged = merge_entries([entry(max_speedup=1.0), entry(max_speedup=20.0), entry(max_speedup=5.0)])
        assert merged[0].fields["max_speedup"] == 20.0

    def test_host_limits_keep_the_highest_per_host(self):
        merged = merge_entries([entry(host_max_speedup={"a": 2.0}), entry(host_max_speedup={"a": 4.0, "b": 1.0})])
        assert merged[0].fields["host_max_speedup"] == {"a": 4.0, "b": 1.0}

    def test_the_exact_range_keeps_the_lowest_bound(self):
        assert merge_entries([entry(exact_up_to_speedup=5.0), entry(exact_up_to_speedup=1.0)])[0].fields["exact_up_to_speedup"] == 1.0

    def test_evidence_is_concatenated_and_notes_merged(self):
        merged = merge_entries([entry(evidence="first.", notes={"wind": "a"}), entry(evidence="second.", notes={"waves": "b"})])
        assert merged[0].fields["evidence"] == "first. second."
        assert merged[0].fields["notes"] == {"wind": "a", "waves": "b"}

    def test_merging_does_not_change_the_inputs(self):
        first = entry(deviation_bounds_m={1: 0.1})
        merge_entries([first, entry(deviation_bounds_m={1: 0.9})])
        assert first.fields["deviation_bounds_m"] == {1: 0.1}


class TestRender:
    def test_yaml_has_one_key_per_spec_id(self):
        data = yaml.safe_load(render_yaml([entry("sitl_internal_physics", max_speedup=20.0), entry("kinematic_command_input", repeatability_tier="exact")]))
        assert list(data) == ["sitl_internal_physics", "kinematic_command_input"]

    def test_infinity_is_written_as_the_yaml_literal(self):
        text = render_yaml([entry("kinematic_command_input", max_speedup=math.inf)])
        assert "max_speedup: .inf" in text
        assert math.isinf(load_text(text)["kinematic_command_input"].overrides[0][1])

    def test_numbers_are_rounded_and_plain(self):
        import numpy as np

        text = render_yaml([entry(deviation_bounds_m={np.float64(5.0): np.float64(0.07736512345)})])
        assert "0.077365" in text
        assert "!!" not in text and "numpy" not in text

    def test_header_becomes_comments(self):
        text = render_yaml([entry(max_speedup=1.0)], "first line\n\nsecond line")
        assert text.startswith("# first line\n#\n# second line\n")

    def test_rendered_entries_build_a_registry(self, tmp_path):
        text = render_yaml(
            [
                entry("kinematic_command_input", repeatability_tier="exact", max_speedup=math.inf),
                entry("replay_mavlink_lockstep", deviation_bounds_m_by_layer={"simulation_layer/ardupilot_sim": {5: 0.077}}, max_speedup=20.0, evidence="measured."),
                entry("ardupilot_gazebo_plugin", host_max_speedup={"bench": 2.0}),
            ]
        )
        path = tmp_path / "measured.yaml"
        path.write_text(text, encoding="utf-8")
        registry = build_registry(load_capability_measurements(str(path)))
        assert registry.adapter("replay_mavlink_lockstep").capabilities.max_speedup == 20.0
        assert registry.measurement("ardupilot_gazebo_plugin").max_speedup_on("bench") == 2.0

    def test_write_yaml_checks_and_writes_the_file(self, tmp_path):
        path = tmp_path / "out.yaml"
        text = write_yaml(str(path), [entry(max_speedup=3.0)], "header")
        assert path.read_text(encoding="utf-8") == text
        assert "sitl_internal_physics" in text

    def test_write_yaml_refuses_a_bad_entry_without_writing(self, tmp_path):
        path = tmp_path / "out.yaml"
        with pytest.raises(ValueError):
            write_yaml(str(path), [entry(nonsense=1)])
        assert not path.exists()


class TestEvidence:
    def test_names_the_date_host_and_details(self):
        text = evidence("a run", speedup="5x", repeats=3)
        assert text.startswith("Calibration 20")
        assert host_label() in text
        assert text.endswith("a run (speedup 5x, repeats 3).")

    def test_without_details(self):
        assert evidence("a run").endswith("a run.")


def load_text(text):
    import yaml as _yaml

    from scenegems_tool.vessel_stack.registry.measured_capabilities import parse_capability_measurement

    return {spec_id: parse_capability_measurement(spec_id, fields) for spec_id, fields in _yaml.safe_load(text).items()}
