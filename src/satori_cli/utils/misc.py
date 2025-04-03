from collections.abc import Mapping


def remove_none_values(d: Mapping):
    return {k: v for k, v in d.items() if v is not None}
