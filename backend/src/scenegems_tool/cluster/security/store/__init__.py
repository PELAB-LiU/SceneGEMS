"""Where the master keeps its security state: pairing tokens, node credentials, broker accounts.

    security_store.py        the records and the SecurityStore interface
    file_security_store.py   one JSON file per record under the master's security folder

Only hashes of secrets are stored. P3.3 can replace the file store with Postgres tables
behind the same interface.
"""
