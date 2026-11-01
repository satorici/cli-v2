import platform
import subprocess
import sys
import sysconfig
from pathlib import Path

import rich_click as click

from ..utils.console import stderr


@click.command()
def update():
    args = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--force-reinstall",
        "git+https://github.com/satorici/cli-v2",
    ]
    # PEP 668: Homebrew/distro Pythons refuse pip installs outside a venv.
    # The CLI is already installed there, so updating it in place is intended.
    in_venv = sys.prefix != sys.base_prefix
    marker = Path(sysconfig.get_path("stdlib")) / "EXTERNALLY-MANAGED"
    if not in_venv and marker.exists():
        args.append("--break-system-packages")
    stderr.print(f"Going to run: {' '.join(args)}")

    if platform.system() == "Windows":
        subprocess.Popen(args)  # noqa: S603
        return

    proc = subprocess.run(args, stdout=sys.stdout, stderr=sys.stderr)  # noqa: S603

    sys.exit(proc.returncode)
