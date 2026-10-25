"""Trust on first contact, pinned: the master's CA is accepted only if its hash matches.

Before pairing the node trusts nothing. It fetches the CA certificate from the master
without verifying the server, compares the SHA-256 of the certificate's DER bytes with
SCENEGEMS_MASTER_CA_SHA256 (printed by the master's token command) and refuses on any
difference. Every later connection, HTTPS and WebSocket, is verified against that CA.
"""

import hashlib
import re
import ssl
import urllib.request

from scenegems_tool.cluster.protocol.routes import CA_CERTIFICATE_PATH

FETCH_TIMEOUT_S = 15.0
_PEM_CERTIFICATE = re.compile(r"-----BEGIN CERTIFICATE-----\s+.*?\s+-----END CERTIFICATE-----", re.DOTALL)


class CaPinMismatch(RuntimeError):
    """The master's CA certificate is not the one the node was told to trust."""


def certificate_sha256(certificate_pem: str) -> str:
    """SHA-256 of a PEM certificate's DER bytes, lowercase hex: the value of SCENEGEMS_MASTER_CA_SHA256."""
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(single_certificate(certificate_pem))).hexdigest()


def single_certificate(certificate_pem: str) -> str:
    """The one certificate in a PEM text; a CA file with more or none is refused."""
    blocks = _PEM_CERTIFICATE.findall(certificate_pem or "")
    if len(blocks) != 1:
        raise CaPinMismatch(f"Expected one PEM certificate from the master, found {len(blocks)}")
    return blocks[0] + "\n"


def verified_context(ca_certificate_pem: str) -> ssl.SSLContext:
    """A client TLS context that trusts only the master's CA and checks the host name."""
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cadata=single_certificate(ca_certificate_pem))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _unverified_context() -> ssl.SSLContext:
    # Used for exactly one request, whose answer is checked against the pinned hash.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def open_url(request: urllib.request.Request, context: ssl.SSLContext, timeout_s: float):
    """Open an HTTPS request with this TLS context, directly: proxies from the environment are not used for the master."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    return opener.open(request, timeout=timeout_s)


def fetch_ca_certificate(master_url: str, *, timeout_s: float = FETCH_TIMEOUT_S) -> str:
    """The CA certificate the master serves, not yet trusted."""
    request = urllib.request.Request(f"{master_url}{CA_CERTIFICATE_PATH}", method="GET")
    with open_url(request, _unverified_context(), timeout_s) as response:
        return response.read().decode("ascii", errors="replace")


def pinned_ca_certificate(master_url: str, expected_sha256: str, *, timeout_s: float = FETCH_TIMEOUT_S) -> str:
    """The master's CA certificate, after its hash matched the pin; raises CaPinMismatch otherwise."""
    certificate_pem = single_certificate(fetch_ca_certificate(master_url, timeout_s=timeout_s))
    ensure_pinned(certificate_pem, expected_sha256)
    return certificate_pem


def ensure_pinned(certificate_pem: str, expected_sha256: str) -> None:
    actual = certificate_sha256(certificate_pem)
    if actual != expected_sha256:
        raise CaPinMismatch(
            f"The master's CA certificate has SHA-256 {actual}, but SCENEGEMS_MASTER_CA_SHA256 is {expected_sha256}. "
            "Refusing to pair: check the value printed by the master's token command and the master address."
        )
