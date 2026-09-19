"""Hand-rolled Python wrappers for the external CLI tools run-remote's
toolchain must stay external -- see UTILS.md at the repo root for why each
one can't be replaced with a Python-native (stdlib or official third-party)
equivalent: ssh, scp, rsync, git, uv.

Every wrapper builds subprocess argv as a list, never a shell string, so
the local invocation never needs shell-quoting -- see _proc.py. The one
place quoting is still unavoidable is inside a remote command string
handed to `ssh`/`bash -c`; ssh.quote() (shlex.quote) is for that.
"""

# Rewritten in place by .github/workflows/build-wheel.yml from the
# workflow_dispatch `version` input; hatchling reads the wheel version from
# here (see [tool.hatch.version] in pyproject.toml).
__version__ = "0.0.0"
