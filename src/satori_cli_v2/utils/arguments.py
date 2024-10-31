from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import click

from ..api import client
from ..exceptions import SatoriError


class _SourceParam(click.ParamType):
    def convert(self, value: str, param, ctx) -> dict:
        if "://" in value:
            return {"playbook_uri": value}
        if Path(value).is_file():
            with BytesIO() as obj:
                with ZipFile(obj, "x") as zf:
                    zf.writestr(".satori.yml", Path(value).read_bytes())

                obj.seek(0)

                res = client.post("/bundles", files={"bundle": obj})
                return {"bundle_id": res.text}
        if Path(value).is_dir():
            raise SatoriError("Source not supported")


source_arg = click.argument("source", type=_SourceParam())
