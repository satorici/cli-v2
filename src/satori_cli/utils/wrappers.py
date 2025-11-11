import sys
from datetime import datetime, timedelta
from itertools import groupby
from math import floor
from typing import Generic, TypeVar

from rich.console import Console, ConsoleOptions, RenderResult
from rich.highlighter import RegexHighlighter
from rich.json import JSON
from rich.panel import Panel
from rich.segment import Segment
from rich.table import Column, Table

if sys.version_info < (3, 11):
    from typing_extensions import TypedDict
else:
    from typing import TypedDict

from ..config import config

T = TypeVar("T")


class Wrapper(Generic[T]):
    def __init__(self, obj: T):
        self.obj = obj

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        raise NotImplementedError


W = TypeVar("W", bound=Wrapper)


def has_json_output(cls: type[W]):
    orig = cls.__rich_console__

    def __rich_console__(self: W, console: Console, options: ConsoleOptions):
        if config.get("json"):
            yield JSON.from_data(self.obj)
        else:
            yield from orig(self, console, options)

    cls.__rich_console__ = __rich_console__

    return cls


def command_generator(job: dict):
    job_type: str = job["type"]

    command = ["satori-v2", job_type.lower(), job["playbook_source"]]

    if job_type == "MONITOR":
        command.append(job["expression"])

    if job_type == "SCAN":
        command.append(job["repository_data"]["repository"])

    return " ".join(command)


@has_json_output
class JobWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        job = self.obj
        job_type = job["type"]

        job_grid = Table.grid(padding=(0, 2))

        if job_type != "GITHUB":
            job_grid.add_row("Command", command_generator(job))

        job_grid.add_row("Type", job_type.capitalize())
        job_grid.add_row("Playbook source", job["playbook_source"])
        job_grid.add_row("Visibility", job["visibility"].capitalize())
        job_grid.add_row("Created at", ISODateTime(job["created_at"]))

        if status := job.get("status"):
            finished_job = job_type in ("RUN", "SCAN") and status == "FINISHED"

            if finished_job and job["finished_at"]:
                job_grid.add_row("Finished at", ISODateTime(job["finished_at"]))

            job_grid.add_row("Status", status.capitalize().replace("_", " "))

            if finished_job:
                result = highlight_result("Fail" if job["failed_reports"] else "Pass")
            else:
                result = "N/A"

            if job["type"] == "RUN":
                job_grid.add_row("Execution count", str(job["count"]))
                job_grid.add_row("Result", result)

            if job["type"] == "MONITOR":
                job_grid.add_row("Schedule expression", str(job["expression"]))

        yield Panel(job_grid, title=f"Job {job['id']}", title_align="left")


class JobExecutionsWrapper(Wrapper[list]):
    def __rich_console__(self, console, options):
        table = Table(expand=True)
        table.add_column("Report id")
        table.add_column("Created at")
        table.add_column("Region")
        table.add_column("Status")
        table.add_column("Visibility")
        table.add_column("Result")

        for execution in self.obj:
            if report := execution["data"].get("report"):
                result = highlight_result("Fail" if report["fails"] else "Pass")
            else:
                result = "N/A"

            table.add_row(
                str(execution["id"]),
                ISODateTime(execution["created_at"]),
                execution["data"].get("region", "N/A"),
                execution["status"].capitalize().replace("_", " "),
                execution["visibility"].capitalize(),
                result,
            )

        yield table


