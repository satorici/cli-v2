"""Detect a repo's stack and recommend a quality-check playbook.

The rules are data (recommendations.yaml); this module only detects, evaluates the closed set
of predicates the rules may use, and assembles the playbook. No network, no subprocesses.
"""

import json
import re
import warnings
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from satorici.validator import validate_playbook
from satorici.validator.exceptions import PlaybookValidationError

from ..exceptions import SatoriError

CATEGORIES = ("lint", "format", "types", "unit", "security")
HEADER_RE = re.compile(
    r"^#\s*satori:recommended\s+v(\d+)\s+(\S+)(?:\s+prefs:\s*(.*?))?\s*$", re.MULTILINE
)
EXISTING_PLAYBOOK = ".satori.yml"
PREDICATES = ("has_file", "has_dir", "has_dep", "pkg_script", "manager", "has_any")
LANGUAGES = (
    "python",
    "node",
    "go",
    "java",
    "csharp",
    "rust",
    "ruby",
    "php",
    "swift",
    "cpp",
    "solidity",
)
MANAGERS = {
    "go": "go",
    "csharp": "dotnet",
    "rust": "cargo",
    "ruby": "bundler",
    "php": "composer",
    "swift": "swiftpm",
    "cpp": "cmake",
    "solidity": "foundry",
}


@dataclass
class Profile:
    root: Path
    language: str
    manager: str
    other_languages: list[str] = field(default_factory=list)
    has_lockfile: bool = True
    pyproject: str = ""
    requirements: str = ""
    package_json: dict = field(default_factory=dict)
    manifest: str = ""
    composer_json: dict = field(default_factory=dict)

    # ---- predicates -------------------------------------------------------
    def has_file(self, pattern: str) -> bool:
        return any(self.root.glob(pattern))

    def has_dir(self, name: str) -> bool:
        return (self.root / name).is_dir()

    def has_dep(self, name: str) -> bool:
        pattern = re.compile(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])", re.IGNORECASE)
        if self.language == "python":
            return bool(
                pattern.search(self.pyproject) or pattern.search(self.requirements)
            )
        if self.language in ("ruby", "rust"):
            return bool(pattern.search(self.manifest))
        if self.language == "node":
            pkg = self.package_json
            return any(
                name in pkg.get(k, {}) for k in ("dependencies", "devDependencies")
            )
        if self.language == "php":
            pkg = self.composer_json
            return any(name in pkg.get(k, {}) for k in ("require", "require-dev"))
        return False

    def pkg_script(self, name: str) -> bool:
        script = (self.package_json.get("scripts") or {}).get(name)
        return bool(script) and "no test specified" not in script

    def has_pyproject_section(self, path: str) -> bool:
        return bool(
            re.search(
                rf"^\[\s*{re.escape(path)}(\.|\s*\])", self.pyproject, re.MULTILINE
            )
        )


@dataclass
class Recommendation:
    profile: Profile
    rules_version: int
    playbook: dict
    header: str
    checks: list[dict]
    questions: list[dict]
    prefs_used: dict
    notes: list[str]
    install: list[str]

    @property
    def yaml(self) -> str:
        body = yaml.safe_dump(self.playbook, sort_keys=False, width=1000)
        return f"{self.header}\n{body}"


# ---------------------------------------------------------------------------- rules
@cache
def load_rules() -> dict:
    text = (
        resources.files(__package__).joinpath("recommendations.yaml").read_text("utf-8")
    )
    rules = yaml.safe_load(text)
    validate_rules(rules)
    return rules


def _check_when(tool_id: str, when: dict) -> None:
    for key, value in when.items():
        if key not in PREDICATES:
            raise ValueError(f"{tool_id}: unknown predicate {key!r}")
        if key == "has_any":
            for sub in value:
                _check_when(tool_id, sub)


