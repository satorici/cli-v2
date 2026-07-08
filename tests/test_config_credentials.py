import sys

import pytest

from satori_cli.config import Config


def test_display_dict_redacts_token(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yml"
    monkeypatch.setattr(Config, "CONFIG_FILE", creds)
    cfg = Config()
    cfg.save("token", "secret")
    assert cfg.display_dict()["token"] == "***"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix permissions")
def test_save_sets_file_permissions(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yml"
    monkeypatch.setattr(Config, "CONFIG_FILE", creds)
    cfg = Config()
    cfg.save("token", "secret")
    assert oct(creds.stat().st_mode & 0o777) == "0o600"
