"""Shallow-clone a GitHub owner/repo into a destination directory."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import rich_click as click

from ..exceptions import SatoriError

log = logging.getLogger(__name__)

_CLONE_ATTEMPTS = 3
_CLONE_BACKOFF_S = 10.0
# Retry only genuine network flakiness (a 404 / auth error must fail fast, not retry).
_TRANSIENT_CLONE_RE = re.compile(
    r"Connection reset|Connection timed out|Could not resolve host|Recv failure|send failure"
    r"|early EOF|unexpected disconnect|RPC failed|fetch-pack|index-pack|GnuTLS|TLS|SSL"
    r"|Operation timed out|timed out|returned error: 5\d\d|Temporary failure|Broken pipe",
    re.IGNORECASE,
)


# A cloned repo's agent config to move aside before running Claude in it: `.claude/` (hooks,
# settings, skills, commands, agents -> code execution), `.mcp.json` (servers Claude would
# spawn), and the instruction files Claude auto-loads (prompt injection).
_UNTRUSTED_CONFIG = (".claude", ".mcp.json", "CLAUDE.md", "AGENTS.md", ".cursorrules")


def defang_clone(clone_dir: Path) -> None:
    """Rename a cloned repo's agent config to ``*.bak`` before running Claude in it, so an
    untrusted repo's hooks, MCP servers and instruction files cannot take effect. Claude loads
    project config from its working directory with no trust prompt in ``-p`` mode, so moving
    these files aside -- deterministically, before Claude starts -- is what stops a cloned
    repo from running code or injecting instructions during an agent pass over it. Shared by
    every caller that runs Claude over an untrusted clone (verify, improve-report, ...)."""
    for name in _UNTRUSTED_CONFIG:
        entry = clone_dir / name
        if not entry.exists():
            continue
        backup = clone_dir / f"{name}.bak"
        if backup.is_dir():
            shutil.rmtree(backup, ignore_errors=True)
        elif backup.exists():
            backup.unlink()
        entry.rename(backup)


def require_git(quiet: bool = False) -> str:
    git = shutil.which("git")
    if not git:
        if quiet:
            raise SatoriError("`git` is not installed or not on PATH.")
        raise click.UsageError("`git` is not installed or not on PATH.")
    return git


def require_claude() -> str:
    """Path to the Claude Code CLI binary, required by every agent pass over a clone
    (verify, improve-report, ...)."""
    claude = shutil.which("claude")
    if not claude:
        raise click.UsageError(
            "`claude` (Claude Code CLI) is not installed or not on PATH. "
            "Install with: npm install -g @anthropic-ai/claude-code"
        )
    return claude


def clone_repo(git: str, repository: str, dest: Path, quiet: bool = False) -> Path:
    """Clone ``owner/repo`` with ``--depth 1`` into ``dest / <repo-name>``.

    git runs with ``--quiet`` and its output is captured, so the ``remote:`` /
    ``Receiving objects`` progress never reaches this process's streams; the
    captured stderr is surfaced only when the clone fails. A transient network
    failure (connection reset, early EOF, timeout, DNS) is retried a few times with
    backoff; a non-transient one (missing repo, auth) fails immediately. The
    "Cloning <repo> into <dir>" line is debug logging (shown with ``--debug``).
    ``quiet`` raises ``SatoriError`` instead of a click error (for callers that must
    keep stdout clean).
    """
    url = f"https://github.com/{repository}.git"
    dest.mkdir(parents=True, exist_ok=True)
    clone_dir = dest / Path(repository).name
    cmd = [git, "clone", "--quiet", "--depth", "1", url, str(clone_dir)]
    log.debug(f"Cloning {repository} into {clone_dir}")
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
