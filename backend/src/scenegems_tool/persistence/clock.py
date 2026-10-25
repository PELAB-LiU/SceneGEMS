"""The clock the stores read. Stores take it as an argument, so tests drive time explicitly."""

from datetime import datetime, timezone
from typing import Callable

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
