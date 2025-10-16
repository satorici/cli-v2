import os
import sys
from pathlib import Path

from deepmerge import always_merger
from yaml import safe_dump, safe_load


class Config:
    CONFIG_FILE = Path.home() / ".satori_credentials.yml"

    def __init__(self):
        config = {}

        self._env_config = {
            k.lstrip("SATORI_").lower(): v
            for k, v in os.environ.items()
            if k.startswith("SATORI_")
        }

        if self.CONFIG_FILE.is_file():
            config = always_merger.merge(
                config, safe_load(self.CONFIG_FILE.read_bytes())
            )

        profile = "default"

        for i, arg in enumerate(sys.argv):
            if arg == "--profile":
                profile = sys.argv[i + 1]
                break
            if arg.startswith("--profile="):
                profile = arg.split("=")[1]
                break

        if "profile" in self._env_config:
            profile = self._env_config["profile"]

        if profile:
            profile = profile

        self._config = config
        self._current_config = {}
        self.profile = profile

    def __getitem__(self, key: str):
        if key in self._env_config:
            return self._env_config[key]

        return self.get_all()[key]

    def __setitem__(self, key: str, value):
        self._current_config[key] = value

    def get(self, key: str, default=None):
        return self.get_all().get(key, default)

    def get_all(self):
        config = self._config.get("default", {})
        config = always_merger.merge(config, self._config.get(self.profile, {}))
        config = always_merger.merge(config, self._env_config)
        config = always_merger.merge(config, self._current_config)
        return config

    def save(self, key: str, value, profile="default"):
        if not self.CONFIG_FILE.is_file():
            self.CONFIG_FILE.write_text(safe_dump({}))

        config: dict = safe_load(self.CONFIG_FILE.read_bytes())
        config.setdefault(profile, {})[key] = safe_load(value)

        with open(self.CONFIG_FILE, "w") as f:
            f.write(safe_dump(config))

    def __str__(self):
        return str(self.get_all())


config = Config()
