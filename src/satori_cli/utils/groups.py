import rich_click as click


class IdGroup(click.Group):
    """Click group that accepts a numeric ID before options or subcommands."""

    def __init__(self, *args, id_attr: str = "obj", **kwargs):
        self._id_attr = id_attr
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
            if (
                not getattr(ctx, self._id_attr, None)
                and not (i and args[i - 1] in valued)
                and arg not in self.commands
                and arg.isdigit()
            ):
                setattr(ctx, self._id_attr, int(arg))
            else:
                remaining.append(arg)
        return super().parse_args(ctx, remaining)
