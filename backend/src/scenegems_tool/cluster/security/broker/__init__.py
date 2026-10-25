"""The master's cluster broker: who may connect and which topics each account may use.

    access_rules.py   topic scopes and the NanoMQ access rule file generated from them
    broker_config.py  the NanoMQ configuration: TLS listener, login hook, access rules
    auth_hook.py      the HTTP endpoint NanoMQ calls to check each login against the store

Logins are checked by the master on every CONNECT, and the access rules are static per
master (node accounts are covered by a `${username}` placeholder). So pairing a node
changes only the store, and the broker never needs a restart or a reload.
"""
