from pathlib import Path

import click

from ..models import Playbook, Source
from .repo import is_github_repo, is_wildcard_repo, wildcard_owner


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

        if not Path(value).exists():
            if is_github_repo(value):
                return Source.as_repo(value)
            # A mistyped folder must not scan some GitHub owner's repositories, so
            # wildcards are only taken from --repo
            if is_wildcard_repo(value) and (owner := wildcard_owner(value)):
                self.fail(
                    f"{value!r} is not a local path. To scan every repository of "
                    f"{owner}, use --repo {owner}/*",
                    param,
                    ctx,
                )

        return super().convert(value, param, ctx)


source_arg = click.argument("source", type=_SourceParam())
run_source_arg = click.argument("source", type=_RunSourceParam(), required=False)
