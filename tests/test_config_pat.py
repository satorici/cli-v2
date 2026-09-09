from click.testing import CliRunner

from satori_cli.commands.config import config_


class _FakeResponse:
    def json(self):
        return {"github": {"token": {"configured": True}}}


def test_config_pat_patches_settings(monkeypatch):
    request = {}

    def patch(path, json):
        request["path"] = path
        request["body"] = json
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.config.client.patch", patch)
    monkeypatch.setattr("satori_cli.commands.config.stdout.print", lambda *args: None)

    result = CliRunner().invoke(config_, ["pat", "ghp_test_token"])

    assert result.exit_code == 0, result.output
    assert request["path"] == "/settings"
    assert request["body"] == {"github": {"token": "ghp_test_token"}}
