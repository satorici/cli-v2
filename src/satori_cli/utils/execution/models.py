from contextlib import AbstractContextManager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, TypedDict

import msgpack


class Result(TypedDict):
    stdout: bytes | None
    stderr: bytes | None
    return_code: int | None
    time: float | None
    os_error: str | None


class CommandData(TypedDict):
    settings: dict[str, Any]
    "key: setting name, value: setting value"
    asserts: dict[str, list[Any]]
    "key: assert name, value: all applicable assert values"
    cache: bool
    "Cache result to reference in future commands"


class CommandLine(TypedDict):
    path: str
    "Command group path"
    original: str
    "Playbook command as-is"
    testcase: dict[str, bytes]
    "key: variable name, value: variable value."


class ResultCache(AbstractContextManager):
    def store(self, path: str, result: Result): ...
    def get(self, id: str) -> Result | None: ...
    def close(self): ...

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class InMemoryResultCache(ResultCache):
    def __init__(self):
        self._cache: dict[str, Result] = {}

    def store(self, path: str, result: Result):
        self._cache[path] = result

    def get(self, id: str) -> Result | None:
        return self._cache.get(id.replace(".", ":"))

    def close(self):
        self._cache.clear()


class FileBasedResultCache(ResultCache):
    def __init__(self):
        self._dir = TemporaryDirectory()

    def store(self, path: str, result: Result):
        with Path(self._dir.name, path.replace(":", ".")).open("wb") as f:
            msgpack.pack(result, f)

    def get(self, id: str) -> Result | None:
        try:
            with Path(self._dir.name, id).open("rb") as f:
                return msgpack.unpack(f)  # type: ignore
        except Exception:
            return None

    def close(self):
        self._dir.cleanup()
