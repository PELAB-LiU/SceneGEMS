"""Compare the fingerprints a node reports with the required ones."""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class FingerprintMismatch:
    image: str
    required: str
    actual: Optional[str]  # None when the node has no fingerprinted image of that name

    @property
    def missing(self) -> bool:
        return self.actual is None


def find_mismatches(actual: Dict[str, str], required: Dict[str, str]) -> List[FingerprintMismatch]:
    """Required images the node lacks or has built from other inputs; images not required are ignored."""
    return [FingerprintMismatch(image, fingerprint, actual.get(image)) for image, fingerprint in sorted(required.items()) if actual.get(image) != fingerprint]
