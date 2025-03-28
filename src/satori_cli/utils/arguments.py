import click

from ..models import Source


class _SourceParam(click.ParamType):
    def convert(self, value: str, param, ctx):
        return Source(value)


source_arg = click.argument("source", type=_SourceParam())
