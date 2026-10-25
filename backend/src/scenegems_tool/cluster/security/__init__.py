"""Security of one master's cluster: its certificate authority, credentials and broker access.

A master is created once (`initialize_master_security`), which makes its certificate
authority, the server certificates of its API and broker, the master's broker account
and the broker configuration. Pairing then turns a one-time token into a node's
credential and broker account. Only hashes of secrets are stored.

    master_security.py      MasterSecurity: the security folder of a master, init and load
    security_layout.py      where each file lives in that folder
    pairing.py              pair_node: one-time token to PairingResponse (the REST route calls it)
    command_line.py         `python -m scenegems_tool.cluster.security`: init, pairing tokens, revoke
    scope_names.py          the naming rule for master ids, node ids and broker usernames
    file_writing.py         atomic, owner-only writes into the security folder
    certificates/           the master's certificate authority and server certificates
    credentials/            secret hashing, pairing tokens, node credentials, broker accounts
    broker/                 broker access rules, broker configuration, the broker's auth hook
    store/                  the state interface and its file implementation
"""
