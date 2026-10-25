"""Subject alternative names: how clients find the master's API and broker.

A client checks that the address it dialled is listed in the server certificate, so the
certificate must list every IP address and host name a node or container may use.
"""

import ipaddress
from typing import Iterable, List, Union

from cryptography import x509

# Names every master certificate carries: the local host and the compose service names
# the master's own containers dial inside the compose network.
DEFAULT_SUBJECT_NAMES = ("localhost", "127.0.0.1", "::1", "cluster-broker", "master-api")

GeneralName = Union[x509.DNSName, x509.IPAddress]


def subject_alternative_name(value: str) -> GeneralName:
    """An IP address entry when the value parses as one, otherwise a DNS name entry."""
    text = value.strip()
    if not text:
        raise ValueError("Empty subject alternative name")
    try:
        return x509.IPAddress(ipaddress.ip_address(text))
    except ValueError:
        pass
    if any(character.isspace() for character in text) or "/" in text:
        raise ValueError(f"Not an IP address or host name: {value!r}")
    return x509.DNSName(text.lower())


def subject_alternative_names(values: Iterable[str], *, include_defaults: bool = True) -> List[GeneralName]:
    """Deduplicated entries, defaults first, in a stable order."""
    names: List[GeneralName] = []
    candidates = [*DEFAULT_SUBJECT_NAMES, *values] if include_defaults else list(values)
    for value in candidates:
        name = subject_alternative_name(value)
        if name not in names:
            names.append(name)
    return names


def split_address_list(text: str) -> List[str]:
    """Split a comma or whitespace separated list such as SCENEGEMS_MASTER_ADDRESSES."""
    return [part for part in text.replace(",", " ").split() if part]
