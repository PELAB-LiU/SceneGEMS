"""The calibration command line: arguments, and the in-process subcommands end to end."""

import json

import pytest
import yaml

from scenegems_tool.vessel_stack.registry.measured_capabilities import parse_capability_measurement
from scripts import calibrate


def test_a_subcommand_is_required():
    with pytest.raises(SystemExit):
        calibrate.build_parser().parse_args([])


def test_stack_needs_a_layer():
    with pytest.raises(SystemExit):
        calibrate.build_parser().parse_args(["stack"])


def test_stack_arguments():
    args = calibrate.build_parser().parse_args(["stack", "--layer", "gazebo", "--drive", "target", "--speedups", "1", "2", "--reference", "straight", "turning", "--wind", "0", "5"])
    assert (args.layer, args.drive, args.speedups, args.reference, args.wind) == ("gazebo", "target", [1, 2], ["straight", "turning"], [0.0, 5.0])
    assert args.repeats == 3 and args.duration == 90


def test_unknown_layer_is_rejected():
    with pytest.raises(SystemExit):
        calibrate.build_parser().parse_args(["stack", "--layer", "kinematic"])


def test_kinematic_writes_checked_entries_and_a_report(tmp_path, capsys):
    out, report = tmp_path / "kinematic.yaml", tmp_path / "report.json"
    code = calibrate.main(["kinematic", "--mode", "both", "--encounter", "head_on", "--timespan", "60", "--repeats", "2", "--hash-seeds", "--out", str(out), "--report", str(report)])
    assert code == 0
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert set(data) == {"kinematic_command_input", "usv_navigation_in_process"}
    for spec_id, fields in data.items():
        parse_capability_measurement(spec_id, fields)
        assert fields["repeatability_tier"] == "exact"
    assert "wrote 2 measured entries" in capsys.readouterr().out
    assert [item["mode"] for item in json.loads(report.read_text(encoding="utf-8"))] == ["replay", "usv_navigation"]


def test_without_out_the_entries_are_printed(capsys):
    calibrate.main(["kinematic", "--mode", "replay", "--timespan", "30", "--repeats", "1", "--hash-seeds"])
    output = capsys.readouterr().out
    assert "kinematic_command_input:" in output


def test_monitor_reports_without_entries(tmp_path, capsys):
    out = tmp_path / "unused.yaml"
    assert calibrate.main(["monitor", "--timespan", "30", "--repeats", "1", "--hash-seeds", "--out", str(out)]) == 0
    assert not out.exists(), "the monitor is not a stack spec, so it produces no measured_capabilities entry"
    assert "monitor:" in capsys.readouterr().out


def test_the_shipped_measured_capabilities_file_is_never_the_default_output():
    assert calibrate.build_parser().parse_args(["kinematic"]).out is None
