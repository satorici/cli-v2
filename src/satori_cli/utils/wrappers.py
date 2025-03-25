from datetime import datetime
from itertools import groupby
from math import floor
from typing import Generic, TypeVar

from rich.console import Console, ConsoleOptions, RenderResult
from rich.highlighter import RegexHighlighter
from rich.json import JSON
from rich.panel import Panel
from rich.segment import Segment
from rich.table import Column, Table
from typing_extensions import TypedDict

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


@has_json_output
class JobWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        job = self.obj

        job_grid = Table.grid(padding=(0, 2))
        job_grid.add_row("Type", job["type"].capitalize())
        job_grid.add_row("Visibility", job["visibility"].capitalize())
        job_grid.add_row("Created at", ISODateTime(job["created_at"]))

        if status := job.get("status"):
            job_grid.add_row("Status", status.capitalize())

            if job["type"] in ("RUN", "SCAN") and status == "FINISHED":
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
                execution["status"].capitalize(),
                execution["visibility"].capitalize(),
                result,
            )

        yield table


class ISODateTime(Wrapper[str]):
    def __rich_console__(self, console, options):
        if self.obj.endswith(("Z", "+00:00")):
            orig = self.obj
        else:
            orig = self.obj + "Z"

        try:
            dt = datetime.strptime(orig, "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            dt = datetime.strptime(orig, "%Y-%m-%dT%H:%M:%S%z")

        yield dt.strftime("%Y-%m-%d %H:%M:%S")


class ResultHighlighter(RegexHighlighter):
    highlights = [r"(?P<green>Pass)", r"(?P<red>Fail)"]


highlight_result = ResultHighlighter()


@has_json_output
class ExecutionWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        job = self.obj["job"]
        data = self.obj["data"]

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

        grid.add_row(
            execution_grid,
            Panel(job_grid, title=f"Job {job['id']}", title_align="left"),
        )

        yield Panel(grid, title=f"Execution {self.obj['id']}", title_align="left")

        if report := data["report"]["detail"]:
            yield ReportWrapper(report)


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
        yield f"Page {self.page} of {floor(self.obj['total'] / self.quantity)}"


class ExecutionListWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        table = Table(expand=True)
        table.add_column("Id")
        table.add_column("Status")
        table.add_column("Visibility")
        table.add_column("Job type")
        table.add_column("Job id")
        table.add_column("Result")

        for execution in self.obj:
            if report := execution["data"].get("report"):
                result = highlight_result("Fail" if report["fails"] else "Pass")
            else:
                result = "N/A"

            table.add_row(
                str(execution["id"]),
                execution["status"].capitalize(),
                execution["visibility"].capitalize(),
                execution["job"]["type"].capitalize(),
                str(execution["job"]["id"]),
                result,
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

        yield grid

        yield "Stdout:"
        if stdout := result["stdout"]:
            yield Segment(stdout.decode(errors="ignore"))
            yield ""

        yield "Stderr:"
        if stderr := result["stderr"]:
            yield Segment(stderr.decode(errors="ignore"))
            yield ""
