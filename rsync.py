"""Hand-rolled wrapper around the `rsync` binary.

Must stay external -- see UTILS.md: no Python package replicates rsync's
delta-transfer protocol or its --delete semantics at production quality.
"""
from __future__ import annotations

import os
import tempfile

from . import _proc


def _flags(delete: bool, exclude: list[str] | None) -> list[str]:
    argv = ["rsync", "-az"]
    if delete:
        argv.append("--delete")
    for pattern in exclude or []:
        argv.append(f"--exclude={pattern}")
    return argv


def _with_trailing_slash(path: str) -> str:
    # src/dst are always synced as directory *contents* -- omitting the
    # slash would nest the source's basename inside the destination instead
    # of replacing the destination's contents with the source's.
    return path if path.endswith("/") else path + "/"


def sync(  # pylint: disable=too-many-arguments
    src_dir: str,
    alias: str,
    dst_dir: str,
    *,
    delete: bool = True,
    exclude: list[str] | None = None,
    files_from: list[str] | None = None,
) -> None:
    """rsync -az [--delete] [--exclude=X ...] [--files-from=F] <src_dir>/ <alias>:<dst_dir>/

    files_from, when given, restricts the transfer to exactly those paths
    (relative to src_dir; directories are recursed into under -a) instead
    of everything under src_dir -- for shipping a specific set of files out
    of a directory that also holds things that shouldn't go along (e.g.
    this toolset's own source files living alongside profiles/, secrets/,
    and .git/ in the same repo).
    """
    argv = _flags(delete, exclude)

    files_from_path = None
    if files_from is not None:
        # --files-from turns OFF rsync's own implied recursion (even under
        # -a), per rsync(1) -- without an explicit -r, a directory entry in
        # the list is copied empty instead of recursed into. Confirmed:
        # a "commands" entry copied zero files without this.
        argv.append("-r")
        fd, files_from_path = tempfile.mkstemp(text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(files_from) + "\n")
        argv.append(f"--files-from={files_from_path}")

    argv += [_with_trailing_slash(src_dir), f"{alias}:{_with_trailing_slash(dst_dir)}"]
    try:
        _proc.run(argv, capture=False)
    finally:
        if files_from_path is not None:
            os.unlink(files_from_path)


def pull(alias: str, remote_dir: str, local_dir: str, *, delete: bool = True, exclude: list[str] | None = None) -> None:
    """rsync -az [--delete] [--exclude=X ...] <alias>:<remote_dir>/ <local_dir>/ -- the reverse
    of sync(): pulls a remote directory's current contents down to a local one."""
    argv = _flags(delete, exclude)
    argv += [f"{alias}:{_with_trailing_slash(remote_dir)}", _with_trailing_slash(local_dir)]
    _proc.run(argv, capture=False)
