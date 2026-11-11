from click.testing import CliRunner
from httpx2 import HTTPStatusError

from satori_cli.commands.whoami import whoami


class _Cfg:
    def __init__(self, profile: str, organization: int | None = None):
        self.profile = profile
        self._organization = organization

    def get(self, key, default=None):
        return self._organization if key == "organization" else default


class _FakeResponse:
    def __init__(self, configured: bool, profile: dict | None = None):
        self._configured = configured
        self._profile = profile

    def json(self):
        body = {"github": {"token": {"configured": self._configured}}}
        if self._profile is not None:
            body["profile"] = self._profile
        return body


class _Org:
    def json(self):
        return {"id": 7, "name": "Acme"}


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
        _Cfg("default"),
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
        _Cfg("alice"),
    )

    result = CliRunner().invoke(whoami)

    assert result.exit_code == 0, result.output
    assert printed == ["Profile: alice", "GitHub PAT: not configured"]


def _run(monkeypatch, get, cfg):
    printed = []
    monkeypatch.setattr("satori_cli.commands.whoami.client.get", get)
    monkeypatch.setattr(
        "satori_cli.commands.whoami.stdout.print",
        lambda *args: printed.append(" ".join(str(a) for a in args)),
    )
    monkeypatch.setattr("satori_cli.commands.whoami.config", cfg)
    result = CliRunner().invoke(whoami)
    assert result.exit_code == 0, result.output
    return printed


def test_whoami_shows_name_email_and_organization(monkeypatch):
    paths = []

    def get(path):
        paths.append(path)
        if path == "/organizations/7":
            return _Org()
        return _FakeResponse(True, {"name": "Ada", "email": "ada@x.io"})

    printed = _run(monkeypatch, get, _Cfg("default", 7))

    assert paths == ["/settings", "/organizations/7"]
    assert printed == [
        "Profile: default",
        "Name: Ada",
        "Email: ada@x.io",
        "Organization: Acme (7)",
        "GitHub PAT: configured",
    ]


def test_whoami_skips_missing_profile_fields(monkeypatch):
    printed = _run(
        monkeypatch,
        lambda path: _FakeResponse(True, {"name": None, "email": "ada@x.io"}),
        _Cfg("default"),
    )
    assert printed == ["Profile: default", "Email: ada@x.io", "GitHub PAT: configured"]


def test_whoami_falls_back_to_organization_id(monkeypatch):
    def get(path):
        if path == "/organizations/7":
            raise HTTPStatusError("403", request=None, response=None)
        return _FakeResponse(True)

    printed = _run(monkeypatch, get, _Cfg("default", 7))
    assert printed == ["Profile: default", "Organization: 7", "GitHub PAT: configured"]
