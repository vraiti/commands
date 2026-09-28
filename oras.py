"""Hand-rolled wrapper around the `oras` binary (ORAS: OCI Registry As
Storage, https://oras.land), used by run-remote's artifact-type sync
entries to pull/push a zstd-compressed tar snapshot of a local directory
to/from a container registry.

Must stay external -- see UTILS.md's reasoning for git/uv/rsync/scp/ssh:
pulling/pushing an arbitrary artifact to an OCI registry (auth, manifest/
annotation handling, blob upload) is the actual protocol implementation
being orchestrated here, not glue a Python HTTP client should reimplement.
"""
from __future__ import annotations

import os
import tempfile

from . import _proc

CONTENT_HASH_ANNOTATION = "dev.vraiti.run-remote.content-hash"
LAYER_MEDIA_TYPE = "application/vnd.oci.image.layer.v1.tar+zstd"


def _registry_config_args(registry_config: str | None) -> list[str]:
    return ["--registry-config", registry_config] if registry_config else []


def pull(ref: str, dest_dir: str, *, registry_config: str | None = None) -> bool:
    """Pulls ref's tar layer and extracts it into dest_dir (already
    created, left empty). Returns False, without raising, if ref doesn't
    exist yet -- an artifact's first run has nothing to pull. Any other
    failure (bad ref, auth denied, registry down) still raises."""
    os.makedirs(dest_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        argv = ["oras", "pull", ref, "-o", tmp, *_registry_config_args(registry_config)]
        result = _proc.run(argv, check=False)
        if result.returncode != 0:
            stderr = (result.stderr or "").lower()
            if "not found" in stderr or "404" in stderr:
                return False
            raise _proc.CommandError(argv, result.returncode, result.stdout, result.stderr)

        pulled = [f for f in os.listdir(tmp) if os.path.isfile(os.path.join(tmp, f))]
        if len(pulled) != 1:
            raise RuntimeError(f"expected exactly one file pulled from {ref}, got {pulled}")
        _proc.run(["tar", "-xf", os.path.join(tmp, pulled[0]), "-C", dest_dir])
    return True


def push(dir_path: str, ref: str, content_hash: str, *, registry_config: str | None) -> None:
    """Tars and zstd-compresses dir_path's contents into a single layer and
    pushes it to ref, annotated with content_hash -- so the registry itself
    carries a visible fingerprint of what's inside, inspectable without
    pulling and extracting the whole tar."""
    with tempfile.TemporaryDirectory() as tmp:
        archive_path = os.path.join(tmp, "content.tar.zst")
        _proc.run(["tar", "--zstd", "-cf", archive_path, "-C", dir_path, "."])
        _proc.run(
            [
                "oras",
                "push",
                ref,
                "--annotation",
                f"{CONTENT_HASH_ANNOTATION}={content_hash}",
                f"{archive_path}:{LAYER_MEDIA_TYPE}",
                *_registry_config_args(registry_config),
            ],
            capture=False,
        )
