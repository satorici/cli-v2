"""Shallow-clone a GitHub owner/repo into a destination directory."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import rich_click as click

from ..exceptions import SatoriError
from .console import stderr

_CLONE_ATTEMPTS = 3
_CLONE_BACKOFF_S = 10.0
# Retry only genuine network flakiness (a 404 / auth error must fail fast, not retry).
_TRANSIENT_CLONE_RE = re.compile(
    r"Connection reset|Connection timed out|Could not resolve host|Recv failure|send failure"
    r"|early EOF|unexpected disconnect|RPC failed|fetch-pack|index-pack|GnuTLS|TLS|SSL"
    r"|Operation timed out|timed out|returned error: 5\d\d|Temporary failure|Broken pipe",
    re.IGNORECASE,
)


def require_git(quiet: bool = False) -> str:
    git = shutil.which("git")
    if not git:
        if quiet:
            raise SatoriError("`git` is not installed or not on PATH.")
        raise click.UsageError("`git` is not installed or not on PATH.")
    return git


def clone_repo(git: str, repository: str, dest: Path, quiet: bool = False) -> Path:
    """Clone ``owner/repo`` with ``--depth 1`` into ``dest / <repo-name>``.

    git runs with ``--quiet`` and its output is captured, so the ``remote:`` /
    ``Receiving objects`` progress never reaches this process's streams; the
    captured stderr is surfaced only when the clone fails. A transient network
    failure (connection reset, early EOF, timeout, DNS) is retried a few times with
    backoff; a non-transient one (missing repo, auth) fails immediately. ``quiet``
    also drops the one-line "Cloning …" status and raises ``SatoriError`` instead of
    a click error (for callers that must keep stdout clean).
    """
    url = f"https://github.com/{repository}.git"
    dest.mkdir(parents=True, exist_ok=True)
    clone_dir = dest / Path(repository).name
    cmd = [git, "clone", "--quiet", "--depth", "1", url, str(clone_dir)]
    if not quiet:
        stderr.print(f"Cloning {repository} into {clone_dir}…")
    for attempt in range(1, _CLONE_ATTEMPTS + 1):
        result = subprocess.run(  # noqa: S603
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        if result.returncode == 0:
            return clone_dir
        detail = (result.stderr or "").strip()
        if attempt < _CLONE_ATTEMPTS and _TRANSIENT_CLONE_RE.search(detail):
            shutil.rmtree(clone_dir, ignore_errors=True)  # git won't clone into a non-empty dir
            time.sleep(_CLONE_BACKOFF_S)
            continue
        message = f"Failed to clone {url} (exit {result.returncode}): {detail[:500]}"
        raise SatoriError(message) if quiet else click.ClickException(message)
    raise SatoriError(f"Failed to clone {url}")  # unreachable: the loop returns or raises
