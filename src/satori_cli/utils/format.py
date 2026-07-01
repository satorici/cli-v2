from typing import Literal

from ..config import config

OutputFormat = Literal["rich", "json", "md"]


def get_output_format() -> OutputFormat:
    if config.get("json") or config.get("format") == "json":
        return "json"
    if config.get("format") == "md":
        return "md"
    return "rich"


def is_json_output() -> bool:
    return get_output_format() == "json"
