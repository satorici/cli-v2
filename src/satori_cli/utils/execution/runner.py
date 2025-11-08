import asyncio
import logging
import os
import shlex
import signal
from asyncio import subprocess
from itertools import groupby
from time import perf_counter
from typing import Iterable

from .models import CommandData, CommandLine, FileBasedResultCache, Result, ResultCache
from .utils import replace_results, replace_testcase

log = logging.getLogger("runner")
log.setLevel(logging.INFO)
log.addHandler(logging.StreamHandler())


timeout_event = asyncio.Event()


async def run_command(
    stop_event: asyncio.Event,
    command_timeout_event: asyncio.Event,
    command: str,
    shell: bool | None = None,
) -> Result:
    buffer_limit = 1024 * 1024 * 10

    try:
        if not shell:
            p = await subprocess.create_subprocess_exec(
                *shlex.split(command),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                limit=buffer_limit,
            )
        else:
            p = await subprocess.create_subprocess_shell(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                limit=buffer_limit,
            )
    except OSError as e:
        return {
            "stdout": None,
            "stderr": None,
            "return_code": None,
            "time": None,
            "os_error": str(e),
        }

    start = perf_counter()
    p_task = asyncio.create_task(p.wait())

    tasks: list[asyncio.Task] = [
        p_task,
        asyncio.create_task(timeout_event.wait()),
        asyncio.create_task(command_timeout_event.wait()),
        asyncio.create_task(stop_event.wait()),
    ]

    done, pending = await asyncio.wait(tasks, return_when="FIRST_COMPLETED")

    if done != {p_task}:
        if not shell:
            p.kill()
        else:
            os.killpg(p.pid, signal.SIGKILL)

    for t in done | pending:
        t.cancel()

    stdout, stderr = await p.communicate()
    return_code = await p.wait()
    time = perf_counter() - start

    return {
        "stdout": stdout,
        "stderr": stderr,
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
):
    if not stop_event:
        stop_event = asyncio.Event()

    if timeout is not None:
        asyncio.create_task(set_after(timeout_event, timeout))

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

                tasks: dict[asyncio.Task[Result], CommandLine] = {
                    asyncio.create_task(
                        run_command(stop_event, command_timeout_event, command, shell)
                    ): cline
                    for cline, command in group_to_run
                }

                for _, v in tasks.items():
                    log.info(f"Running {v['path']}: {v['original']}")

                if inner_timeout is not None:
                    asyncio.create_task(set_after(command_timeout_event, inner_timeout))

                await asyncio.gather(*tasks)

                for task, command_line in tasks.items():
                    result = await task

                    if data.get("cache", True):
                        result_cache.store(command_line["path"], result)

                    yield command_line, result

                check_events()
