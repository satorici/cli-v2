from pathlib import Path

import click

from ..api import client
from ..exceptions import SatoriError
from ..utils.bundler import make_bundle


class _SourceParam(click.ParamType):
    def convert(self, value: str, param, ctx) -> dict:
        if "://" in value:
            return {"playbook_uri": value}
        if Path(value).is_file():
            res = client.post("/bundles", files={"bundle": make_bundle(value)})
            return {"bundle_id": res.text}
        if Path(value).is_dir():
            raise SatoriError("Source not supported")


source_arg = click.argument("source", type=_SourceParam())
