from click.testing import CliRunner

from satori_cli.commands.settings import settings


class _FakeResponse:
    def __init__(self, payload=None):
        self._payload = payload or {}

    def json(self):
        return self._payload


FULL_PAYLOAD = {
    "github": {"token": {"configured": True}},
    "ai": {
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-5",
        "credentials": {
            "anthropic": {"configured": True},
            "openai": {"configured": False},
            "openrouter": {"configured": False},
        },
        "models": {
            "anthropic": ["claude-sonnet-4-5", "claude-opus-4-5"],
            "openai": ["gpt-4o", "gpt-4.1"],
            "openrouter": ["anthropic/claude-sonnet-4.5"],
        },
    },
    "notify": {
        "default": "slack",
        "slack_workspace": "T123",
        "slack_channel": "C456",
        "email": "user@example.com",
        "discord": None,
        "telegram": None,
    },
}


def _table_dict(table) -> dict:
    keys = list(table.columns[0]._cells)
    values = list(table.columns[1]._cells)
    return dict(zip(keys, values))


def test_settings_lists_all_sections(monkeypatch):
    request = {}
    printed = []

    def get(path):
        request["path"] = path
        return _FakeResponse(FULL_PAYLOAD)

    monkeypatch.setattr("satori_cli.commands.settings.client.get", get)
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print",
        lambda *args, **kwargs: printed.append(args[0] if args else None),
    )

    result = CliRunner().invoke(settings)

    assert result.exit_code == 0, result.output
    assert request["path"] == "/settings"
    assert len(printed) == 3
    github, ai, notify = printed
    assert _table_dict(github)["github"] == "configured"
    assert _table_dict(ai)["ai.provider"] == "anthropic"
    assert _table_dict(ai)["ai.openai"] == "(not set)"
    assert _table_dict(notify)["default"] == "slack"
    assert _table_dict(notify)["discord"] == "(not set)"


def test_settings_gets_notify_key(monkeypatch):
    printed = []

    monkeypatch.setattr(
        "satori_cli.commands.settings.client.get",
        lambda path: _FakeResponse(FULL_PAYLOAD),
    )
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print",
        lambda *args, **kwargs: printed.append(args[0] if args else None),
    )

    result = CliRunner().invoke(settings, ["email"])

    assert result.exit_code == 0, result.output
    assert printed == ["user@example.com"]


def test_settings_gets_github_configured(monkeypatch):
    printed = []

    monkeypatch.setattr(
        "satori_cli.commands.settings.client.get",
        lambda path: _FakeResponse(FULL_PAYLOAD),
    )
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print",
        lambda *args, **kwargs: printed.append(args[0] if args else None),
    )

    result = CliRunner().invoke(settings, ["github"])

    assert result.exit_code == 0, result.output
    assert printed == ["configured"]


def test_settings_gets_ai_credential_status(monkeypatch):
    printed = []

    monkeypatch.setattr(
        "satori_cli.commands.settings.client.get",
        lambda path: _FakeResponse(FULL_PAYLOAD),
    )
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print",
        lambda *args, **kwargs: printed.append(args[0] if args else None),
    )

    result = CliRunner().invoke(settings, ["ai.openai"])

    assert result.exit_code == 0, result.output
    assert printed == ["(not set)"]


def test_settings_sets_notify_value(monkeypatch):
    request = {}

    def patch(path, json):
        request["path"] = path
        request["body"] = json
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.settings.client.patch", patch)
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["email", "new@example.com"])

    assert result.exit_code == 0, result.output
    assert request["path"] == "/settings"
    assert request["body"] == {"notify": {"email": "new@example.com"}}


def test_settings_sets_github(monkeypatch):
    request = {}

    def patch(path, json):
        request["path"] = path
        request["body"] = json
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.settings.client.patch", patch)
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["github", "ghp_test"])

    assert result.exit_code == 0, result.output
    assert request["body"] == {"github": {"token": "ghp_test"}}


