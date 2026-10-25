"""Pairing: trust the master only through the pinned CA hash, exchange the token once, keep the result.

ca_pinning.py       fetch the CA unverified, compare its SHA-256 with the pin, verified TLS contexts
pairing_client.py   the PairingRequest over verified HTTPS
pairing_state.py    the stored PairingResponse and the CA files in the state and trust folders
node_pairing.py     pair on first start, reuse the stored pairing afterwards
"""
