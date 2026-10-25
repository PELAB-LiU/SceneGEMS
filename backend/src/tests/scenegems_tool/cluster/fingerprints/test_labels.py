import io
import uuid

import pytest

from scenegems_tool.cluster.fingerprints.labels import FINGERPRINT_LABEL, read_image_fingerprints


class _Image:
    def __init__(self, tags, labels):
        self.tags = tags
        self.labels = labels


class _Client:
    def __init__(self, images):
        self.images = self
        self._images = images

    def list(self):
        return self._images


def test_reads_the_label_of_every_tag():
    client = _Client([_Image(["a:latest", "a:v1"], {FINGERPRINT_LABEL: "abc"}), _Image(["b:latest"], {FINGERPRINT_LABEL: "def"})])
    assert read_image_fingerprints(client) == {"a:latest": "abc", "a:v1": "abc", "b:latest": "def"}


def test_images_without_the_label_or_a_tag_are_skipped():
    client = _Client([_Image(["plain:latest"], {}), _Image(["none:latest"], None), _Image([], {FINGERPRINT_LABEL: "abc"})])
    assert read_image_fingerprints(client) == {}


@pytest.mark.docker
def test_reads_the_label_from_a_real_image():
    import docker

    client = docker.from_env()
    tag = f"scenegems-fingerprint-test:{uuid.uuid4().hex[:8]}"
    dockerfile = io.BytesIO(f"FROM scratch\nLABEL {FINGERPRINT_LABEL}=deadbeef\n".encode())
    client.images.build(fileobj=dockerfile, tag=tag)
    try:
        assert read_image_fingerprints(client)[tag] == "deadbeef"
    finally:
        client.images.remove(tag, force=True)
