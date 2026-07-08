import pytest

from satori_cli.config import Config


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("abc123", "secret"),
    ],
)
def test_save_preserves_string_values(tmp_path, monkeypatch, value, key):
    creds = tmp_path / "creds.yml"
    monkeypatch.setattr(Config, "CONFIG_FILE", creds)
    cfg = Config()
    cfg.save(key, value)
    cfg2 = Config()
    assert cfg2.get(key) == value
    assert isinstance(cfg2.get(key), str)
