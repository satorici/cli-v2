import json
from typing import Generic, TypeVar

from rich.console import Console, ConsoleOptions, RenderResult

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
        yield "Report: " + json.dumps(self.obj["data"]["report"], indent=2)
