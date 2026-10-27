"""The master integration layer's control plane: it knows the nodes, leases them jobs and serves the master's API.

Nodes connect to the master (outbound only) over one authenticated WebSocket each; the
master offers them queued jobs from its Postgres job store and keeps each lease alive
while the node renews it. State is in the database (persistence/), so a master restart
loses only what the nodes resend on reconnect.

    timing.py           heartbeat, lease, offer and sweep periods, and why they are what they are
    control_plane.py    registry, scheduler and lease manager wired on one event loop, with timers
    job_activity.py     latest status and log lines of running jobs, in memory
    registry/           connected nodes and their status
        node_session.py           one connected node: socket, latest facts, leases it holds
        node_registry.py          sessions, heartbeats, drain, silent nodes offline
        lease_reconciliation.py   a reconnected node's running leases against the store's
    scheduling/         which node gets which job
        scheduler.py              round robin offers to eligible nodes through the store's claim
        node_eligibility.py       online, up to date, resource guard
        fingerprint_policy.py     the master's expected fingerprints, required of jobs and nodes
        reject_backoff.py         a node that rejects a job does not get it again for a while
    leases/
        lease_manager.py          accept, renew, reject, release, result, expiry sweep, reconnect
    control_link/
        node_control_socket.py    the node's WebSocket: Hello, frame loop
    api/                the HTTP side, one app per listener
        master_apps.py            node API (plain HTTP), operator (workbench and jobs)
        node_routes.py            control WebSocket
        operator_routes.py        jobs and nodes
        views.py                  JSON views of jobs and nodes
    settings.py         environment settings of the master process
    server.py           the master process: two listeners in one event loop (`python -m scenegems_tool.cluster.master`)
"""
