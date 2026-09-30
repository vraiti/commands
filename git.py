"""Hand-rolled wrapper around the `git` binary.

pygit2 was considered for the local commit-plumbing half, but push needs to
stay on real `git` for SSH-agent/credential-helper compatibility (pygit2's
own SSH transport, via libssh2, has historically weaker support for modern
key types/agent setups than plain OpenSSH gives for free) -- see UTILS.md.
Since git stays external either way, this wraps the CLI entirely rather
than splitting the implementation across two libraries.
"""
from __future__ import annotations

import os
import subprocess
from typing import NamedTuple

from . import _proc


def _git(
    repo_dir: str,
    *args: str,
    check: bool = True,
    capture: bool = True,
    env: dict[str, str] | None = None,
    config: dict[str, str] | None = None,
    input: str | None = None,  # pylint: disable=redefined-builtin
) -> subprocess.CompletedProcess:
    """git -C <repo_dir> [-c key=value...] <args...> -- config entries are
    one-off `-c` overrides for this invocation only, never written anywhere."""
    overrides = [arg for key, value in (config or {}).items() for arg in ("-c", f"{key}={value}")]
    return _proc.run(["git", "-C", repo_dir, *overrides, *args], check=check, capture=capture, env=env, input=input)


def _index_env(index_file: str | None) -> dict[str, str] | None:
    """Full env (see _proc.run) pointing git at index_file instead of the
    repo's own index -- None (inherit) when no index_file is given."""
    return None if index_file is None else {**os.environ, "GIT_INDEX_FILE": index_file}


def version() -> str:
    """git version, e.g. "git version 2.55.0"."""
    return _proc.run(["git", "version"]).stdout.strip()


