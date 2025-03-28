import os
import re
import tarfile
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Any, Literal, Optional, TypedDict, Union

import httpx
import yaml

from .api import client
from .exceptions import SatoriError
from .utils.bundler import make_bundle

VARIABLE_REGEX = re.compile(r"\${{([\w-]+)}}")


class PlaybookData(TypedDict, total=False):
    playbook_uri: str
    bundle_id: str


Inputs = dict[str, list[str]]


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
        self._path = path

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

    def playbook_data(self) -> PlaybookData:
        res = client.post("/bundles", files={"bundle": make_bundle(self._path)})
        return {"bundle_id": res.text}

    def get_inputs_from_env(self, inputs: Optional[Inputs] = None) -> Optional[Inputs]:
        """Gets playbook variables values from environment variables

        Args:
            inputs: Merge with given inputs

        Returns:
            None: If no variables are found
        """

        env_params = {k: [v] for k, v in os.environ.items() if k in self.variables}

        if inputs and env_params | inputs:
            return env_params | inputs

        if env_params:
            return env_params


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
            playbook_path = path / ".satori.yml"

            if playbook_path.is_file():
                self.playbook = Playbook(playbook_path)
        else:
            raise SatoriError("Source not supported")

    def upload_files(self, data: dict):
        ignore_file = Path(self._arg, ".satorignore")

        if ignore_file.is_file():
            ignore_list = tuple(i for i in ignore_file.read_text().splitlines() if i)
        else:
            ignore_list = None

        def tar_filter(info: tarfile.TarInfo):
            if ignore_list and info.path != ".":
                if info.path.removeprefix("./").startswith(ignore_list):
                    return None

            return info

        with SpooledTemporaryFile() as f:
            with tarfile.open(fileobj=f, mode="w:gz") as tf:
                tf.add(self._arg, ".", filter=tar_filter)

            f.seek(0)
            res = httpx.post(data["url"], data=data["fields"], files={"file": f})
            res.raise_for_status()

    def playbook_data(self) -> PlaybookData:
        if self.type == "URL":
            return {"playbook_uri": self._arg}
        elif self.playbook:
            return self.playbook.playbook_data()
        else:
            raise SatoriError("No playbook provided")
