"""Shallow-clone a GitHub owner/repo into a destination directory."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import rich_click as click

from .console import stderr


def require_git() -> str:
    git = shutil.which("git")
    if not git:
        raise click.UsageError("`git` is not installed or not on PATH.")
    return git


def clone_repo(git: str, repository: str, dest: Path) -> Path:
    """Clone ``owner/repo`` with ``--depth 1`` into ``dest / <repo-name>``."""
    url = f"https://github.com/{repository}.git"
    dest.mkdir(parents=True, exist_ok=True)
    clone_dir = dest / Path(repository).name
    stderr.print(f"Cloning {repository} into {clone_dir}…")
    result = subprocess.run(  # noqa: S603
        [git, "clone", "--depth", "1", url, str(clone_dir)],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if result.returncode != 0:
        raise click.ClickException(
            f"Failed to clone {url} (exit {result.returncode})."
        )
    return clone_dir
