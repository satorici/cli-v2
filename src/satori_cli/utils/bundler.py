from collections.abc import Generator
from io import BytesIO
from pathlib import Path
from typing import Union

import yaml
from repro_zipfile import ReproducibleZipFile as ZipFile


def dump_file_uris(playbook_obj: dict) -> Generator[str, None, None]:
    for value in playbook_obj.values():
        if isinstance(value, dict):
            yield from dump_file_uris(value)
        elif isinstance(value, list):
            if len(value) == 1 and isinstance(value[0], list):
                yield from (
                    i["file"]
                    for i in value[0]
                    if isinstance(i, dict)
                    and isinstance(i.get("file"), str)
                    and i["file"].startswith("file://")
                )
            elif all(
                isinstance(i, str) and i.startswith(("file://", "satori://"))
                for i in value
            ):
                yield from (i for i in value if i.startswith("file://"))


def make_bundle(playbook_path: Union[str, Path]) -> bytes:
    with open(playbook_path, "rb") as f:
        playbook_raw = f.read()
        playbook_obj = yaml.safe_load(playbook_raw)

    playbook_dir = Path(playbook_path).parent
    # Imported playbooks may import other files too; follow them
    pending = [playbook_obj]

    with BytesIO() as obj:
        with ZipFile(obj, "x") as zf:
            zf.writestr(".satori.yml", playbook_raw)

            while pending:
                current = pending.pop()

                if not isinstance(current, dict):
                    continue

                for path in dump_file_uris(current):
                    path = path[7:]

                    if path in zf.namelist():
                        continue

                    zf.write(playbook_dir / path, path)

                    if path.endswith((".yml", ".yaml")):
                        try:
                            pending.append(
                                yaml.safe_load((playbook_dir / path).read_bytes())
                            )
                        except yaml.YAMLError:
                            pass

        return obj.getvalue()
