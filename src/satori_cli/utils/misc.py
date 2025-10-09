from collections.abc import Mapping
from typing import Optional

from ..api import client
from .console import stdout


def remove_none_values(d: Mapping):
    return {k: v for k, v in d.items() if v is not None}


def list_jobs(page: int, quantity: int, type: Optional[str], visibility: Optional[str]):
    params = {k: v for k, v in locals().items() if v is not None}

    res = client.get("/jobs", params=params)
    stdout.print_json(res.text)
