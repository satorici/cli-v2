import tarfile
from pathlib import Path
from tempfile import SpooledTemporaryFile

import click
import httpx

from ..api import client
from ..exceptions import SatoriError
from ..utils.bundler import make_bundle


class Source:
    def __init__(self, arg: str):
        self._arg = arg
        self.is_dir = Path(arg).is_dir()

    def upload_files(self, data: dict):
        with SpooledTemporaryFile() as f:
            with tarfile.open(fileobj=f, mode="w:gz") as tf:
                tf.add(self._arg, ".")

            f.seek(0)
            res = httpx.post(data["url"], data=data["fields"], files={"file": f})
            res.raise_for_status()

    def playbook_data(self) -> dict:
        value = self._arg

        if "://" in value:
            return {"playbook_uri": value}

        path = Path(value)

        if path.is_file():
            res = client.post("/bundles", files={"bundle": make_bundle(value)})
            return {"bundle_id": res.text}
        elif path.is_dir():
            res = client.post(
                "/bundles", files={"bundle": make_bundle(path / ".satori.yml")}
            )

            return {"bundle_id": res.text}
        else:
            raise SatoriError("Source not supported")


class _SourceParam(click.ParamType):
    def convert(self, value: str, param, ctx):
        return Source(value)


source_arg = click.argument("source", type=_SourceParam())
