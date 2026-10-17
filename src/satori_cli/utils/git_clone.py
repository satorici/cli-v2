"""Shallow-clone a GitHub owner/repo into a destination directory."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import rich_click as click

from ..exceptions import SatoriError
from .console import stderr


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
    captured stderr is surfaced only when the clone fails. ``quiet`` also drops the
    one-line "Cloning …" status and raises ``SatoriError`` instead of a click error
    (needed by the MCP server, where stdout is the protocol channel).
    """
    url = f"https://github.com/{repository}.git"
    dest.mkdir(parents=True, exist_ok=True)
    clone_dir = dest / Path(repository).name
    cmd = [git, "clone", "--quiet", "--depth", "1", url, str(clone_dir)]
    if not quiet:
        stderr.print(f"Cloning {repository} into {clone_dir}…")
    result = subprocess.run(  # noqa: S603
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[:500]
        message = f"Failed to clone {url} (exit {result.returncode}): {detail}"
        raise SatoriError(message) if quiet else click.ClickException(message)
    return clone_dir
