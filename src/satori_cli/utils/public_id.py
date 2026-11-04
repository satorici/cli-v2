"""Public IDs of jobs, executions, findings and advisories: 21 chars of 0-9A-Za-z.

The API no longer accepts the old integer IDs (they get 404), so a malformed ID is
rejected here, before any request.
"""

import re

import rich_click as click

_PUBLIC_ID_RE = re.compile(r"[0-9A-Za-z]{21}")
EXAMPLE_ID = "V1StGXR8Z5jdHi6BmyT7k"


def is_public_id(value: str) -> bool:
    return _PUBLIC_ID_RE.fullmatch(value) is not None


class PublicIdParam(click.ParamType):
    name = "ID"

    def __init__(self, label: str):
        self.label = label

    def convert(self, value, param, ctx) -> str:
        if isinstance(value, str) and is_public_id(value):
            return value
        self.fail(
            f"{value!r} is not a valid {self.label} ID: IDs are 21 letters and "
            f"digits, e.g. {EXAMPLE_ID}",
            param,
            ctx,
        )


EXECUTION_ID = PublicIdParam("execution")
JOB_ID = PublicIdParam("job")
FINDING_ID = PublicIdParam("finding")
ADVISORY_ID = PublicIdParam("advisory")
