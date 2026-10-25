"""The pinned hash of the master's CA certificate, which a new node checks before trusting it.

The token command prints the hash next to the pairing token (SCENEGEMS_MASTER_CA_SHA256). The
node fetches the CA certificate over an unverified connection, compares its hash with the
pinned value, and only then uses it as its trust anchor. Master and node call the same
function, so both hash the same bytes: the certificate's DER encoding, not its PEM text,
whose line breaks and headers may differ. Standard library only, so the node needs no
cryptography package for it.
"""

import hashlib
import hmac
import ssl
from typing import Union


def certificate_sha256(pem: Union[str, bytes]) -> str:
    """SHA-256 of the DER bytes of a PEM certificate, as lowercase hex."""
    text = pem.decode("ascii") if isinstance(pem, bytes) else pem
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(text.strip())).hexdigest()


def normalize_sha256(value: str) -> str:
    """A pinned hash as lowercase hex; upper case and ':' separators (as openssl prints them) are accepted."""
    return value.strip().replace(":", "").lower()


def matches_pinned_sha256(pem: Union[str, bytes], expected: str) -> bool:
    """True when the certificate's hash equals the pinned value."""
    expected = normalize_sha256(expected)
    if len(expected) != 64:
        return False
    return hmac.compare_digest(certificate_sha256(pem), expected)
