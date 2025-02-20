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


class JobWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        if config.get("json"):
            yield json.dumps(self.obj, indent=2)
            return

        yield f"Job id: {self.obj['id']}"
        yield f"Job type: {self.obj['type']}"
