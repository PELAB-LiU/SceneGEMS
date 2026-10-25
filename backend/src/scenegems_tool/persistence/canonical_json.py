"""Canonical JSON and its sha256, so equal content gives one hash whatever its key order.

Keys sorted, no whitespace, UTF-8 without escapes, no NaN or infinity. Campaign configs and
the keys of calibration results are hashed this way.
"""

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
