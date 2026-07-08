from satori_cli.config import Config


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yml"
    monkeypatch.setattr(Config, "CONFIG_FILE", creds)
    cfg = Config()
    cfg.save("width", "145")
    cfg2 = Config()
    assert cfg2.get("width") == 145  # safe_load coerces "145" → int; plan 002 will change this
