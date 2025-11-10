import sys
from typing import Optional

import rich_click as click

from ..config import config
from ..utils.console import stderr, stdout
from ..utils.options import profile_opt


@click.command("config")
@click.argument("key", required=False)
@click.argument("value", required=False)
@profile_opt
def config_(key: Optional[str], value: Optional[str], **kwargs):
    if key is None:
        stdout.print(config)
        return

    if value is None:
        try:
            stdout.print(config[key])
        except KeyError:
            stderr.print(f"'{key}' not found in profile {kwargs['profile']}")
        return

    if key and value == "":
        stderr.print(f"'{key}' value must not be empty")
        sys.exit(1)

    config.save(key, value, kwargs["profile"])