def validate_rules(rules: dict) -> None:
    """Raise ValueError if the rules use anything outside the closed vocabulary."""
    prefs = rules["prefs"]
    seen = set()
    for tool in rules["tools"]:
        tid = tool["id"]
        if tid in seen:
            raise ValueError(f"duplicate tool id {tid}")
        seen.add(tid)
        if tool["category"] not in CATEGORIES:
            raise ValueError(f"{tid}: unknown category {tool['category']!r}")
        if tool["language"] not in (*LANGUAGES, "dockerfile"):
            raise ValueError(f"{tid}: unknown language {tool['language']!r}")
        if tool["kind"] not in ("python-tool", "tool", "project"):
            raise ValueError(f"{tid}: unknown kind {tool['kind']!r}")
        if tool["kind"] in ("python-tool", "tool") and not (
            tool.get("package") and tool.get("version")
        ):
            raise ValueError(f"{tid}: {tool['kind']} needs package and version")
        if tool["kind"] == "tool":
            managers = rules["profiles"].get(tool["language"], {})
            if not managers or not all("tool_install" in m for m in managers.values()):
                raise ValueError(
                    f"{tid}: every {tool['language']} profile needs tool_install"
                )
        if not 0 <= tool["severity"] <= 5:
            raise ValueError(f"{tid}: severity must be 0-5")
        if tool["since"] > rules["rules_version"]:
            raise ValueError(f"{tid}: since is newer than rules_version")
        _check_when(tid, tool.get("when", {}))
        pref = tool.get("pref")
        if pref:
            key, value = (
                next(iter(pref.items())) if isinstance(pref, dict) else (pref, True)
            )
            if key not in prefs:
                raise ValueError(f"{tid}: unknown pref {key!r}")
            if prefs[key]["type"] == "choice" and value not in prefs[key]["choices"]:
                raise ValueError(f"{tid}: {value!r} is not a choice of {key}")
        for token in tool.get("configured_by", []):
            if token.split(":", 1)[0] not in ("file", "pyproject", "dep"):
                raise ValueError(f"{tid}: bad configured_by token {token!r}")
    for lang, managers in rules["profiles"].items():
        if lang not in LANGUAGES:
            raise ValueError(f"unknown profile language {lang!r}")
        for manager, data in managers.items():
            if "image" not in data or "run" not in data:
                raise ValueError(f"profile {lang}/{manager} needs image and run")


# ------------------------------------------------------------------------ detection
def _read(path: Path) -> str:
    try:
        return path.read_text("utf-8", errors="replace")
    except OSError:
        return ""


def detect(directory: Path) -> Profile:
    root = directory
    found: list[str] = []
    if any(
        (root / f).is_file() for f in ("pyproject.toml", "setup.py", "Pipfile")
    ) or any(root.glob("requirements*.txt")):
        found.append("python")
    # Foundry repos usually carry a package.json too; Solidity must win over Node.
    if (root / "foundry.toml").is_file():
        found.append("solidity")
    if (root / "package.json").is_file():
        found.append("node")
    if (root / "go.mod").is_file():
        found.append("go")
    if (root / "pom.xml").is_file() or any(root.glob("build.gradle*")):
        found.append("java")
    if (
        any(root.glob("*.sln"))
        or any(root.glob("*.csproj"))
        or any(root.glob("*/*.csproj"))
    ):
        found.append("csharp")
    for manifest, lang in (
        ("Cargo.toml", "rust"),
        ("Gemfile", "ruby"),
        ("composer.json", "php"),
        ("Package.swift", "swift"),
        ("CMakeLists.txt", "cpp"),
    ):
        if (root / manifest).is_file():
            found.append(lang)
    if not found:
        raise SatoriError(
            "No supported project detected (looked for Python, JS/TS, Go, Java, C#, "
            f"Rust, Ruby, PHP, Swift, C/C++ and Solidity manifests) in {root}."
        )

    language = found[0]
    profile = Profile(
        root=root, language=language, manager="", other_languages=found[1:]
    )
    profile.pyproject = _read(root / "pyproject.toml")
    profile.requirements = "\n".join(
        _read(p) for p in sorted(root.glob("requirements*.txt"))
    )
    if language == "node":
        try:
            profile.package_json = json.loads(_read(root / "package.json")) or {}
        except json.JSONDecodeError:
            raise SatoriError("package.json is not valid JSON.") from None
    elif language == "php":
        try:
            profile.composer_json = json.loads(_read(root / "composer.json")) or {}
        except json.JSONDecodeError:
            raise SatoriError("composer.json is not valid JSON.") from None
    elif language == "ruby":
        profile.manifest = _read(root / "Gemfile") + "\n" + _read(root / "Gemfile.lock")
    elif language == "rust":
        profile.manifest = _read(root / "Cargo.toml")

    if language == "python":
        uv = (root / "uv.lock").is_file() or profile.has_pyproject_section("tool.uv")
        profile.manager = "uv" if uv else "pip"
    elif language == "node":
        declared = str(profile.package_json.get("packageManager", "")).split("@")[0]
        locks = {
            "pnpm": "pnpm-lock.yaml",
            "yarn": "yarn.lock",
            "bun": "bun.lock*",
            "npm": "package-lock.json",
        }
        by_lock = next((m for m, f in locks.items() if any(root.glob(f))), None)
        profile.manager = declared if declared in locks else (by_lock or "npm")
        profile.has_lockfile = any(root.glob(locks[profile.manager]))
    elif language == "java":
        profile.manager = "maven" if (root / "pom.xml").is_file() else "gradle"
    else:
        profile.manager = MANAGERS[language]
    return profile


