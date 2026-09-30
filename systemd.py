"""Hand-rolled wrappers around systemd's CLI tools: systemctl,
systemd-escape, systemd-id128.

Kept external: the stdlib has no binding to the service manager (talking
D-Bus directly would need a third-party library, and systemctl is the
supported interface anyway), and systemd-escape/systemd-id128 implement
systemd's own unit-name escaping and app-specific id derivation, which a
reimplementation could silently drift from.

user=True targets the calling user's service manager (systemctl --user).
"""
from __future__ import annotations

import subprocess

from . import _proc


def _systemctl(*args: str, user: bool, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return _proc.run(["systemctl", *(["--user"] if user else []), *args], check=check, capture=capture)


def escape_path(path: str, *, template: str | None = None) -> str:
    """systemd-escape --path [--template=<template>] <path>, e.g.
    escape_path("/home/me/repo", template="foo@.service") ->
    "foo@home-me-repo.service"."""
    args = ["systemd-escape", "--path"]
    if template:
        args.append(f"--template={template}")
    return _proc.run([*args, path]).stdout.strip()


def app_specific_machine_id(app_id: str) -> str:
    """systemd-id128 machine-id --app-specific=<app_id>: a stable per-machine
    id derived from /etc/machine-id that doesn't reveal it (systemd says the
    raw machine id should be kept confidential)."""
    return _proc.run(["systemd-id128", "machine-id", f"--app-specific={app_id}"]).stdout.strip()


def daemon_reload(*, user: bool = False) -> None:
    """systemctl daemon-reload -- needed after writing or changing a unit file."""
    _systemctl("daemon-reload", user=user)


def enable(unit: str, *, now: bool = False, user: bool = False) -> None:
    """systemctl enable [--now] <unit>, output passed through."""
    _systemctl("enable", *(["--now"] if now else []), unit, user=user, capture=False)


def disable(unit: str, *, now: bool = False, user: bool = False) -> None:
    """systemctl disable [--now] <unit>, output passed through."""
    _systemctl("disable", *(["--now"] if now else []), unit, user=user, capture=False)


def start(unit: str, *, user: bool = False) -> None:
    """systemctl start <unit>."""
    _systemctl("start", unit, user=user)


def stop(unit: str, *, user: bool = False) -> None:
    """systemctl stop <unit>."""
    _systemctl("stop", unit, user=user)


def is_enabled(unit: str, *, user: bool = False) -> bool:
    """systemctl is-enabled -q <unit>; False too when the service manager
    can't be reached."""
    return _systemctl("is-enabled", "-q", unit, user=user, check=False).returncode == 0


def is_active(unit: str, *, user: bool = False) -> bool:
    """systemctl is-active -q <unit>; False too when the service manager
    can't be reached."""
    return _systemctl("is-active", "-q", unit, user=user, check=False).returncode == 0


def list_units(pattern: str, *, user: bool = False, state: str | None = None) -> list[str]:
    """Names of the loaded units matching a glob pattern (systemctl
    list-units --all), optionally only those in state (e.g. "active").
    Empty too when the service manager can't be reached."""
    args = ["list-units", "--all", "--plain", "--no-legend", *([f"--state={state}"] if state else []), pattern]
    result = _systemctl(*args, user=user, check=False)
    return [line.split()[0] for line in result.stdout.splitlines() if line.strip()]
