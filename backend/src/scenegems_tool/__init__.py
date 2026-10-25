"""
SceneGEMS tool: the runtime that executes assurance workflows.

The package tree is a map. Depth follows concreteness: a package at depth 1 names an
abstract concept of the architecture, and each level below it is a more concrete concept.
See system_revision/architecture_design.md for the full design.

Present now:
    gateway/        browser WebSocket API: app, protocol, serialization, per-connection sessions
    workbench/      single-machine demo orchestration kept working through the revision
    messaging/      MQTT clients and services that carry subsystem traffic
    subsystems/     one package per subsystem
        scene_generation/, trajectory_generation/, monitoring/, scenario_execution/
    vessel_stack/   ASV software, control layer and simulation layer as adapters
        contracts/              roles, ports, capabilities, adapter specs, clock, stack config
        registry/               adapter registry, resolver, measured capability data
        simulation_layers/      kinematic/ (in process), gazebo/ (generators), ardupilot_sim/
        control_layers/         ardupilot/, later custom/
        asv_software/           replay/, usv_navigation/ (in process), mission_planner/ (specs)
    cluster/        distributed integration layer
        protocol/               typed, versioned master-node messages, jobs and pairing
        security/               master CA, pairing tokens, node credentials, broker accounts and access rules
        node/                   instance scopes, launchers and job types; later the node daemon
        fingerprints/           image build fingerprints: label reader, expected set, comparison
        master/                 node registry, scheduler, lease manager and the master's API and process
    persistence/    the master's Postgres: tables, migrations, node and job stores

Planned (added by later phases):
    assurance/      campaign configuration and the per-scenario pipeline
    persistence/    artifact store, campaign tables
    vessel_stack/adapters/      shared edges between layers (mavlink, gz_transport)
"""

__all__: list[str] = []