# ---------------------------------------------------------------------- predicates
def _eval_when(profile: Profile, when: dict) -> bool:
    for key, value in when.items():
        if key == "has_file":
            ok = profile.has_file(value)
        elif key == "has_dir":
            ok = profile.has_dir(value)
        elif key == "has_dep":
            ok = profile.has_dep(value)
        elif key == "pkg_script":
            ok = profile.pkg_script(value)
        elif key == "manager":
            ok = profile.manager in value
        else:  # has_any
            ok = any(_eval_when(profile, sub) for sub in value)
        if not ok:
            return False
    return True


def _configured(profile: Profile, tool: dict) -> bool:
    for token in tool.get("configured_by", []):
        kind, _, arg = token.partition(":")
        if kind == "file" and profile.has_file(arg):
            return True
        if kind == "pyproject" and profile.has_pyproject_section(arg):
            return True
        if kind == "dep" and profile.has_dep(arg):
            return True
    return False


# ------------------------------------------------------------------------- header
def parse_header(text: str) -> tuple[int, dict[str, str]] | None:
    """Return (rules_version, prefs) from a `# satori:recommended` header, if present."""
    match = HEADER_RE.search(text)
    if not match:
        return None
    prefs = dict(p.split("=", 1) for p in (match.group(3) or "").split() if "=" in p)
    return int(match.group(1)), prefs


def render_header(version: int, profile: Profile, prefs: dict[str, Any]) -> str:
    stack = f"{profile.language}/{profile.manager}"
    stored = " ".join(
        f"{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in prefs.items()
    )
    return f"# satori:recommended v{version} {stack}" + (
        f" prefs: {stored}" if stored else ""
    )


# ---------------------------------------------------------------------------- prefs
def _pref_tool_value(tool: dict) -> tuple[str, Any] | None:
    pref = tool.get("pref")
    if not pref:
        return None
    return next(iter(pref.items())) if isinstance(pref, dict) else (pref, True)


def _coerce(key: str, spec: dict, value: Any) -> Any:
    if spec["type"] == "bool":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("true", "false"):
            return str(value).lower() == "true"
        raise SatoriError(f"pref {key!r} must be true or false, got {value!r}.")
    if value not in spec["choices"]:
        raise SatoriError(
            f"pref {key!r} must be one of {spec['choices']}, got {value!r}."
        )
    return value


