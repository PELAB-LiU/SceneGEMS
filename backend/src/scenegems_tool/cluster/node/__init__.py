"""The node integration layer: everything that runs subsystem instances on one machine.

    instance_scope.py   instance identity and the names derived from it (topics, containers, projects)
    subsystem.py        the subsystems and their images
    node_context.py     what a job needs from its node: identity, slots, broker, pools
    job_report.py       status and log lines of a running job, and its failure
    launchers/          start and stop subsystem containers, shared with the workbench
    jobs/               one module per job type and run_job, the daemon's entry point
    docker_subsystem_shutdown.py   removes the workbench's containers at backend exit

The node daemon (P3.4) adds the connection to the master on top of jobs/.
"""
