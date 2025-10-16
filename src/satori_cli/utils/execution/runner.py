import asyncio
import logging
import os
import shlex
import signal
from asyncio import subprocess
from itertools import groupby
from time import perf_counter
from typing import Iterable

from async_timeout import timeout_at

from .models import CommandData, CommandLine, FileBasedResultCache, Result, ResultCache
from .utils import replace_results, replace_testcase

log = logging.getLogger("runner")
log.setLevel(logging.INFO)
log.addHandler(logging.StreamHandler())


async def run_command(command: str, shell: bool | None = None) -> Result:
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

    try:
        return_code = await p.wait()
    except asyncio.CancelledError:
        if not shell:
            p.kill()
        else:
            os.killpg(p.pid, signal.SIGKILL)

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


async def process_commands(
    command_lines: Iterable[CommandLine],
    commands_data: dict[str, CommandData],
    timeout: int | None = None,
    cache_class: type[ResultCache] = FileBasedResultCache,
):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + int(timeout) if timeout is not None else None

    def to_deadline(timeout: int | None):
        if timeout:
            new_deadline = loop.time() + timeout
            return min(deadline, new_deadline) if deadline else new_deadline
        return deadline

    grouped = groupby(command_lines, lambda x: x["path"])
    grouped_data = ((commands_data[path], clines) for path, clines in grouped)

    with cache_class() as result_cache:

        def build_command(cl: CommandLine):
            return replace_results(
                replace_testcase(cl["original"], cl["testcase"]), result_cache
            )

        for data, clgroup in grouped_data:
            inner_timeout = data["settings"].get("setCommandTimeout")
            parallel = data["settings"].get("setParallel")
            shell = data["settings"].get("setShell")

            if parallel:
                add_command = [((cl, build_command(cl)) for cl in clgroup)]
            else:
                add_command = ([(cl, build_command(cl))] for cl in clgroup)

            for group_to_run in add_command:
                tasks: dict[asyncio.Task[Result], CommandLine] = {
                    asyncio.create_task(run_command(command, shell)): cline
                    for cline, command in group_to_run
                }

                for _, v in tasks.items():
                    log.info(f"Running {v['path']}: {v['original']}")

                try:
                    async with timeout_at(to_deadline(inner_timeout)):
                        await asyncio.gather(*tasks)
                except TimeoutError:
                    pass

                for task, command_line in tasks.items():
                    result = await task

                    if data.get("cache", True):
                        result_cache.store(command_line["path"], result)

                    yield command_line, result

                if deadline and deadline < loop.time():
                    raise TimeoutError
