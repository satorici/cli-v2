import importlib.metadata
import sys
from unittest.mock import MagicMock

# Package __init__ imports shards (numpy) and reads distribution metadata;
# mock both so unit tests can import Config without a full editable install.
sys.modules.setdefault("numpy", MagicMock())

_version = importlib.metadata.version


def _patched_version(distribution_name: str) -> str:
    if distribution_name == "satori-cli":
        return "0.1.0"
    return _version(distribution_name)


importlib.metadata.version = _patched_version
