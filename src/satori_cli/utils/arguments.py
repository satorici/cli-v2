import click

from ..models import Playbook, Source


RUN_PLAYBOOK_ALIASES = {
    "pyspector": "satori://code/python/pyspector.yml",
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

        return super().convert(value, param, ctx)


source_arg = click.argument("source", type=_SourceParam())
run_source_arg = click.argument("source", type=_RunSourceParam())
