import asyncio
from time import perf_counter

import pytest

from satori_cli.utils.execution.runner import TimedOut, process_commands, run_command
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


def test_stdout_streams_before_command_exits():
    async def main():
        chunks: list[tuple[float, bytes]] = []
        start = perf_counter()

        def on_stdout(chunk: bytes) -> None:
            chunks.append((perf_counter() - start, chunk))

        stop = asyncio.Event()
        cmd_timeout = asyncio.Event()
        result = await run_command(
            stop,
            cmd_timeout,
            "printf 'hola\\n'; sleep 0.3; printf 'chaudate\\n'",
            shell=True,
            on_stdout=on_stdout,
        )

        assert result["stdout"] == b"hola\nchaudate\n"
        assert chunks, "expected live stdout chunks"
        joined = b"".join(c for _, c in chunks)
        assert joined == b"hola\nchaudate\n"

        first_hola = next(t for t, c in chunks if b"hola" in c)
        first_chaudate = next(t for t, c in chunks if b"chaudate" in c)
        assert first_hola < 0.2
        assert first_chaudate >= 0.25

    asyncio.run(main())


def test_stdout_callback_optional_still_accumulates():
    data = {"cmd": {"settings": {"setShell": True}}}

    async def run():
        return [
            r
            async for _, r in process_commands(
                _lines("printf 'hi\\n'"), data, cache_class=_Cache
            )
        ]

    (res,) = asyncio.run(run())
    assert res["stdout"] == b"hi\n"
