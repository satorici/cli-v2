import re
import tarfile
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Any, Literal, Optional, Union

import click
import httpx
import yaml

from ..api import client
from ..exceptions import SatoriError
from ..utils.bundler import make_bundle

VARIABLE_REGEX = re.compile(r"\${{([\w-]+)}}")


def flatten_dict(d: dict[str, Any], parent_key="") -> dict[str, Any]:
    flat_dict = {}

    for k, v in d.items():
        new_key = f"{parent_key}.{k}" if parent_key else k

        if isinstance(v, dict):
            flat_dict.update(flatten_dict(v, new_key))
        else:
            flat_dict[new_key] = v

    return flat_dict


class Playbook:
    def __init__(self, path: Union[str, Path]):
        with open(path) as f:
            self._obj: dict = yaml.safe_load(f)

        self._flat = flatten_dict(self._obj)

    @property
    def variables(self) -> set[str]:
        names: set[str] = set()

        def is_cmd_group(value):
            if isinstance(value, list) and len(value) > 0:
                if all(
                    isinstance(i, str) and not i.startswith(("file://", "satori://"))
                    for i in value
                ):
                    return True

        for key, value in self._flat.items():
            if is_cmd_group(value):
                names.update(VARIABLE_REGEX.findall("\n".join(value)))

        return names


class Source:
    type: Literal["URL", "FILE", "DIR"]
    playbook: Optional[Playbook] = None

    def __init__(self, arg: str):
        self._arg = arg
        path = Path(arg)

        if "://" in arg:
            self.type = "URL"
        elif path.is_file():
            self.type = "FILE"
            self.playbook = Playbook(path)
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
