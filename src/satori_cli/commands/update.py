import platform
import subprocess
import sys

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
    stderr.print(f"Going to run: {' '.join(args)}")

    if platform.system() == "Windows":
        subprocess.Popen(args)
        return

    proc = subprocess.run(args, stdout=sys.stdout, stderr=sys.stderr)

    sys.exit(proc.returncode)
