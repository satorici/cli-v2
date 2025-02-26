from collections import defaultdict
from itertools import groupby
import json
from math import floor
from typing import Generic, TypeVar

from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table, Column
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
            yield json.dumps(self.obj, indent=2)
        else:
            yield from orig(self, console, options)

    cls.__rich_console__ = __rich_console__

    return cls


@has_json_output
class JobWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        yield f"Job id: {self.obj['id']}"
        yield f"Job type: {self.obj['type']}"


@has_json_output
class ExecutionWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        yield f"Execution id: {self.obj['id']}"
        yield f"Status: {self.obj['status']}"
        yield JobWrapper(self.obj["job"])
        yield "Report:"
        yield ReportWrapper(self.obj["data"]["report"]["detail"])


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
                result = "FAIL" if report["fails"] else "PASS"
            else:
                result = "N/A"

            table.add_row(
                str(execution["id"]),
                execution["status"],
                execution["visibility"],
                execution["job"]["type"],
                str(execution["job"]["id"]),
                result,
            )

        yield table


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
                status = "\n".join([str(val["status"]) for val in values])

                table.add_row(test_name, name.lstrip("assert"), expected, status)
                test_name = ""

            table.add_section()

        yield table
