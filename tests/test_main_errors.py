"""main(): a network timeout / connection failure becomes a clean error, not a traceback."""
import httpx2
import pytest

import satori_cli


class _Recorder:
    def __init__(self):
        self.lines = []

    def print(self, *args, **kwargs):
        self.lines.append(" ".join(str(a) for a in args))

    def print_json(self, *args, **kwargs):
        self.lines.append("json")

    @property
    def text(self):
        return "\n".join(self.lines)


@pytest.mark.parametrize("exc, word", [
    (httpx2.ConnectTimeout("x"), "timed out"),
    (httpx2.ReadTimeout("x"), "timed out"),
    (httpx2.ConnectError("x"), "failed to connect"),
])
def test_main_reports_transport_errors_cleanly(monkeypatch, exc, word):
    recorder = _Recorder()
    monkeypatch.setattr(satori_cli, "stderr", recorder)
    monkeypatch.setattr(satori_cli, "cli", lambda: (_ for _ in ()).throw(exc))
    rc = satori_cli.main()  # if the error were uncaught, this would raise instead of returning
    assert rc == 1
    assert word in recorder.text              # a plain message...
    assert type(exc).__name__ in recorder.text  # ...keeping the name so callers can retry
    assert "Traceback" not in recorder.text   # and no Python stack trace