def _resolve_prefs(
    profile: Profile,
    rules: dict,
    explicit: dict,
    stored: dict,
    previous_version: int | None,
) -> tuple[dict, dict, list[dict]]:
    """Return (effective prefs, prefs to persist in the header, questions)."""
    specs = {
        k: v for k, v in rules["prefs"].items() if v["language"] == profile.language
    }
    unknown = set(explicit) - set(rules["prefs"])
    if unknown:
        raise SatoriError(
            f"Unknown prefs {sorted(unknown)}; valid: {sorted(rules['prefs'])}."
        )

    effective: dict[str, Any] = {}
    persist: dict[str, Any] = {}
    questions: list[dict] = []
    for key, spec in specs.items():
        tied = [
            t for t in rules["tools"] if (pv := _pref_tool_value(t)) and pv[0] == key
        ]
        if key in explicit:
            effective[key] = persist[key] = _coerce(key, spec, explicit[key])
            continue
        if key in stored:
            effective[key] = persist[key] = _coerce(key, spec, stored[key])
            continue

        configured = [t for t in tied if _configured(profile, t)]
        if spec["type"] == "choice":
            choices = {_pref_tool_value(t)[1] for t in configured}
            if len(choices) == 1:
                effective[key] = choices.pop()
                continue
        elif configured:
            effective[key] = True
            continue

        effective[key] = spec["default"]
        is_new = previous_version is None or any(
            t["since"] > previous_version for t in tied
        )
        if is_new:
            question = {
                "pref": key,
                "question": spec["question"],
                "default": spec["default"],
            }
            if spec["type"] == "choice":
                question["choices"] = spec["choices"]
            questions.append(question)
    return effective, persist, questions


# --------------------------------------------------------------------------- build
def _render_command(
    profile: Profile, rules: dict, tool: dict, install: list[str]
) -> str | None:
    cfg = rules["profiles"][profile.language][profile.manager]
    command = tool["command"]
    verbatim = False
    if isinstance(command, dict):
        command = command.get(profile.manager, command.get("default", ""))
        verbatim = True
    if not command:
        return None
    if "{pm}" in command:
        command = command.replace("{pm}", cfg.get("pm", ""))
        verbatim = True

    package, version = tool.get("package"), tool.get("version")
    if profile.language == "python":
        if profile.manager == "uv":
            if tool["kind"] == "python-tool":
                return cfg["tool"].format(package=package, version=version) + command
            if package and not profile.has_dep(package):
                return f"uv run --with {package}=={version} {command}"
            return f"{cfg['run']}{command}"
        if package and (tool["kind"] == "python-tool" or not profile.has_dep(package)):
            step = cfg["tool_install"].format(package=package, version=version)
            if step not in install:
                install.append(step)
        return f"{cfg['run']}{command}"
    if tool["kind"] == "tool":
        step = cfg["tool_install"].format(package=package, version=version)
        if step not in install:
            install.append(step)
        return cfg.get("tool", "") + command
    return command if verbatim else f"{cfg['run']}{command}"


def _install_steps(profile: Profile, rules: dict) -> list[str]:
    cfg = rules["profiles"][profile.language][profile.manager]
    steps = list(
        cfg["install"]
        if profile.has_lockfile
        else cfg.get("install_nolock", cfg["install"])
    )
    for key, step in (cfg.get("project_install") or {}).items():
        if (key == "requirements" and profile.requirements) or (
            key == "project" and profile.pyproject
        ):
            steps.append(step)
    return steps


