import pytest

from satori_cli.commands.run import _require_first_execution_id
from satori_cli.exceptions import SatoriError


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_require_first_execution_id_returns_id(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.commands.run.client.get",
        lambda *args, **kwargs: _FakeResponse({"items": [{"id": 42}]}),
    )
    assert _require_first_execution_id(1) == 42


def test_require_first_execution_id_raises_on_empty(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.commands.run.client.get",
        lambda *args, **kwargs: _FakeResponse({"items": []}),
    )
    with pytest.raises(SatoriError, match="No executions found"):
        _require_first_execution_id(1)
