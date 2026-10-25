"""Secrets the master hands out and checks: pairing tokens, node credentials, broker accounts.

secret_hashing.py     new secrets, salted scrypt hashes and the token lookup key
pairing_tokens.py     one-time pairing tokens: create, expire, consume once
node_credentials.py   the node's bearer credential for the API and control WebSocket
broker_accounts.py    accounts on the master's broker and their login check
"""
