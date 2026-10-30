import pytest
from httpx2 import Request

from satori_cli import auth
from satori_cli.config import Config
from satori_cli.exceptions import AuthError


def _isolated_config(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yml"
    monkeypatch.setattr(Config, "CONFIG_FILE", creds)
    return Config()


def test_get_token_raises_without_token(tmp_path, monkeypatch):
    cfg = _isolated_config(tmp_path, monkeypatch)
    monkeypatch.setattr(auth, "config", cfg)
    with pytest.raises(AuthError, match="Login required"):
        auth.get_token()


def test_get_token_returns_string(tmp_path, monkeypatch):
    cfg = _isolated_config(tmp_path, monkeypatch)
    monkeypatch.setattr(auth, "config", cfg)
    cfg["token"] = "my-token"
    assert auth.get_token() == "my-token"


def _auth_headers():
    flow = auth.SatoriAuth().auth_flow(Request("GET", "https://example.com"))
    return next(flow).headers


def test_auth_sends_the_organization(tmp_path, monkeypatch):
    cfg = _isolated_config(tmp_path, monkeypatch)
    monkeypatch.setattr(auth, "config", cfg)
    cfg["token"] = "my-token"
    cfg["organization"] = 7
    assert _auth_headers()["X-Satori-Organization"] == "7"


def test_auth_without_organization(tmp_path, monkeypatch):
    cfg = _isolated_config(tmp_path, monkeypatch)
    monkeypatch.setattr(auth, "config", cfg)
    cfg["token"] = "my-token"
    assert "X-Satori-Organization" not in _auth_headers()
