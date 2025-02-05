from collections.abc import Generator
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import yaml


def dump_file_uris(playbook_obj: dict) -> Generator[str, None, None]:
    for value in playbook_obj.values():
        if isinstance(value, dict):
            yield from dump_file_uris(value)
        elif isinstance(value, list):
            if len(value) == 1 and isinstance(value[0], list):
                yield from (
                    i["file"] for i in value[0] if isinstance(i, dict) and i.get("file")
                )
            elif all(
                isinstance(i, str) and i.startswith(("file://", "satori://"))
                for i in value
            ):
                yield from (i for i in value if i.startswith("file://"))


def make_bundle(playbook_path: str) -> bytes:
    with open(playbook_path, "rb") as f:
        playbook_raw = f.read()
        playbook_obj = yaml.safe_load(playbook_raw)

    playbook_dir = Path(playbook_path).parent

    with BytesIO() as obj:
        with ZipFile(obj, "x") as zf:
            zf.writestr(".satori.yml", playbook_raw)

            for path in dump_file_uris(playbook_obj):
                path = path.lstrip("file://")
                zf.write(playbook_dir / path, path)

        return obj.getvalue()
