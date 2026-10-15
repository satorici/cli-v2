from typing import Any, Optional

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
AI_PROVIDERS = ("anthropic", "openai", "openrouter")
AI_CREDENTIAL_KEYS = tuple(f"ai.{p}" for p in AI_PROVIDERS)
SETTINGS_KEYS = (
    "github",
    "ai.provider",
    "ai.model_id",
    *AI_CREDENTIAL_KEYS,
    *NOTIFY_KEYS,
)
NOT_SET = "(not set)"
CONFIGURED = "configured"


def _display(value: Optional[str]) -> str:
    return value if value else NOT_SET


def _secret_status(configured: bool) -> str:
    return CONFIGURED if configured else NOT_SET


def _fetch_settings() -> dict[str, Any]:
    return client.get("/settings").json()


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _print_section(title: str, rows: list[tuple[str, str]]) -> None:
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("Key")
    table.add_column("Value")
    for key, value in rows:
        table.add_row(key, value)
    stdout.print(table)


def _print_all(settings: dict[str, Any]) -> None:
    github = _as_dict(settings.get("github"))
    token = _as_dict(github.get("token"))
    _print_section(
        "github",
        [("github", _secret_status(bool(token.get("configured"))))],
    )

    ai = _as_dict(settings.get("ai"))
    credentials = _as_dict(ai.get("credentials"))
    ai_rows: list[tuple[str, str]] = [
        ("ai.provider", _display(ai.get("provider"))),
        ("ai.model_id", _display(ai.get("model_id"))),
    ]
    for provider in AI_PROVIDERS:
        configured = bool(_as_dict(credentials.get(provider)).get("configured"))
        ai_rows.append((f"ai.{provider}", _secret_status(configured)))
    _print_section("ai", ai_rows)

    notify = _as_dict(settings.get("notify"))
    _print_section(
        "notify",
        [(key, _display(notify.get(key))) for key in NOTIFY_KEYS],
    )


def _get_value(settings: dict[str, Any], key: str) -> str:
    if key == "github":
        token = _as_dict(_as_dict(settings.get("github")).get("token"))
        return _secret_status(bool(token.get("configured")))

    if key == "ai.provider":
        return _display(_as_dict(settings.get("ai")).get("provider"))

    if key == "ai.model_id":
        return _display(_as_dict(settings.get("ai")).get("model_id"))

    if key in AI_CREDENTIAL_KEYS:
        provider = key.removeprefix("ai.")
        credentials = _as_dict(_as_dict(settings.get("ai")).get("credentials"))
        return _secret_status(
            bool(_as_dict(credentials.get(provider)).get("configured"))
        )

    notify = _as_dict(settings.get("notify"))
    return _display(notify.get(key))


def _resolve_model_id(ai: dict[str, Any], provider: str) -> str:
    models = _as_dict(ai.get("models")).get(provider) or []
    if not isinstance(models, list) or not models:
        raise click.ClickException(f"No models available for provider {provider!r}")
    current = ai.get("model_id")
    if isinstance(current, str) and current in models:
        return current
    return models[0]


def _clear_key(key: str) -> None:
    if key == "github":
        client.patch("/settings", json={"github": {"token": None}})
    elif key == "ai.provider":
        client.patch("/settings", json={"ai": {"provider": None}})
    elif key == "ai.model_id":
        stderr.print("Cannot clear ai.model_id alone; use: settings ai.provider --clear")
        raise SystemExit(1)
    elif key in AI_CREDENTIAL_KEYS:
        provider = key.removeprefix("ai.")
        client.patch("/settings", json={"ai": {"credentials": {provider: None}}})
    else:
        client.patch("/settings", json={"notify": {key: None}})
    stdout.print(f"{key} cleared")


def _set_key(key: str, value: str) -> None:
    if key == "github":
        client.patch("/settings", json={"github": {"token": value}})
    elif key == "ai.provider":
        if value not in AI_PROVIDERS:
            stderr.print(
                f"Invalid ai.provider: {value!r} "
                f"(use {' | '.join(AI_PROVIDERS)})"
            )
            raise SystemExit(1)
        settings = _fetch_settings()
        ai = _as_dict(settings.get("ai"))
        model_id = _resolve_model_id(ai, value)
        client.patch(
            "/settings",
            json={"ai": {"provider": value, "model_id": model_id}},
        )
    elif key == "ai.model_id":
        settings = _fetch_settings()
        ai = _as_dict(settings.get("ai"))
        provider = ai.get("provider")
        if not provider:
            stderr.print("Select an AI provider first: settings ai.provider PROVIDER")
            raise SystemExit(1)
        client.patch(
            "/settings",
            json={"ai": {"provider": provider, "model_id": value}},
        )
    elif key in AI_CREDENTIAL_KEYS:
        provider = key.removeprefix("ai.")
        client.patch(
            "/settings",
            json={"ai": {"credentials": {provider: value}}},
        )
    else:
        if key == "default" and value not in NOTIFY_DEFAULTS:
            stderr.print(
                f"Invalid default: {value!r} "
                f"(use {' | '.join(sorted(NOTIFY_DEFAULTS))})"
            )
            raise SystemExit(1)
        client.patch("/settings", json={"notify": {key: value}})
    stdout.print(f"{key} updated")


@click.command("settings")
@click.argument(
    "key",
    required=False,
    type=click.Choice(SETTINGS_KEYS, case_sensitive=False),
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
    """List, get, or set personal settings (github, AI, notification defaults)."""
    if key is None:
        if clear_value or value is not None:
            raise click.UsageError("--clear and VALUE require KEY")
        _print_all(_fetch_settings())
        return

    key = key.lower()

    if clear_value:
        if value is not None:
            raise click.UsageError("Cannot combine VALUE with --clear")
        _clear_key(key)
        return

    if value is None:
        stdout.print(_get_value(_fetch_settings(), key))
        return

    if value == "":
        stderr.print(f"'{key}' value must not be empty; use --clear to remove it")
        raise SystemExit(1)

    _set_key(key, value)