def build(
    profile: Profile,
    prefs: dict | None = None,
    previous: tuple[int, dict[str, str]] | None = None,
) -> Recommendation:
    rules = load_rules()
    version = rules["rules_version"]
    previous_version, stored = previous if previous else (None, {})
    effective, persist, questions = _resolve_prefs(
        profile, rules, prefs or {}, stored, previous_version
    )

    cfg = rules["profiles"][profile.language][profile.manager]
    install = _install_steps(profile, rules)
    notes: list[str] = []
    if profile.other_languages:
        notes.append(
            f"Also detected {', '.join(profile.other_languages)}; this recommendation covers "
            f"{profile.language} only. Run recommend_playbook on the sub-directory for the rest."
        )

    groups: dict[str, dict] = {c: {} for c in CATEGORIES}
    checks: list[dict] = []
    for tool in rules["tools"]:
        language = tool["language"]
        if language == "dockerfile":
            if profile.language != "python":
                if _eval_when(profile, tool.get("when", {})):
                    notes.append(
                        f"Dockerfile found but {tool['id']} needs a Python toolchain; "
                        "run a Dockerfile linter separately."
                    )
                continue
        elif language != profile.language:
            continue
        if not _eval_when(profile, tool.get("when", {})):
            continue
        if (pv := _pref_tool_value(tool)) and effective.get(pv[0]) != pv[1]:
            continue
        command = _render_command(profile, rules, tool, install)
        if command is None:
            notes.append(f"{tool['id']} has no command for {profile.manager}; skipped.")
            continue

        blocking = bool(tool["blocking_if_present"] and _configured(profile, tool))
        entry: dict[str, Any] = {}
        if blocking:
            entry["assertReturnCode"] = 0
        entry["setSeverity"] = tool["severity"]
        entry["run"] = [command]
        groups[tool["category"]][tool["id"]] = entry
        checks.append(
            {
                "id": tool["id"],
                "category": tool["category"],
                "command": command,
                "blocking": blocking,
                "severity": tool["severity"],
                "why": tool["why"],
                "since": tool["since"],
            }
        )

    playbook: dict[str, Any] = {
        "settings": {
            "name": f"Quality checks ({profile.language}/{profile.manager})",
            "image": cfg["image"],
        }
    }
    if install:
        playbook["install"] = install
    for category in CATEGORIES:
        if groups[category]:
            playbook[category] = groups[category]

    if not any(c["blocking"] for c in checks):
        notes.append(
            "No check is blocking yet (the repo does not configure these tools): nothing "
            "fails the playbook, results only show up as findings and output."
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            validate_playbook(playbook)
    except (PlaybookValidationError, TypeError) as e:
        raise SatoriError(f"Generated playbook failed validation: {e}") from None

    return Recommendation(
        profile=profile,
        rules_version=version,
        playbook=playbook,
        header=render_header(version, profile, persist),
        checks=checks,
        questions=questions,
        prefs_used=effective,
        notes=notes,
        install=install,
    )


# ------------------------------------------------------------------------- update
def _strings(node: Any) -> set[str]:
    if isinstance(node, str):
        return {node}
    if isinstance(node, list):
        return set().union(*(_strings(n) for n in node)) if node else set()
    if isinstance(node, dict):
        return set().union(*(_strings(v) for v in node.values())) if node else set()
    return set()


def _find_test(playbook: dict, test_id: str) -> Any:
    stack: list[Any] = [playbook]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if test_id in node:
                return node[test_id]
            stack.extend(node.values())
    return None


def diff_existing(existing_text: str, rec: Recommendation) -> dict:
    """Compare an existing playbook with the recommendation; the caller does the merge."""
    try:
        existing = yaml.safe_load(existing_text) or {}
    except yaml.YAMLError as e:
        raise SatoriError(
            f"Existing {EXISTING_PLAYBOOK} is not valid YAML: {e}"
        ) from None
    if not isinstance(existing, dict):
        raise SatoriError(f"Existing {EXISTING_PLAYBOOK} must be a YAML mapping.")

    present_commands = _strings(existing)
    missing, different = [], []
    for check in rec.checks:
        wanted = rec.playbook[check["category"]][check["id"]]
        if check["command"] in present_commands:
            continue
        current = _find_test(existing, check["id"])
        fragment = yaml.safe_dump(
            {check["category"]: {check["id"]: wanted}}, sort_keys=False
        )
        if current is None:
            missing.append({**check, "suggested_yaml": fragment})
        else:
            different.append({**check, "existing": current, "suggested_yaml": fragment})
    install_missing = [s for s in rec.install if s not in present_commands]
    return {
        "missing": missing,
        "different": different,
        "install_missing": install_missing,
        "up_to_date": not (missing or different or install_missing),
    }
