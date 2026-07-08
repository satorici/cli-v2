from satori_cli.config import Config
from satori_cli.utils import format as format_module
from satori_cli.utils.format import get_output_format


def _isolated_config(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yml"
    monkeypatch.setattr(Config, "CONFIG_FILE", creds)
    return Config()


def test_json_flag_returns_json(tmp_path, monkeypatch):
    cfg = _isolated_config(tmp_path, monkeypatch)
    monkeypatch.setattr(format_module, "config", cfg)
    cfg["json"] = True
    assert get_output_format() == "json"


def test_format_md_returns_md(tmp_path, monkeypatch):
    cfg = _isolated_config(tmp_path, monkeypatch)
    monkeypatch.setattr(format_module, "config", cfg)
    cfg["format"] = "md"
    assert get_output_format() == "md"


def test_default_returns_rich(tmp_path, monkeypatch):
    cfg = _isolated_config(tmp_path, monkeypatch)
    monkeypatch.setattr(format_module, "config", cfg)
    assert get_output_format() == "rich"
