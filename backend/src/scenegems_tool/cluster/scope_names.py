"""Master ids, node ids and broker usernames.

Each one becomes a single MQTT topic level (`scenegems/<master_id>/<node_id>/...`), a part
of Docker container names and a file name. The rule below keeps
all three safe: lowercase letters, digits and hyphens, so no MQTT wildcard (`+`, `#`),
no level separator and no path component can ever appear in one.
"""

import re

SCOPE_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class InvalidScopeName(ValueError):
    pass


def is_scope_name(value: object) -> bool:
    return isinstance(value, str) and SCOPE_NAME_PATTERN.fullmatch(value) is not None


def ensure_scope_name(value: str, what: str) -> str:
    if not is_scope_name(value):
        raise InvalidScopeName(f"Invalid {what} {value!r}: use 1 to 63 lowercase letters, digits and hyphens, starting and ending with a letter or digit")
    return value


def slug_from_name(name: str, *, max_length: int = 40) -> str:
    """A scope name part derived from a free text name such as a node's display name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:max_length].strip("-")
    return slug or "node"
