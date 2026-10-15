from typing import Optional

import rich_click as click
from rich.table import Table

from ..api import client
from ..utils.console import stderr, stdout

NOTIFY_KEYS = (
    "default",
    "email",
    "slack_workspace",
    "slack_channel",
    "discord",
    "telegram",
)
NOTIFY_DEFAULTS = frozenset({"slack", "email", "discord", "telegram"})
NOT_SET = "(not set)"


def _display(value: Optional[str]) -> str:
    return value if value else NOT_SET


def _fetch_notify() -> dict:
    settings = client.get("/settings").json()
    notify = settings.get("notify") or {}
    if not isinstance(notify, dict):
        return {}
    return notify


def _print_notify_table(notify: dict) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("Key")
    table.add_column("Value")
    for key in NOTIFY_KEYS:
        table.add_row(key, _display(notify.get(key)))
    stdout.print(table)


@click.command("settings")
@click.argument(
    "key",
    required=False,
    type=click.Choice(NOTIFY_KEYS, case_sensitive=False),
)
@click.argument("value", required=False)
@click.option(
    "--clear",
    "clear_value",
    is_flag=True,
    help="Clear the setting (send null to the API)",
)
def settings(
    key: Optional[str] = None,
    value: Optional[str] = None,
    clear_value: bool = False,
):
    """List, get, or set personal notification defaults."""
    if key is None:
        if clear_value or value is not None:
            raise click.UsageError("--clear and VALUE require KEY")
        _print_notify_table(_fetch_notify())
        return

    key = key.lower()

    if clear_value:
        if value is not None:
            raise click.UsageError("Cannot combine VALUE with --clear")
        client.patch("/settings", json={"notify": {key: None}})
        stdout.print(f"{key} cleared")
        return

    if value is None:
        notify = _fetch_notify()
        stdout.print(_display(notify.get(key)))
        return

    if value == "":
        stderr.print(f"'{key}' value must not be empty; use --clear to remove it")
        raise SystemExit(1)

    if key == "default" and value not in NOTIFY_DEFAULTS:
        stderr.print(
            f"Invalid default: {value!r} "
            f"(use {' | '.join(sorted(NOTIFY_DEFAULTS))})"
        )
        raise SystemExit(1)

    client.patch("/settings", json={"notify": {key: value}})
    stdout.print(f"{key} updated")
