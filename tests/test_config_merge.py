import sys

from yaml import safe_dump

from satori_cli.config import Config


def test_profile_overrides_default(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yml"
    creds.write_text(
        safe_dump({"default": {"width": "100"}, "test_user": {"width": "200"}})
    )
    monkeypatch.setattr(Config, "CONFIG_FILE", creds)
    monkeypatch.setattr(sys, "argv", ["satori-v2", "--profile", "test_user"])
    cfg = Config()
    assert cfg.get("width") == "200"


def test_env_overrides_file(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yml"
    creds.write_text(safe_dump({"default": {"token": "file-token"}}))
    monkeypatch.setattr(Config, "CONFIG_FILE", creds)
    monkeypatch.setenv("SATORI_TOKEN", "env-token")
    cfg = Config()
    assert cfg.get("token") == "env-token"


def test_current_config_overrides_all(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yml"
    creds.write_text(safe_dump({"default": {"format": "md"}}))
    monkeypatch.setattr(Config, "CONFIG_FILE", creds)
    cfg = Config()
    cfg["format"] = "json"
    assert cfg.get("format") == "json"
