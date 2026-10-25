"""Calibration: the measurement tool behind measured_capabilities.yaml (design doc sections 3.4 and 12.5.2).

A measurement repeats a reference scenario on one stack combination K times and turns the
result into numbers the resolver can use: the repeatability tier, the largest deviation
between repeats at each speedup, the speedup the stack really reached, and the throughput of
the in-process parts. The command line is `backend/src/scripts/calibrate.py`; this package is
the library, so the same measurements can become a campaign job type later.

    reference_scenarios.py     the vessels and trajectories every measurement runs (straight, turning, encounters)
    repeat_analysis.py         deviation between repeats, pace, onset alignment: pure functions on sampled tracks
    kinematic_measurement.py   kinematic layer: digests across repeats and processes, and steps per second
    monitor_measurement.py     COLREGS monitor: scenes per second and whether its output is reproducible
    sitl_stack_runs.py         ArduPilot Sim and Gazebo in Docker: generated stacks, repeats, tracks (needs Docker)
    measured_entry.py          results in the shape of measured_capabilities.yaml, checked by the registry loader

Nothing here edits measured_capabilities.yaml. A run writes its own YAML file with the same
shape; the entries are reviewed and merged into the shipped file by hand, so a noisy run
never replaces a measurement silently.
"""
