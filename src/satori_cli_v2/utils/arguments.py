import tarfile
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Callable

import click
import httpx

from ..api import client
from ..exceptions import SatoriError
from ..utils.bundler import make_bundle


class _SourceParam(click.ParamType):
    def convert(self, value: str, param, ctx) -> Callable[[], dict]:
        def playbook_data_provider():
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

                def upload_data(data: dict):
                    with SpooledTemporaryFile() as f:
                        with tarfile.open(fileobj=f, mode="w:gz") as tf:
                            tf.add(path, ".")

                        f.seek(0)
                        res = httpx.post(
                            data["url"], data=data["fields"], files={"file": f}
                        )
                        res.raise_for_status()

                return {"bundle_id": res.text, "upload_data": upload_data}
            else:
                raise SatoriError("Source not supported")

        return playbook_data_provider


source_arg = click.argument("source", type=_SourceParam())
