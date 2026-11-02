import pytest
from click.testing import CliRunner
from httpx2 import HTTPStatusError

from satori_cli.commands.config import config_
from satori_cli.config import config

ORGANIZATIONS = [{"id": 7, "name": "Acme"}]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def requests(monkeypatch) -> list:
    for attr in ("_env_config", "_current_config"):
        monkeypatch.setattr(config, attr, {})
    # a saved organization, so we can check lookups are made on your own account
    monkeypatch.setattr(config, "_config", {"default": {"organization": 3}})
    requests = []

    def get(path, **kwargs):
        requests.append((path, config.get("organization")))
        if path == "/organizations":
            return _FakeResponse(ORGANIZATIONS)
        if path in ("/organizations/3", "/organizations/7"):
            return _FakeResponse({"id": int(path.rsplit("/", 1)[1]), "name": "Acme"})
        raise HTTPStatusError("not found", request=None, response=None)

    monkeypatch.setattr("satori_cli.commands.config.client.get", get)
    return requests


@pytest.fixture
def saved(monkeypatch) -> list:
    saved = []
    monkeypatch.setattr(
        config, "save", lambda key, value, profile: saved.append((key, value, profile))
    )
    return saved


def test_config_organization_by_id(requests, saved):
    result = CliRunner().invoke(config_, ["organization", "7"])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations/7", None)]
    assert saved == [("organization", "7", "default")]
    assert "Using organization 7 (Acme) by default" in result.output


def test_config_organization_by_name(requests, saved):
    result = CliRunner().invoke(config_, ["organization", "acme"])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations", None), ("/organizations/7", None)]
    assert saved == [("organization", "7", "default")]


def test_config_organization_unknown_name(requests, saved):
    result = CliRunner().invoke(config_, ["organization", "Nope"])

    assert result.exit_code == 2
    assert "no organization named 'Nope'" in result.output
    assert saved == []


@pytest.mark.parametrize("value", ["none", "personal"])
def test_config_organization_none(requests, saved, value):
    result = CliRunner().invoke(config_, ["organization", value])

    assert result.exit_code == 0, result.output
    assert requests == []
    assert saved == [("organization", "null", "default")]


def test_config_organization_per_profile(requests, saved):
    result = CliRunner().invoke(config_, ["organization", "7", "--profile", "work"])

    assert result.exit_code == 0, result.output
    assert saved == [("organization", "7", "work")]


def test_config_organization_shows_the_name(requests):
    result = CliRunner().invoke(config_, ["organization"])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations/3", None)]
    assert "3 (Acme)" in result.output


def test_config_organization_shows_your_own_account(monkeypatch, requests):
    monkeypatch.setattr(config, "_config", {})

    result = CliRunner().invoke(config_, ["organization"])

    assert result.exit_code == 0, result.output
    assert requests == []
    assert "Using your own account" in result.output


def test_config_organization_shows_an_unknown_one(monkeypatch, requests):
    monkeypatch.setattr(config, "_config", {"default": {"organization": 9}})

    result = CliRunner().invoke(config_, ["organization"])

    assert result.exit_code == 0, result.output
    assert "9" in result.output
