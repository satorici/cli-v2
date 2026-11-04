import rich_click as click


class IdGroup(click.Group):
    """Click group that takes an ID before its options or subcommand.

    The first positional argument before the subcommand is the ID, converted (and
    validated) with ``id_type``; arguments after the subcommand belong to it.
    """

    def __init__(
        self, *args, id_attr: str = "obj", id_type: click.ParamType = click.INT, **kwargs
    ):
        self._id_attr = id_attr
        self._id_type = id_type
        super().__init__(*args, **kwargs)

    def parse_args(self, ctx, args):
        # options taking a value, so that value (e.g. `--org 7`) is never read as the ID
        valued = {
            opt
            for param in self.params
            if isinstance(param, click.Option) and not param.is_flag and not param.count
            for opt in param.opts
        }
        remaining = []
        for i, arg in enumerate(args):
            if arg in self.commands:
                remaining.extend(args[i:])
                break
            if (
                getattr(ctx, self._id_attr, None) is None
                and not arg.startswith("-")
                and not (i and args[i - 1] in valued)
            ):
                setattr(ctx, self._id_attr, self._id_type.convert(arg, None, ctx))
            else:
                remaining.append(arg)
        return super().parse_args(ctx, remaining)
