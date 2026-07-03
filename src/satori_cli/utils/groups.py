import rich_click as click


class IdGroup(click.Group):
    """Click group that accepts a numeric ID before options or subcommands."""

    def __init__(self, *args, id_attr: str = "obj", **kwargs):
        self._id_attr = id_attr
        super().__init__(*args, **kwargs)

    def parse_args(self, ctx, args):
        remaining = []
        for arg in args:
            if (
                not getattr(ctx, self._id_attr, None)
                and arg not in self.commands
                and arg.isdigit()
            ):
                setattr(ctx, self._id_attr, int(arg))
            else:
                remaining.append(arg)
        return super().parse_args(ctx, remaining)
