"""The fingerprints the images on this machine carry, read from their labels."""

from typing import Any, Dict, Optional

FINGERPRINT_LABEL = "org.scenegems.fingerprint"


def read_image_fingerprints(client: Optional[Any] = None) -> Dict[str, str]:
    """Image tag to fingerprint for every local image with the label; this is the node's Hello.fingerprints."""
    if client is None:
        import docker

        client = docker.from_env()
    fingerprints: Dict[str, str] = {}
    for image in client.images.list():
        fingerprint = (image.labels or {}).get(FINGERPRINT_LABEL)
        if fingerprint:
            for tag in image.tags:
                fingerprints[tag] = fingerprint
    return fingerprints
