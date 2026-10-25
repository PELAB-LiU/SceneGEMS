"""Calibration command line: measure a stack combination and write measured_capabilities.yaml entries.

Run from backend/ with PYTHONPATH=src. Every subcommand prints a summary, and --out writes the entries in the
shape of src/scenegems_tool/vessel_stack/registry/measured_capabilities.yaml to a file of its own. Review the entries
and merge them into the shipped file by hand; nothing here edits it.

    python -m scripts.calibrate kinematic --mode usv_navigation --out kinematic.yaml
    python -m scripts.calibrate monitor --timespan 600
    python -m scripts.calibrate stack --layer ardupilot_sim --drive replay --speedups 1 5 20 --repeats 3 --out sitl.yaml
    python -m scripts.calibrate stack --layer gazebo --drive target --speedups 1 2 --repeats 2 --out gazebo.yaml

The stack subcommand needs Docker and the SITL and Gazebo images. The others run in process.
The library is scenegems_tool/vessel_stack/calibration/, which explains each measurement.
"""

import argparse
import json
import sys
import tempfile
from typing import List, Optional, Sequence

from scenegems_tool.vessel_stack.calibration.kinematic_measurement import DEFAULT_HASH_SEEDS, measure_kinematic
from scenegems_tool.vessel_stack.calibration.measured_entry import MeasuredEntry, render_yaml, write_yaml
from scenegems_tool.vessel_stack.calibration.monitor_measurement import DEFAULT_CONSTANTS_FILE, measure_monitor
from scenegems_tool.vessel_stack.calibration.reference_scenarios import ENCOUNTER_TARGETS, REFERENCE_RUNS, VESSEL_SCALES
from scenegems_tool.vessel_stack.calibration.sitl_stack_runs import BASE_HOST_PORT, LAYERS, StackMeasurement, StackRunSpec, measure_stack

HEADER = "Measured by scripts/calibrate.py. Review the entries and merge them into registry/measured_capabilities.yaml."


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", help="write the measured_capabilities.yaml entries to this file")
    parser.add_argument("--report", help="write the measurements as JSON to this file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="calibrate", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    kinematic = commands.add_parser("kinematic", help="reproducibility and pace of the kinematic layer")
    kinematic.add_argument("--mode", choices=["replay", "usv_navigation", "both"], default="both")
    kinematic.add_argument("--encounter", choices=sorted(ENCOUNTER_TARGETS), default="crossing_from_starboard")
    kinematic.add_argument("--timespan", type=int, default=600, help="simulated seconds, one step each")
    kinematic.add_argument("--repeats", type=int, default=3)
    kinematic.add_argument("--hash-seeds", nargs="*", default=list(DEFAULT_HASH_SEEDS), help="PYTHONHASHSEED values of the fresh processes; none skips them")
    _add_common(kinematic)

    monitor = commands.add_parser("monitor", help="throughput and reproducibility of the COLREGS monitor")
    monitor.add_argument("--encounter", choices=sorted(ENCOUNTER_TARGETS), default="head_on")
    monitor.add_argument("--timespan", type=int, default=600)
    monitor.add_argument("--repeats", type=int, default=2)
    monitor.add_argument("--constants", default=DEFAULT_CONSTANTS_FILE)
    monitor.add_argument("--hash-seeds", nargs="*", default=["0", "1", "4242"])
    _add_common(monitor)

    stack = commands.add_parser("stack", help="repeat envelope and pace of ArduPilot Sim or Gazebo in Docker")
    stack.add_argument("--layer", choices=sorted(LAYERS), required=True)
    stack.add_argument("--drive", choices=["replay", "target"], default="replay")
    stack.add_argument("--reference", choices=list(REFERENCE_RUNS), nargs="+", default=["straight"])
    stack.add_argument("--scale", choices=sorted(VESSEL_SCALES), default="5m")
    stack.add_argument("--duration", type=int, default=90, help="simulated seconds")
    stack.add_argument("--speedups", type=int, nargs="+", default=[1])
    stack.add_argument("--repeats", type=int, default=3)
    stack.add_argument("--wind", type=float, nargs=2, metavar=("EAST", "NORTH"), help="wind in m/s")
    stack.add_argument("--work-folder", help="where the generated stacks go (default: a temporary folder)")
    stack.add_argument("--base-port", type=int, default=BASE_HOST_PORT, help="first host port for the SITL serial ports")
    stack.add_argument("--repo-entrypoints", action="store_true", help="mount the repo's entrypoint scripts over the image copies")
    stack.add_argument("--keep-stacks", action="store_true", help="leave the containers running")
    _add_common(stack)
    return parser


def _kinematic(args: argparse.Namespace):
    modes = ["replay", "usv_navigation"] if args.mode == "both" else [args.mode]
    measurements = [measure_kinematic(mode, args.encounter, args.timespan, args.repeats, args.hash_seeds) for mode in modes]
    for measurement in measurements:
        print(f"{measurement.mode}: reproducible={measurement.reproducible} {measurement.steps_per_second:,.0f} steps/s ({measurement.speed_relative_to_real_time:,.0f}x real time)")
    return [measurement.entry() for measurement in measurements], [vars(measurement) for measurement in measurements]


def _monitor(args: argparse.Namespace):
    measurement = measure_monitor(args.encounter, args.timespan, args.repeats, args.constants, args.hash_seeds)
    data = measurement.as_dict()
    print(f"monitor: {data['scenes_per_second']:,.0f} scenes/s; reproducible in process: {data['reproducible_in_process']}; across processes: {data['reproducible_across_processes']}")
    return [], [data]


def _print_stack(measurement: StackMeasurement) -> None:
    spec = measurement.spec
    deviation = f"{measurement.deviation.max_m:.3f} m ({measurement.deviation.alignment})" if measurement.deviation else "n/a"
    achieved = f"{measurement.achieved:.2f}x" if measurement.achieved else "n/a"
    failed = [repeat for repeat in measurement.repeats if not repeat.ok]
    print(f"{spec.label()}: {len(measurement.ok_repeats)}/{len(measurement.repeats)} repeats, achieved {achieved}, repeat deviation {deviation}")
    for repeat in failed:
        print(f"  repeat {repeat.index} failed: {repeat.error}\n{repeat.logs}")


def _stack(args: argparse.Namespace):
    work_folder = args.work_folder or tempfile.mkdtemp(prefix="scenegems-calibration-")
    entries: List[MeasuredEntry] = []
    reports = []
    for reference in args.reference:
        for speedup in args.speedups:
            spec = StackRunSpec(LAYERS[args.layer], reference, args.scale, args.duration, speedup, args.repeats, args.drive, tuple(args.wind) if args.wind else None)
            measurement = measure_stack(spec, work_folder, args.base_port, args.repo_entrypoints, args.keep_stacks)
            _print_stack(measurement)
            entries.extend(measurement.entries())
            reports.append(
                {
                    "label": spec.label(),
                    "achieved_speedup": measurement.achieved,
                    "deviation": vars(measurement.deviation) if measurement.deviation else None,
                    "repeats": [{"ok": repeat.ok, "error": repeat.error, "achieved_speedup": repeat.achieved_speedup, "state_digest": repeat.state_digest} for repeat in measurement.repeats],
                }
            )
    return entries, reports


COMMANDS = {"kinematic": _kinematic, "monitor": _monitor, "stack": _stack}


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    entries, reports = COMMANDS[args.command](args)
    if args.out and entries:
        write_yaml(args.out, entries, HEADER)
        print(f"wrote {len(entries)} measured entries to {args.out}")
    elif entries:
        print(render_yaml(entries, HEADER))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as file:
            json.dump(reports, file, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
