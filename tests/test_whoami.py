from click.testing import CliRunner

from satori_cli.commands.whoami import whoami


class _FakeResponse:
    def __init__(self, configured: bool):
        self._configured = configured

    def json(self):
        return {"github": {"token": {"configured": self._configured}}}


def test_whoami_shows_profile_and_configured_pat(monkeypatch):
    request = {}
    printed = []

    def get(path):
        request["path"] = path
        return _FakeResponse(True)

    monkeypatch.setattr("satori_cli.commands.whoami.client.get", get)
    monkeypatch.setattr(
        "satori_cli.commands.whoami.stdout.print",
        lambda *args: printed.append(" ".join(str(a) for a in args)),
    )
    monkeypatch.setattr(
        "satori_cli.commands.whoami.config",
        type("Cfg", (), {"profile": "default"})(),
    )

    result = CliRunner().invoke(whoami)

    assert result.exit_code == 0, result.output
    assert request["path"] == "/settings"
    assert printed == ["Profile: default", "GitHub PAT: configured"]


def test_whoami_shows_not_configured_pat(monkeypatch):
    printed = []

    monkeypatch.setattr(
        "satori_cli.commands.whoami.client.get",
        lambda path: _FakeResponse(False),
    )
    monkeypatch.setattr(
        "satori_cli.commands.whoami.stdout.print",
        lambda *args: printed.append(" ".join(str(a) for a in args)),
    )
    monkeypatch.setattr(
        "satori_cli.commands.whoami.config",
        type("Cfg", (), {"profile": "alice"})(),
    )

    result = CliRunner().invoke(whoami)

    assert result.exit_code == 0, result.output
    assert printed == ["Profile: alice", "GitHub PAT: not configured"]
