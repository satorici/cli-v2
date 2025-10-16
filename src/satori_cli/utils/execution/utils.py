import re
from collections.abc import Callable
from typing import Literal

from .models import ResultCache

RESULT_REF_PATTERN = re.compile(
    r"\${{[\w]+(?:\.[\w]+)*\.(?:std(?:out|err)(?:\.strip\(\))?|return_code)}}"
)


Field = Literal["stdout", "stderr", "return_code"]


def parse_result_ref(ref: str) -> tuple[str, Field, str | None]:
    parts = ref[3:-2].split(".")
    y, z = parts[-2:]

    if y in ("stdout", "stderr"):
        return ".".join(parts[:-2]), y, z
    elif z in ("stdout", "stderr", "return_code"):
        return ".".join(parts[:-1]), z, None
    else:
        raise Exception("Bad ref format")


OPERATIONS: dict[str, Callable[[str], str]] = {
    "strip()": lambda x: x.strip(),
}


def replace_result(
    orig: str, ref: str, value: bytes | int | None, operation: str | None
):
    if value is None:
        return orig.replace(ref, "")

    if isinstance(value, bytes):
        replace = value.decode(errors="ignore")
    else:
        replace = str(value)

    if operation and operation in OPERATIONS:
        replace = OPERATIONS[operation](replace)

    return orig.replace(ref, replace)


def replace_results(orig: str, result_cache: ResultCache) -> str:
    for ref in set(RESULT_REF_PATTERN.findall(orig)):
        path, result_field, operation = parse_result_ref(ref)

        if result := result_cache.get(path):
            orig = replace_result(orig, ref, result[result_field], operation)

    return orig


def replace_testcase(orig: str, testcase: dict[str, bytes]) -> str:
    for name, value in testcase.items():
        orig = orig.replace("${{%s}}" % name, value.decode(errors="ignore"))

    return orig
