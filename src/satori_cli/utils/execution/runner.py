import asyncio
import logging
import os
import shlex
import signal
from asyncio import StreamReader, subprocess
from collections.abc import Callable, Iterable
from itertools import groupby
from time import perf_counter

from .models import CommandData, CommandLine, FileBasedResultCache, Result, ResultCache
from .utils import replace_results, replace_testcase

log = logging.getLogger("runner")
log.setLevel(logging.INFO)
log.addHandler(logging.StreamHandler())

OnChunk = Callable[[bytes], None]
OnCommandStart = Callable[[CommandLine], None]
OnCommandDone = Callable[[CommandLine, Result], None]


async def _drain_stream(
    stream: StreamReader | None,
    buf: bytearray,
    on_chunk: OnChunk | None,
) -> None:
    if stream is None:
        return
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        buf.extend(chunk)
        if on_chunk is not None:
            on_chunk(chunk)


async def run_command(
    stop_event: asyncio.Event,
    command_timeout_event: asyncio.Event,
    command: str,
    shell: bool | None = None,
    timeout_event: asyncio.Event | None = None,
    cwd: str | None = None,
    on_stdout: OnChunk | None = None,
    on_stderr: OnChunk | None = None,
) -> Result:
    if timeout_event is None:
        timeout_event = asyncio.Event()

    buffer_limit = 1024 * 1024 * 10

    try:
        if not shell:
            p = await subprocess.create_subprocess_exec(
                *shlex.split(command),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                limit=buffer_limit,
                cwd=cwd,
            )
        else:
            p = await subprocess.create_subprocess_shell(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                limit=buffer_limit,
                cwd=cwd,
            )
    except (OSError, ValueError) as e:
        return {
            "stdout": None,
            "stderr": None,
            "return_code": None,
            "time": None,
            "os_error": str(e),
        }

    start = perf_counter()
    stdout_buf = bytearray()
    stderr_buf = bytearray()

    p_task = asyncio.create_task(p.wait())
    stdout_task = asyncio.create_task(_drain_stream(p.stdout, stdout_buf, on_stdout))
    stderr_task = asyncio.create_task(_drain_stream(p.stderr, stderr_buf, on_stderr))

    waiters: list[asyncio.Task] = [
        p_task,
        asyncio.create_task(timeout_event.wait()),
        asyncio.create_task(command_timeout_event.wait()),
        asyncio.create_task(stop_event.wait()),
    ]

    done, pending = await asyncio.wait(waiters, return_when="FIRST_COMPLETED")

    if done != {p_task}:
        if not shell:
            p.kill()
        else:
            os.killpg(p.pid, signal.SIGKILL)

    for t in done | pending:
        t.cancel()

    await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
    return_code = await p.wait()
    time = perf_counter() - start

    return {
        "stdout": bytes(stdout_buf),
        "stderr": bytes(stderr_buf),
        "return_code": return_code,
        "time": time,
        "os_error": None,
    }


async def set_after(event: asyncio.Event, after: float):
    await asyncio.sleep(after)
    event.set()


class TimedOut(Exception): ...


class Stopped(Exception): ...


async def process_commands(
    command_lines: Iterable[CommandLine],
    commands_data: dict[str, CommandData],
    timeout: int | None = None,
    cache_class: type[ResultCache] = FileBasedResultCache,
    stop_event: asyncio.Event | None = None,
    on_running: Callable[[str], None] | None = None,
    cwd: str | None = None,
    on_stdout: OnChunk | None = None,
    on_stderr: OnChunk | None = None,
    on_command_start: OnCommandStart | None = None,
    on_command_done: OnCommandDone | None = None,
):
    if not stop_event:
        stop_event = asyncio.Event()

    # Per call: the module is reused by the long-lived MCP process.
    timeout_event = asyncio.Event()
    timeout_task = (
        asyncio.create_task(set_after(timeout_event, timeout))
        if timeout is not None
        else None
    )

    try:
        grouped = groupby(command_lines, lambda x: x["path"])
        grouped_data = ((commands_data[path], clines) for path, clines in grouped)

        def check_events():
            if stop_event.is_set():
                raise Stopped
            if timeout_event.is_set():
                raise TimedOut

        with cache_class() as result_cache:

            def build_command(cl: CommandLine):
                return replace_results(
                    replace_testcase(cl["original"], cl["testcase"]), result_cache
                )

            for data, clgroup in grouped_data:
                check_events()

                inner_timeout = data["settings"].get("setCommandTimeout")
                parallel = data["settings"].get("setParallel")
                shell = data["settings"].get("setShell")

                if parallel:
                    add_command = [((cl, build_command(cl)) for cl in clgroup)]
                else:
                    add_command = ([(cl, build_command(cl))] for cl in clgroup)

                for group_to_run in add_command:
                    command_timeout_event = asyncio.Event()
                    group_list = list(group_to_run)

                    def _stream_cbs(cline: CommandLine):
                        if not parallel or (on_stdout is None and on_stderr is None):
                            return on_stdout, on_stderr

                        def wrap(cb: OnChunk | None) -> OnChunk | None:
                            if cb is None:
                                return None

                            def prefixed(chunk: bytes) -> None:
                                cb(chunk)

                            return prefixed

                        return wrap(on_stdout), wrap(on_stderr)

                    tasks: dict[asyncio.Task[Result], CommandLine] = {}
                    for cline, command in group_list:
                        log.debug(f"Running {cline['path']}: {cline['original']}")
                        if on_running is not None:
                            on_running(cline["path"])
                        if on_command_start is not None:
                            on_command_start(cline)

                        out_cb, err_cb = _stream_cbs(cline)
                        tasks[
                            asyncio.create_task(
                                run_command(
                                    stop_event,
                                    command_timeout_event,
                                    command,
                                    shell,
                                    timeout_event,
                                    cwd,
                                    on_stdout=out_cb,
                                    on_stderr=err_cb,
                                )
                            )
                        ] = cline

                    if inner_timeout is not None:
                        asyncio.create_task(set_after(command_timeout_event, inner_timeout))

                    await asyncio.gather(*tasks)

                    for task, command_line in tasks.items():
                        result = await task

                        if data.get("cache", True):
                            result_cache.store(command_line["path"], result)

                        if on_command_done is not None:
                            on_command_done(command_line, result)

                        yield command_line, result

                    check_events()
    finally:
        if timeout_task is not None:
            timeout_task.cancel()
