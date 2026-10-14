import asyncio

import pytest

from satori_cli.utils.execution.runner import TimedOut, process_commands
from satori_cli.utils.execution.models import ResultCache


class _Cache(ResultCache):
    def __init__(self):
        self.d = {}

    def store(self, path, result):
        self.d[path] = result

    def get(self, id):
        return self.d.get(id)

    def close(self):
        pass


def _lines(cmd):
    return [{"path": "cmd", "original": cmd, "testcase": {}}]


DATA = {"cmd": {"settings": {}}}


async def _run(cmd, **kw):
    return [r async for _, r in process_commands(_lines(cmd), DATA, cache_class=_Cache, **kw)]


def test_timeout_does_not_leak_into_next_run():
    async def main():
        with pytest.raises(TimedOut):
            await _run("sleep 5", timeout=1)
        # A fresh call must not inherit the previous timeout.
        (res,) = await _run("echo hi")
        assert res["stdout"].strip() == b"hi"

    asyncio.run(main())


def test_cwd_is_honored(tmp_path):
    (res,) = asyncio.run(_run("pwd", cwd=str(tmp_path)))
    assert res["stdout"].decode().strip() == str(tmp_path.resolve())
