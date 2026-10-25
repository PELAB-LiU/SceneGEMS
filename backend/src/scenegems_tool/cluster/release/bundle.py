"""Write a release bundle from the images built on this machine.

The bundle records each image's ID and fingerprint label as Docker reports them here, so
the deployment tool can tell whether a machine already has the same image, and the
master can tell whether a node runs the images of this release.
"""

import datetime
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from scenegems_tool.cluster.release.manifest import FINGERPRINT_LABEL, RELEASE_FILE, Release, ReleaseError, ReleaseImage, write_release
from scenegems_tool.cluster.release.roles import NAME_PATTERN, POSTGRES_IMAGE, role_images, scenegems_roles

RELEASE_NAME = "scenegems"
STACKS_FOLDER = "stacks"
# The compose file each role's stack is made of, relative to the repository root
STACK_COMPOSE_FILES = {"master": "deploy/master/docker-compose.yml", "node": "deploy/node/docker-compose.yml"}


@dataclass(frozen=True)
class InspectedImage:
    image_id: str
    labels: Dict[str, str]


def inspect_local_image(tag: str) -> Optional[InspectedImage]:
    """The local image of that tag, or None when Docker has none."""
    completed = subprocess.run(["docker", "image", "inspect", "--format", "{{json .}}", tag], capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return None
    data = json.loads(completed.stdout)
    labels = (data.get("Config") or {}).get("Labels") or {}
    return InspectedImage(image_id=data["Id"], labels=dict(labels))


def build_bundle(
    out_dir: Path,
    repo_root: Path,
    revision: str,
    dirty: bool,
    inspect: Callable[[str], Optional[InspectedImage]] = inspect_local_image,
    now: Optional[datetime.datetime] = None,
) -> Release:
    """Write release.json and stacks/ into out_dir and return the release. Fails if an image is not built here."""
    roles = scenegems_roles()
    images: Dict[str, ReleaseImage] = {}
    missing = []
    for tag in role_images(roles):
        found = inspect(tag)
        if found is None:
            missing.append(tag)
            continue
        images[tag] = ReleaseImage(image_id=found.image_id, fingerprint=found.labels.get(FINGERPRINT_LABEL) or None)
    if missing:
        hint = f"; pull {POSTGRES_IMAGE} with docker pull" if POSTGRES_IMAGE in missing else ""
        raise ReleaseError(f"these images are not on this machine: {', '.join(missing)}. Build them with ./build.sh{hint}")
    unlabelled = [tag for tag, image in images.items() if tag != POSTGRES_IMAGE and image.fingerprint is None]
    if unlabelled:
        raise ReleaseError(f"these images carry no {FINGERPRINT_LABEL} label: {', '.join(unlabelled)}. Rebuild them with ./build.sh")

    out_dir.mkdir(parents=True, exist_ok=True)
    stacks = out_dir / STACKS_FOLDER
    if stacks.exists():
        shutil.rmtree(stacks)
    for role, compose_file in STACK_COMPOSE_FILES.items():
        target = stacks / roles[role]["stack"]
        target.mkdir(parents=True)
        shutil.copyfile(repo_root / compose_file, target / "docker-compose.yml")

    created = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat(timespec="seconds")
    release = Release(name=RELEASE_NAME, revision=revision, dirty=dirty, created_at=created, images=images, roles=roles, name_pattern=NAME_PATTERN)
    write_release(out_dir / RELEASE_FILE, release)
    return release
