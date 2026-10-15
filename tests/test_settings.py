from click.testing import CliRunner

from satori_cli.commands.settings import settings


class _FakeResponse:
    def __init__(self, payload=None):
        self._payload = payload or {}

    def json(self):
        return self._payload


NOTIFY_PAYLOAD = {
    "notify": {
        "default": "slack",
        "slack_workspace": "T123",
        "slack_channel": "C456",
        "email": "user@example.com",
        "discord": None,
        "telegram": None,
    }
}


def test_settings_lists_notify_fields(monkeypatch):
    request = {}
    printed = []

    def get(path):
        request["path"] = path
        return _FakeResponse(NOTIFY_PAYLOAD)

    monkeypatch.setattr("satori_cli.commands.settings.client.get", get)
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print",
        lambda *args, **kwargs: printed.append(args[0] if args else None),
    )

    result = CliRunner().invoke(settings)

    assert result.exit_code == 0, result.output
    assert request["path"] == "/settings"
    assert len(printed) == 1
    table = printed[0]
    keys = list(table.columns[0]._cells)
    values = list(table.columns[1]._cells)
    listed = dict(zip(keys, values))
    assert listed["default"] == "slack"
    assert listed["email"] == "user@example.com"
    assert listed["discord"] == "(not set)"
    assert listed["telegram"] == "(not set)"


def test_settings_gets_one_key(monkeypatch):
    printed = []

    monkeypatch.setattr(
        "satori_cli.commands.settings.client.get",
        lambda path: _FakeResponse(NOTIFY_PAYLOAD),
    )
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print",
        lambda *args, **kwargs: printed.append(args[0] if args else None),
    )

    result = CliRunner().invoke(settings, ["email"])

    assert result.exit_code == 0, result.output
    assert printed == ["user@example.com"]


def test_settings_gets_unset_key(monkeypatch):
    printed = []

    monkeypatch.setattr(
        "satori_cli.commands.settings.client.get",
        lambda path: _FakeResponse(NOTIFY_PAYLOAD),
    )
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print",
        lambda *args, **kwargs: printed.append(args[0] if args else None),
    )

    result = CliRunner().invoke(settings, ["telegram"])

    assert result.exit_code == 0, result.output
    assert printed == ["(not set)"]


def test_settings_sets_value(monkeypatch):
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


def test_settings_clear_sends_null(monkeypatch):
    request = {}

    def patch(path, json):
        request["path"] = path
        request["body"] = json
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.settings.client.patch", patch)
    monkeypatch.setattr(
        "satori_cli.commands.settings.stdout.print", lambda *args, **kwargs: None
    )

    result = CliRunner().invoke(settings, ["email", "--clear"])

    assert result.exit_code == 0, result.output
    assert request["path"] == "/settings"
    assert request["body"] == {"notify": {"email": None}}


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
