"""Shallow-clone a GitHub owner/repo into a destination directory."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
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

    ``quiet`` writes nothing to this process's stdout/stderr (needed by the MCP
    server, where stdout is the protocol channel) and raises ``SatoriError``.
    """
    url = f"https://github.com/{repository}.git"
    dest.mkdir(parents=True, exist_ok=True)
    clone_dir = dest / Path(repository).name
    cmd = [git, "clone", "--depth", "1", url, str(clone_dir)]
    if quiet:
        result = subprocess.run(  # noqa: S603
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        if result.returncode != 0:
            raise SatoriError(
                f"Failed to clone {url} (exit {result.returncode}): "
                f"{(result.stderr or '').strip()[:500]}"
            )
        return clone_dir

    stderr.print(f"Cloning {repository} into {clone_dir}…")
    result = subprocess.run(  # noqa: S603
        cmd,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if result.returncode != 0:
        raise click.ClickException(
            f"Failed to clone {url} (exit {result.returncode})."
        )
    return clone_dir
