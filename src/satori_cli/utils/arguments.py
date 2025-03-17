import tarfile
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Literal

import click
import httpx

from ..api import client
from ..exceptions import SatoriError
from ..utils.bundler import make_bundle


class Source:
    type: Literal["URL", "FILE", "DIR"]

    def __init__(self, arg: str):
        self._arg = arg
        path = Path(arg)

        if "://" in arg:
            self.type = "URL"
        elif path.is_file():
            self.type = "FILE"
        elif path.is_dir():
            self.type = "DIR"
        else:
            raise SatoriError("Source not supported")

    def upload_files(self, data: dict):
        with SpooledTemporaryFile() as f:
            with tarfile.open(fileobj=f, mode="w:gz") as tf:
                tf.add(self._arg, ".")

            f.seek(0)
            res = httpx.post(data["url"], data=data["fields"], files={"file": f})
            res.raise_for_status()

    def playbook_data(self) -> dict[str, str]:  # type: ignore
        value = self._arg

        if self.type == "URL":
            return {"playbook_uri": value}
        elif self.type == "FILE":
            res = client.post("/bundles", files={"bundle": make_bundle(value)})
            return {"bundle_id": res.text}
        elif self.type == "DIR":
            res = client.post(
                "/bundles", files={"bundle": make_bundle(Path(value) / ".satori.yml")}
            )

            return {"bundle_id": res.text}


class _SourceParam(click.ParamType):
    def convert(self, value: str, param, ctx):
        return Source(value)


source_arg = click.argument("source", type=_SourceParam())