def test_settings_sets_ai_credential(monkeypatch):
    request = {}

    def patch(path, json):
        request["path"] = path
        request["body"] = json
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.settings.client.patch", patch)
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["ai.openai", "sk-test"])

    assert result.exit_code == 0, result.output
    assert request["body"] == {"ai": {"credentials": {"openai": "sk-test"}}}


def test_settings_sets_ai_provider_picks_model(monkeypatch):
    request = {}

    monkeypatch.setattr(
        "satori_cli.commands.settings.client.get",
        lambda path: _FakeResponse(FULL_PAYLOAD),
    )

    def patch(path, json):
        request["path"] = path
        request["body"] = json
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.settings.client.patch", patch)
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["ai.provider", "openai"])

    assert result.exit_code == 0, result.output
    assert request["body"] == {
        "ai": {"provider": "openai", "model_id": "gpt-4o"},
    }


def test_settings_sets_ai_model_id(monkeypatch):
    request = {}

    monkeypatch.setattr(
        "satori_cli.commands.settings.client.get",
        lambda path: _FakeResponse(FULL_PAYLOAD),
    )

    def patch(path, json):
        request["body"] = json
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.settings.client.patch", patch)
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["ai.model_id", "claude-opus-4-5"])

    assert result.exit_code == 0, result.output
    assert request["body"] == {
        "ai": {"provider": "anthropic", "model_id": "claude-opus-4-5"},
    }


def test_settings_clear_notify(monkeypatch):
    request = {}

    def patch(path, json):
        request["body"] = json
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.settings.client.patch", patch)
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["email", "--clear"])

    assert result.exit_code == 0, result.output
    assert request["body"] == {"notify": {"email": None}}


def test_settings_clear_github(monkeypatch):
    request = {}

    def patch(path, json):
        request["body"] = json
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.settings.client.patch", patch)
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["github", "--clear"])

    assert result.exit_code == 0, result.output
    assert request["body"] == {"github": {"token": None}}


def test_settings_clear_ai_provider(monkeypatch):
    request = {}

    def patch(path, json):
        request["body"] = json
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.settings.client.patch", patch)
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["ai.provider", "--clear"])

    assert result.exit_code == 0, result.output
    assert request["body"] == {"ai": {"provider": None}}


def test_settings_clear_ai_credential(monkeypatch):
    request = {}

    def patch(path, json):
        request["body"] = json
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.settings.client.patch", patch)
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["ai.anthropic", "--clear"])

    assert result.exit_code == 0, result.output
    assert request["body"] == {"ai": {"credentials": {"anthropic": None}}}


def test_settings_clear_ai_model_id_rejected(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.commands.settings.client.patch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not patch")),
    )
    monkeypatch.setattr(
        "satori_cli.commands.settings.stderr.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["ai.model_id", "--clear"])

    assert result.exit_code != 0


def test_settings_invalid_key_exits_nonzero():
    result = CliRunner().invoke(settings, ["datadog_api_key"])
    assert result.exit_code != 0


def test_settings_invalid_default_exits_nonzero(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.commands.settings.client.patch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not patch")),
    )
    monkeypatch.setattr(
        "satori_cli.commands.settings.stderr.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["default", "datadog"])

    assert result.exit_code != 0


def test_settings_invalid_ai_provider_exits_nonzero(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.commands.settings.client.patch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not patch")),
    )
    monkeypatch.setattr(
        "satori_cli.commands.settings.stderr.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["ai.provider", "bedrock"])

    assert result.exit_code != 0


def test_settings_empty_value_rejected(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.commands.settings.client.patch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not patch")),
    )
    monkeypatch.setattr(
        "satori_cli.commands.settings.stderr.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["email", ""])

    assert result.exit_code != 0


def test_settings_clear_with_value_is_usage_error():
    result = CliRunner().invoke(settings, ["email", "x", "--clear"])
    assert result.exit_code != 0
