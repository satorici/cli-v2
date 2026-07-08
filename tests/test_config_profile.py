import sys

from satori_cli.config import Config


def test_bare_profile_flag_defaults(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yml"
    monkeypatch.setattr(Config, "CONFIG_FILE", creds)
    monkeypatch.setattr(sys, "argv", ["satori-v2", "--profile"])
    cfg = Config()
    assert cfg.profile == "default"


def test_profile_space_form(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yml"
    monkeypatch.setattr(Config, "CONFIG_FILE", creds)
    monkeypatch.setattr(sys, "argv", ["satori-v2", "--profile", "test_user"])
    cfg = Config()
    assert cfg.profile == "test_user"


def test_profile_equals_form(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yml"
    monkeypatch.setattr(Config, "CONFIG_FILE", creds)
    monkeypatch.setattr(sys, "argv", ["satori-v2", "--profile=test_user"])
    cfg = Config()
    assert cfg.profile == "test_user"
