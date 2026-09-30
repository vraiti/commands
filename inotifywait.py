"""Hand-rolled wrapper around the `inotifywait` binary (inotify-tools).

Kept external: the stdlib has no inotify binding (it would take ctypes or a
third-party package), and inotifywait -r already handles the fiddly part --
adding watches for directories created after startup.
"""
from __future__ import annotations

import contextlib
import os
import select
import subprocess
from collections.abc import Iterator

from . import _proc


class Monitor:
    """A running `inotifywait -m`; see monitor()."""

    def __init__(self, argv: list[str], proc: subprocess.Popen) -> None:
        assert proc.stdout is not None  # guaranteed by stdout=PIPE in monitor()
        self._argv = argv
        self._proc = proc
        self._fd = proc.stdout.fileno()

    def wait(self, timeout: float) -> bool:
        """Block up to timeout seconds for events. True if any arrived (all
        of those already queued are consumed together), False on timeout.
        Raises CommandError if inotifywait has exited, e.g. because it hit
        fs.inotify.max_user_watches."""
        ready, _, _ = select.select([self._fd], [], [], timeout)
        if not ready:
            return False
        if os.read(self._fd, 65536):
            return True
        self._proc.wait()
        raise _proc.CommandError(self._argv, self._proc.returncode, None, None)


@contextlib.contextmanager
def monitor(path: str, *, events: list[str], exclude: str | None = None, cwd: str | None = None) -> Iterator[Monitor]:
    """inotifywait -m -r -q -e <events> [--exclude <regex>] <path>, running
    for the duration of the with block and terminated on exit.

    exclude is matched against event paths as inotifywait prints them, i.e.
    relative to cwd when path is relative -- pass path="." with cwd set to
    keep the regex from also matching components above the watched tree."""
    argv = ["inotifywait", "-m", "-r", "-q", "--format", "%e", "-e", ",".join(events)]
    if exclude is not None:
        argv += ["--exclude", exclude]
    argv.append(path)
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, cwd=cwd) as proc:
        try:
            yield Monitor(argv, proc)
        finally:
            proc.terminate()
