"""Typed, versioned messages between the master and its nodes.

Both sides import these definitions, so master and node cannot drift apart silently.

    version.py           PROTOCOL_VERSION and the mismatch error
    model_base.py        immutable models; frames carry the protocol version
    jobs.py              job types, states, requirements, submission and the leased job
    node_description.py  capability offers with slots, resources
    messages.py          WebSocket frames, node to master and master to node
    pairing.py           REST pairing: one-time token to node and broker credentials
    codec.py             encode and decode frames, version checked first
    routes.py            HTTP paths and the bearer header of the master's cluster API
"""
