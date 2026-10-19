from pathlib import Path

import click

from ..models import Playbook, Source
from .repo import is_github_repo


RUN_PLAYBOOK_ALIASES = {
    "pyspector": "satori://code/python/pyspector_v2.yml",
    "semgrep": "satori://code/semgrep.yml",
}


class _SourceParam(click.ParamType):
    def convert(self, value: str, param, ctx):
        return Source(value)


class _RunSourceParam(_SourceParam):
    def convert(self, value: str, param, ctx):
        if playbook_uri := RUN_PLAYBOOK_ALIASES.get(value):
            source = Source("./")
            source.playbook = Playbook(playbook_uri)
            return source

        if not Path(value).exists() and is_github_repo(value):
            return Source.as_repo(value)

        return super().convert(value, param, ctx)


source_arg = click.argument("source", type=_SourceParam())
run_source_arg = click.argument("source", type=_RunSourceParam())
