"""Hand-rolled wrapper around the `gh` binary (GitHub CLI).

Kept external rather than replaced with PyGithub or raw REST calls: gh
already holds this machine's GitHub login, so going through it means no
token handling here at all.
"""
from __future__ import annotations

import json

from . import _proc

# gh pr checks exits 8 while checks are pending (and, on some versions, 1 when
# any failed) but still prints its JSON.
_PR_CHECKS_OK_EXITS = (0, 1, 8)


def pr_checks(repo: str, pr: int, fields: tuple[str, ...] = ("name", "state", "bucket", "link")) -> list[dict]:
    argv = ["gh", "pr", "checks", str(pr), "--repo", repo, "--json", ",".join(fields)]
    result = _proc.run(argv, check=False)
    if result.returncode == 1 and "no checks reported" in (result.stderr or ""):
        return []
    if result.returncode not in _PR_CHECKS_OK_EXITS or not result.stdout.strip():
        raise _proc.CommandError(argv, result.returncode, result.stdout, result.stderr)
    return json.loads(result.stdout)
