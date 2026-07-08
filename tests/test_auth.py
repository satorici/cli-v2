import pytest

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