def toplevel(path: str) -> str | None:
    """Absolute path of the work tree containing path, or None if path
    isn't inside a git work tree (or doesn't exist)."""
    result = _git(path, "rev-parse", "--show-toplevel", check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def git_path(repo_dir: str, name: str) -> str:
    """Absolute path of name inside the repo's git dir (rev-parse --git-path),
    which resolves to the right place for linked worktrees too."""
    return _git(repo_dir, "rev-parse", "--path-format=absolute", "--git-path", name).stdout.strip()


def is_dirty(repo_dir: str) -> bool:
    return bool(_git(repo_dir, "status", "--porcelain").stdout.strip())


def current_branch(repo_dir: str) -> str | None:
    """None means detached HEAD (mirrors `git branch --show-current`, which
    prints nothing in that case)."""
    branch = _git(repo_dir, "branch", "--show-current").stdout.strip()
    return branch or None


def rev_parse(repo_dir: str, rev: str, *, short: bool = False) -> str:
    args = ["rev-parse"]
    if short:
        args.append("--short")
    args.append(rev)
    return _git(repo_dir, *args).stdout.strip()


def verify(repo_dir: str, rev: str) -> str | None:
    """Full sha rev resolves to, or None if it doesn't resolve
    (rev-parse -q --verify). Append ^{commit}/^{tree} to peel."""
    result = _git(repo_dir, "rev-parse", "-q", "--verify", rev, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def subject(repo_dir: str, rev: str) -> str:
    """First line of rev's commit message."""
    return _git(repo_dir, "log", "-1", "--format=%s", rev).stdout.rstrip("\n")


def parents(repo_dir: str, rev: str) -> list[str]:
    """Full shas of rev's parents, first parent first."""
    return _git(repo_dir, "log", "-1", "--format=%P", rev).stdout.split()


def is_ancestor(repo_dir: str, ancestor: str, descendant: str) -> bool:
    """merge-base --is-ancestor; False as well when either rev doesn't
    resolve (e.g. an object that was never fetched)."""
    return _git(repo_dir, "merge-base", "--is-ancestor", ancestor, descendant, check=False).returncode == 0


def rev_list_count(repo_dir: str, rev_range: str) -> int:
    """rev-list --count <rev_range>, e.g. "main..topic"."""
    return int(_git(repo_dir, "rev-list", "--count", rev_range).stdout.strip())


def for_each_ref(repo_dir: str, *patterns: str) -> list[str]:
    """Full names of the refs matching patterns (a trailing "/" matches
    everything under that prefix)."""
    return _git(repo_dir, "for-each-ref", "--format=%(refname)", *patterns).stdout.splitlines()


def ref_exists(repo_dir: str, ref: str) -> bool:
    return _git(repo_dir, "show-ref", "--verify", "--quiet", ref, check=False).returncode == 0


def add_all(repo_dir: str, *, index_file: str | None = None) -> None:
    """git add -A -- into index_file instead of the repo's own index when given."""
    _git(repo_dir, "add", "-A", env=_index_env(index_file))


def write_tree(repo_dir: str, *, index_file: str | None = None) -> str:
    """git write-tree -- from index_file instead of the repo's own index when given."""
    return _git(repo_dir, "write-tree", env=_index_env(index_file)).stdout.strip()


def committer_ident(repo_dir: str) -> str:
    return _git(repo_dir, "var", "GIT_COMMITTER_IDENT").stdout.strip()


def commit_tree(repo_dir: str, tree: str, parents: list[str], message: str) -> str:
    args = ["commit-tree", tree]
    for parent in parents:
        args += ["-p", parent]
    args += ["-m", message]
    return _git(repo_dir, *args).stdout.strip()


def update_ref(repo_dir: str, ref: str, sha: str, *, message: str | None = None, old: str | None = None) -> None:
    """git update-ref [-m message] <ref> <sha> [<old>] -- message goes to the
    reflog; with old, refuses unless ref currently points at old."""
    _git(repo_dir, "update-ref", *(["-m", message] if message else []), ref, sha, *([old] if old else []))


class IndexEntry(NamedTuple):
    """One index entry, as `git ls-files --stage` shows it; stage 1-3 are
    the base/ours/theirs versions of a conflicted path."""

    mode: str
    sha: str
    stage: int
    path: str


def delete_ref(repo_dir: str, ref: str, *, old: str | None = None) -> None:
    """git update-ref -d <ref> [<old>] -- with old, refuses unless ref
    currently points at old."""
    _git(repo_dir, "update-ref", "-d", ref, *([old] if old else []))


def merge_tree(repo_dir: str, ours: str, theirs: str) -> tuple[str, list[IndexEntry]]:
    """git merge-tree --write-tree <ours> <theirs>: merges two commits
    without touching the index or working tree. Returns (tree, conflicted
    entries). On conflicts the tree is what `git merge` would leave in the
    working tree (conflict markers included, labelled with ours/theirs as
    given) and the entries are the stages it would leave in the index."""
    args = ["merge-tree", "--write-tree", "-z", "--no-messages", ours, theirs]
    result = _git(repo_dir, *args, check=False)
    if result.returncode not in (0, 1):
        raise _proc.CommandError(["git", "-C", repo_dir, *args], result.returncode, result.stdout, result.stderr)
    tree, *records = result.stdout.split("\0")
    entries = []
    for record in records:
        if record:
            info, path = record.split("\t", 1)
            mode, sha, stage = info.split()
            entries.append(IndexEntry(mode, sha, int(stage), path))
    return tree, entries


def set_conflicts(repo_dir: str, entries: list[IndexEntry]) -> None:
    """Replace each entry's path in the index with its conflict stages, the
    way a conflicted `git merge` leaves them (git update-index --index-info)."""
    null = "0" * 40
    lines = [f"0 {null}\t{path}" for path in dict.fromkeys(e.path for e in entries)]  # drop stage 0 first
    lines += [f"{e.mode} {e.sha} {e.stage}\t{e.path}" for e in entries]
    _git(repo_dir, "update-index", "--index-info", input="".join(line + "\n" for line in lines))


def read_tree(
    repo_dir: str, *trees: str, merge: bool = False, update: bool = False, reset: bool = False
) -> None:
    """git read-tree [-m|--reset] [-u] <trees...>: load trees into the index.
    With merge and two trees, a two-way merge from the first to the second
    that refuses to lose local changes; update also applies it to the
    working tree. reset is like merge but discards local changes and
    unmerged entries instead of refusing."""
    mode = ["-m"] if merge else ["--reset"] if reset else []
    _git(repo_dir, "read-tree", *mode, *(["-u"] if update else []), *trees)


def refresh_index(repo_dir: str) -> None:
    """git update-index -q --refresh: re-stat the working tree so files whose
    content matches the index count as unchanged. Files that really differ
    are left alone (not an error)."""
    _git(repo_dir, "update-index", "-q", "--refresh", check=False)


def checkout(repo_dir: str, branch: str) -> None:
    _git(repo_dir, "checkout", branch)


def symbolic_ref_exists(repo_dir: str, ref: str = "HEAD") -> bool:
    """True unless repo_dir is in detached-HEAD state."""
    return _git(repo_dir, "symbolic-ref", "-q", ref, check=False).returncode == 0


def config_get(repo_dir: str, key: str) -> str | None:
    result = _git(repo_dir, "config", "--get", key, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def config_get_bool(repo_dir: str, key: str) -> bool | None:
    """git config --type=bool --get <key>: None if unset; raises CommandError
    if the value isn't a boolean git understands (true/yes/on/1, false/...)."""
    result = _git(repo_dir, "config", "--type=bool", "--get", key, check=False)
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise _proc.CommandError(["git", "-C", repo_dir, "config", "--type=bool", "--get", key], result.returncode,
                                 result.stdout, result.stderr)
    return result.stdout.strip() == "true"


def config_unset(repo_dir: str, key: str) -> bool:
    """git config --local --unset-all <key>; False if it wasn't set."""
    return _git(repo_dir, "config", "--local", "--unset-all", key, check=False).returncode == 0


def config_set(repo_dir: str, key: str, value: str, *, replace_all: bool = False) -> None:
    """git config --local [--replace-all] <key> <value> -- replace_all
    collapses a multi-valued key to this single value (plain set refuses to
    touch a key that already has several)."""
    _git(repo_dir, "config", "--local", *(["--replace-all"] if replace_all else []), key, value)


def config_remove_section(repo_dir: str, section: str) -> bool:
    """git config --local --remove-section <section>; False if there was no
    such section."""
    return _git(repo_dir, "config", "--local", "--remove-section", section, check=False).returncode == 0


def hook_list(repo_dir: str, event: str, *, config: dict[str, str] | None = None) -> list[str]:
    """git hook list <event>: names of the hooks that would run for event.
    Empty when there are none -- and also when this git has no `hook list`
    at all, so callers can probe for config-based hook support by passing
    a hook.<name>.* definition in config and checking <name> comes back."""
    return _git(repo_dir, "hook", "list", event, check=False, config=config).stdout.splitlines()


def remote_url(repo_dir: str, remote: str) -> str | None:
    """URL of the named remote, or None if there's no remote by that name."""
    result = _git(repo_dir, "remote", "get-url", remote, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def push(repo_dir: str, remote: str, branch: str, *, set_upstream: bool = True) -> None:
    args = ["push"]
    if set_upstream:
        args.append("-u")
    args += [remote, branch]
    _git(repo_dir, *args, capture=False)


def push_refspecs(
    repo_dir: str,
    remote: str,
    *refspecs: str,
    force: bool = False,
    force_with_lease: str | None = None,
    no_verify: bool = False,
) -> None:
    """git push [--force] [--force-with-lease=<lease>] [--no-verify] <remote>
    <refspecs...>, output captured (it lands in CommandError on failure).
    force_with_lease is "<ref>:<expected sha>"; no_verify skips this repo's
    own pre-push hooks."""
    args = ["push"]
    if force:
        args.append("--force")
    if force_with_lease:
        args.append(f"--force-with-lease={force_with_lease}")
    if no_verify:
        args.append("--no-verify")
    _git(repo_dir, *args, remote, *refspecs)


def ls_remote(repo_dir: str, remote: str, *refs: str) -> dict[str, str]:
    """{ref: sha} as the remote itself has them right now (git ls-remote),
    without fetching anything. refs are exact full ref names, e.g.
    "refs/heads/main"; a ref the remote doesn't have is just absent."""
    result = _git(repo_dir, "ls-remote", "--refs", remote, *refs)
    found = {}
    for line in result.stdout.splitlines():
        sha, ref = line.split("\t", 1)
        # ls-remote matches its patterns against the tail of ref names only
        # ("refs/heads/main" would also match "refs/heads/x/refs/heads/main").
        if not refs or ref in refs:
            found[ref] = sha
    return found


def fetch(
    repo_dir: str, remote: str, *refspecs: str, prune: bool = False, write_fetch_head: bool = True
) -> None:
    """git fetch [--prune] [--no-write-fetch-head] <remote> <refspecs...>,
    output captured. remote may be a remote name or a URL."""
    args = ["fetch"]
    if prune:
        args.append("--prune")
    if not write_fetch_head:
        args.append("--no-write-fetch-head")
    _git(repo_dir, *args, remote, *refspecs)


def submodule_status(repo_dir: str) -> list[tuple[str, str, bool]]:
    """[(sha, path, initialized), ...] -- mirrors `git submodule status`
    lines ("[-+U ]<sha><path> [(<describe>)]"); a leading '-' means not
    initialized (nothing to sync/commit/push for it)."""
    result = _git(repo_dir, "submodule", "status", check=False)
    entries = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        flag, rest = line[0], line[1:]
        sha, path = rest.split()[:2]
        entries.append((sha, path, flag != "-"))
    return entries


def signed_off_trailer(repo_dir: str) -> str:
    """Same trailer `git commit -s` would add -- commit-tree has no -s of
    its own, so it's built by hand from GIT_COMMITTER_IDENT with the
    trailing "<timestamp> <tz>" stripped."""
    ident = committer_ident(repo_dir)
    name_email = ident.rsplit(" ", 2)[0]
    return f"Signed-off-by: {name_email}"


def archive_to(repo_dir: str, commit: str, dest_dir: str) -> None:
    """git archive <commit> | tar -x -C <dest_dir> -- exports exactly the
    committed tree, not the working directory (this is what keeps an
    untracked-but-not-gitignored stray file from ever reaching a synced
    remote). Streams the archive through an OS pipe between the two
    subprocesses rather than buffering it in this process as text -- a git
    archive is a binary tar stream and can be large, so reading it via
    _proc.run's text=True capture would both risk a UnicodeDecodeError on
    binary file content and hold the whole archive in memory at once.
    """
    with subprocess.Popen(["git", "-C", repo_dir, "archive", commit], stdout=subprocess.PIPE) as git_proc:
        assert git_proc.stdout is not None  # guaranteed by stdout=PIPE above
        with subprocess.Popen(["tar", "-x", "-C", dest_dir], stdin=git_proc.stdout) as tar_proc:
            git_proc.stdout.close()  # let tar_proc see EOF/SIGPIPE correctly if it exits first
            tar_proc.wait()
        git_proc.wait()

    if git_proc.returncode != 0:
        raise _proc.CommandError(["git", "-C", repo_dir, "archive", commit], git_proc.returncode, None, None)
    if tar_proc.returncode != 0:
        raise _proc.CommandError(["tar", "-x", "-C", dest_dir], tar_proc.returncode, None, None)


def archive_repo_tree(repo_dir: str, commit: str, dest_dir: str) -> None:
    """Recursive version of archive_to: also archives each initialized
    submodule's own committed tree into the corresponding subdirectory --
    `git archive` on the parent alone only emits an empty directory for a
    submodule path (a gitlink, not real content), so that directory (already
    created by the parent's own extraction) needs its contents filled in
    separately, recursing for submodules-of-submodules."""
    archive_to(repo_dir, commit, dest_dir)
    for sha, path, initialized in submodule_status(repo_dir):
        if initialized:
            archive_repo_tree(os.path.join(repo_dir, path), sha, os.path.join(dest_dir, path))


def auto_commit_tree(repo_dir: str) -> None:
    """Commit any uncommitted changes (and initialized submodules,
    recursively) onto AUTOCOMMIT/<branch> via plumbing rather than
    checkout-then-commit. Across enough runs, AUTOCOMMIT/<branch>'s last
    snapshot and the current dirty tree inevitably disagree on some file
    (the real branch moved, or was edited again since), and checking out a
    branch whose committed content differs from an uncommitted local change
    is exactly what `git checkout` correctly refuses to do ("would be
    overwritten by checkout"). write-tree snapshots the current index
    (right after add -A, that's exactly the working tree), so the new
    commit's tree already equals the working tree by construction --
    update-ref moves the branch onto it without touching the working tree
    at all, making the final checkout always a genuine no-op.
    """
    if is_dirty(repo_dir):
        branch = current_branch(repo_dir)
        if branch is None:
            branch = f"detached-{rev_parse(repo_dir, 'HEAD', short=True)}"
        auto_branch = branch if branch.startswith("AUTOCOMMIT/") else f"AUTOCOMMIT/{branch}"

        add_all(repo_dir)
        tree = write_tree(repo_dir)
        ref = f"refs/heads/{auto_branch}"
        parent = rev_parse(repo_dir, ref) if ref_exists(repo_dir, ref) else rev_parse(repo_dir, "HEAD")
        message = f"run-remote auto-commit\n\n{signed_off_trailer(repo_dir)}"
        commit_sha = commit_tree(repo_dir, tree, [parent], message)
        update_ref(repo_dir, ref, commit_sha)
        checkout(repo_dir, auto_branch)

    for _sha, path, initialized in submodule_status(repo_dir):
        if initialized:
            auto_commit_tree(os.path.join(repo_dir, path))