def to_datetime(s: str):
    orig = s if s.endswith(("Z", "+00:00")) else s + "Z"

    try:
        return datetime.strptime(orig, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        return datetime.strptime(orig, "%Y-%m-%dT%H:%M:%S%z")


class ISODateTime(Wrapper[str]):
    def __rich_console__(self, console, options):
        yield to_datetime(self.obj).strftime("%Y-%m-%d %H:%M:%S")


class ResultHighlighter(RegexHighlighter):
    highlights = [r"(?P<green>Pass)", r"(?P<red>Fail)"]


highlight_result = ResultHighlighter()


@has_json_output
class ExecutionWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        job = self.obj["job"]
        data = self.obj["data"]
        report = self.obj["report"]

        grid = Table.grid(Column(ratio=1), Column(ratio=1), expand=True)

        execution_grid = Table.grid(padding=(0, 2))
        execution_grid.add_row("Status", self.obj["status"].capitalize())
        execution_grid.add_row("Visibility", self.obj["visibility"].capitalize())

        if region := data.get("region"):
            execution_grid.add_row("Region", region)

        execution_grid.add_row("Created at", ISODateTime(self.obj["created_at"]))

        if started_at := data.get("timestamps", {}).get("startedAt"):
            execution_grid.add_row("Started at", ISODateTime(started_at))
        if stopped_at := data.get("timestamps", {}).get("executionStoppedAt"):
            execution_grid.add_row("Stopped at", ISODateTime(stopped_at))

        job_grid = Table.grid(padding=(0, 2))
        job_grid.add_row("Type", job["type"].capitalize())
        job_grid.add_row("Visibility", job["visibility"].capitalize())
        job_grid.add_row("Created at", ISODateTime(job["created_at"]))
        job_grid.add_row("Playbook source", job["playbook_source"])

        grid.add_row(
            execution_grid,
            Panel(job_grid, title=f"Job {job['id']}", title_align="left"),
        )

        yield Panel(grid, title=f"Execution {self.obj['id']}", title_align="left")

        if report["detail"]:
            yield ReportWrapper(report["detail"])


class PagedResponse(Generic[T], TypedDict):
    total: int
    items: list[T]


@has_json_output
class PagedWrapper(Wrapper[PagedResponse[W]]):
    def __init__(self, obj, page: int, quantity: int, items_wrapper: type[W]):
        self._wrapper = items_wrapper
        self.page = page
        self.quantity = quantity
        super().__init__(obj)

    def __rich_console__(self, console, options):
        yield self._wrapper(self.obj["items"])
        yield f"Page {self.page} of {floor(self.obj['total'] / self.quantity)} | Total: {self.obj['total']}"


class ExecutionListWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        table = Table(expand=True)
        table.add_column("Id")
        table.add_column("Playbook source")
        table.add_column("Parameters")
        table.add_column("Status")
        table.add_column("Visibility")
        table.add_column("Job type")
        table.add_column("Result")
        table.add_column("Run time")
        table.add_column("Created at")

        for execution in self.obj:
            if report := execution["report"]:
                result = highlight_result("Fail" if report["total_fails"] else "Pass")
            else:
                result = "N/A"

            job = execution["job"]

            timestamps: dict[str, int] = execution["data"].get("timestamps", {})
            run_time = "N/A"

            if timestamps.get("execution_started_at") and timestamps.get(
                "execution_finished_at"
            ):
                run_time = str(
                    timedelta(
                        seconds=timestamps["execution_finished_at"]
                        - timestamps["execution_started_at"]
                    )
                )

            if job["type"] == "LOCAL" and "results_uploaded_at" in timestamps:
                run_time = str(
                    timedelta(
                        seconds=timestamps["results_uploaded_at"]
                        - to_datetime(job["created_at"]).timestamp()
                    )
                )

            parameters = ""

            if job["parameters"] is not None:
                parameters = " ".join(
                    f"{k}={','.join(v)}" for k, v in job["parameters"].items()
                )

            table.add_row(
                str(execution["id"]),
                job["playbook_source"],
                parameters,
                execution["status"].capitalize().replace("_", " "),
                execution["visibility"].capitalize(),
                job["type"].capitalize(),
                result,
                run_time,
                ISODateTime(execution["created_at"]),
            )

        yield table


@has_json_output
class ReportWrapper(Wrapper[list[dict]]):
    def __rich_console__(self, console, options):
        table = Table(
            Column("Test", ratio=1),
            Column("Assert", ratio=1),
            Column("Assert value", ratio=1),
            Column("Result", ratio=1),
            expand=True,
        )

        for detail in self.obj:
            check = "✅" if detail["test_status"] == "Pass" else "❌"
            test_name = check + " " + ":".join(detail["test"].split(" > "))
            grouped_asserts = groupby(detail["asserts"], lambda x: x["assert"])

            for name, valresults in grouped_asserts:
                values = list(valresults)
                expected = "\n".join([str(val["expected"]) for val in values])
                status = highlight_result(
                    "\n".join([str(val["status"]) for val in values])
                )

                table.add_row(test_name, name.lstrip("assert"), expected, status)
                test_name = ""

            table.add_section()

        yield table


class OutputWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        output = self.obj
        result = output["output"]

        grid = Table.grid("", "", padding=(0, 2))
        grid.add_row("[green]Command:[/green]", output["original"])
        grid.add_row("Return code:", str(result["return_code"]))

        if output["testcase"]:
            testcase = Table(
                Column(style="b"),
                Column(),
                show_header=False,
                show_edge=False,
                pad_edge=False,
            )

            for key, value in output["testcase"].items():
                testcase.add_row(key, value.decode(errors="ignore"))

            grid.add_row("Testcase:", testcase)

        if error := result["os_error"]:
            grid.add_row("Error:", error)

        grid.add_row("Time:", str(timedelta(seconds=result["time"])))

        yield grid

        yield "Stdout:"
        if stdout := result["stdout"]:
            yield Segment(stdout.decode(errors="ignore"))
            yield ""

        yield "Stderr:"
        if stderr := result["stderr"]:
            yield Segment(stderr.decode(errors="ignore"))
            yield ""
