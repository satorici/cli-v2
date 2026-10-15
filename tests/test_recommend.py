import pytest
import yaml
from satorici.validator import validate_playbook

from satori_cli.exceptions import SatoriError
from satori_cli.mcp_server import recommend, server

REPOS = {
    "py_uv": {
        "pyproject.toml": '[project]\nname = "d"\n\n[tool.ruff]\nline-length = 100\n',
        "uv.lock": "",
        "tests/test_ok.py": "def test_ok(): ...\n",
    },
    "py_black": {
        "pyproject.toml": '[project]\nname = "d"\n\n[tool.black]\nline-length = 100\n',
        "requirements.txt": "requests\n",
    },
    "py_docker": {
        "pyproject.toml": '[project]\nname = "d"\n',
        "uv.lock": "",
        "Dockerfile": "FROM python\n",
    },
    "node_pnpm": {
        "package.json": '{"scripts": {"test": "vitest run"}, "devDependencies": {"eslint": "9"}}',
        "tsconfig.json": "{}",
        "pnpm-lock.yaml": "",
    },
    "node_npm_nolock": {
        "package.json": '{"scripts": {"test": "echo no test specified"}}'
    },
    "go": {"go.mod": "module x\n"},
    "java_maven": {"pom.xml": "<project/>"},
    "csharp": {"App.csproj": "<Project/>"},
    "rust": {"Cargo.toml": '[package]\nname = "x"\n'},
    "ruby_rails": {
        "Gemfile": 'gem "rails"\ngem "rspec-rails"\ngem "rubocop"\n',
        ".rubocop.yml": "",
    },
    "php": {
        "composer.json": (
            '{"require-dev": {"phpunit/phpunit": "^11", "phpstan/phpstan": "^2"}}'
        ),
        "phpunit.xml": "<phpunit/>",
    },
    "swift": {"Package.swift": "// swift-tools-version:6.0\n"},
    "cpp": {"CMakeLists.txt": "project(x)\n", ".clang-format": ""},
    "solidity": {"foundry.toml": "[profile.default]\n", "package.json": "{}"},
    "py_updated": {
        "pyproject.toml": '[project]\nname = "d"\n\n[tool.black]\nline-length = 100\n',
        "uv.lock": "",
        ".satori.yml": (
            "# satori:recommended v1 python/uv prefs: formatter=black dead_code=false\n"
            "settings:\n  name: mine\nlint:\n  ruff_check:\n    run:\n"
            "    - uvx --from ruff==0.17.0 ruff check --output-format=json .\n"
        ),
    },
}
EXPECTED_IDS = {
    "py_uv": {"ruff_check", "ruff_format", "pytest", "pyrefly", "pyspector"},
    "node_pnpm": {"eslint", "tsc", "node_tests", "node_audit"},
    "go": {"go_vet", "gofmt", "go_test", "govulncheck"},
    "java_maven": {"maven_test"},
    "csharp": {"dotnet_build", "dotnet_format", "dotnet_test", "dotnet_vulnerable"},
    "rust": {"clippy", "rustfmt", "cargo_test", "cargo_audit"},
    "ruby_rails": {"rubocop", "rspec", "bundler_audit", "brakeman"},
    "php": {"phpstan", "phpunit", "composer_audit"},
    "swift": {"swift_format", "swift_test"},
    "cpp": {"cppcheck", "clang_format", "ctest"},
    "solidity": {"forge_fmt", "forge_test"},
    "py_docker": {
        "ruff_check",
        "ruff_format",
        "pyrefly",
        "pyspector",
        "checkov_dockerfile",
    },
}


@pytest.fixture
def repos(tmp_path):
    for name, files in REPOS.items():
        for rel, content in files.items():
            path = tmp_path / name / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    return tmp_path


@pytest.fixture(autouse=True)
def _repos_root(repos):
    global FIXTURES
    FIXTURES = repos


def _recommend(name: str, prefs: dict | None = None):
    return recommend.build(recommend.detect(FIXTURES / name), prefs)


@pytest.mark.parametrize("name", list(EXPECTED_IDS))
def test_recommended_checks_validate(name):
    rec = _recommend(name)
    assert {c["id"] for c in rec.checks} == EXPECTED_IDS[name]
    validate_playbook(yaml.safe_load(rec.yaml))


def test_rules_use_only_the_closed_vocabulary():
    recommend.validate_rules(recommend.load_rules())


def test_rules_ship_as_package_data():
    from importlib import resources

    path = resources.files("satori_cli.mcp_server").joinpath("recommendations.yaml")
    assert path.is_file()


def test_every_rule_renders_to_a_valid_playbook():
    """Each tool, for each manager of its language, must produce a playbook the validator accepts."""
    rules = recommend.load_rules()
    for tool in rules["tools"]:
        language = "python" if tool["language"] == "dockerfile" else tool["language"]
        for manager in rules["profiles"][language]:
            profile = recommend.Profile(
                root=FIXTURES, language=language, manager=manager, pyproject="x"
            )
            install: list[str] = []
            command = recommend._render_command(profile, rules, tool, install)
            if command is None:
                continue
            validate_playbook(
                {
                    "settings": {"name": "t"},
                    "install": install or ["true"],
                    "t": {
                        "assertReturnCode": 0,
                        "setSeverity": tool["severity"],
                        "run": [command],
                    },
                }
            )


def test_existing_black_config_means_no_formatter_question():
    rec = _recommend("py_black")
    assert rec.prefs_used["formatter"] == "black"
    assert "formatter" not in {q["pref"] for q in rec.questions}
    assert "black_check" in {c["id"] for c in rec.checks}
    assert "ruff_format" not in {c["id"] for c in rec.checks}
    blocking = {c["id"] for c in rec.checks if c["blocking"]}
    assert blocking == {"black_check"}


def test_unconfigured_optional_tools_are_asked_with_defaults():
    rec = _recommend("py_docker")
    assert {q["pref"] for q in rec.questions} == {
        "formatter",
        "dead_code",
        "types",
        "security",
    }
    assert rec.prefs_used == {
        "formatter": "ruff",
        "dead_code": False,
        "types": True,
        "security": True,
    }
    assert "vulture" not in {c["id"] for c in rec.checks}


def test_explicit_prefs_are_applied_and_persisted_in_header():
    rec = _recommend("py_docker", {"formatter": "black", "dead_code": "true"})
    ids = {c["id"] for c in rec.checks}
    assert {"black_check", "vulture"} <= ids
    assert "ruff_format" not in ids
    assert (
        rec.header
        == "# satori:recommended v2 python/uv prefs: formatter=black dead_code=true"
    )
    assert {q["pref"] for q in rec.questions} == {"types", "security"}


@pytest.mark.parametrize(
    "prefs", [{"formatter": "yapf"}, {"nope": True}, {"dead_code": "maybe"}]
)
def test_invalid_prefs_are_rejected(prefs):
    with pytest.raises(SatoriError):
        _recommend("py_docker", prefs)


def test_header_round_trip():
    assert recommend.parse_header(
        "# satori:recommended v3 python/uv prefs: formatter=black dead_code=false\nx: 1\n"
    ) == (3, {"formatter": "black", "dead_code": "false"})
    assert recommend.parse_header("# satori:recommended v2 go/go\n") == (2, {})
    assert recommend.parse_header("settings: {}\n") is None


def test_update_asks_only_about_tools_newer_than_the_header(monkeypatch):
    rules = recommend.load_rules()
    previous = (1, {"formatter": "black", "dead_code": "false"})
    profile = recommend.detect(FIXTURES / "py_updated")

    rec = recommend.build(profile, None, previous)
    assert rec.questions == []

    newer = {
        **rules,
        "rules_version": 2,
        "tools": [
            {**t, "since": 2} if t["id"] == "pyrefly" else t for t in rules["tools"]
        ],
    }
    monkeypatch.setattr(recommend, "load_rules", lambda: newer)
    rec = recommend.build(profile, None, previous)
    assert [q["pref"] for q in rec.questions] == ["types"]
    assert rec.header.startswith("# satori:recommended v2 python/uv")


def test_diff_existing_reports_missing_and_keeps_present():
    root = FIXTURES / "py_updated"
    rec = recommend.build(
        recommend.detect(root),
        None,
        recommend.parse_header((root / ".satori.yml").read_text()),
    )
    changes = recommend.diff_existing((root / ".satori.yml").read_text(), rec)
    missing = {c["id"] for c in changes["missing"]}
    assert "ruff_check" not in missing
    assert {"black_check", "pyspector"} <= missing
    assert not changes["up_to_date"]
    assert "run:" in changes["missing"][0]["suggested_yaml"]


def test_no_supported_project_is_an_error(tmp_path):
    tmp_path = tmp_path / "empty"
    tmp_path.mkdir()
    with pytest.raises(SatoriError, match="No supported project"):
        recommend.detect(tmp_path)


def test_node_without_lockfile_uses_plain_install():
    rec = _recommend("node_npm_nolock")
    assert rec.install == ["npm install"]
    assert "node_tests" not in {c["id"] for c in rec.checks}


def test_on_demand_tools_are_installed_without_project_prefix():
    rec = _recommend("ruby_rails")
    assert rec.install[0] == "bundle install"
    assert {
        "gem install bundler-audit -v 0.9.3",
        "gem install brakeman -v 8.1.0",
    } <= set(rec.install)
    commands = {c["id"]: c["command"] for c in rec.checks}
    assert commands["brakeman"] == "brakeman -q -f json"
    assert commands["rubocop"] == "bundle exec rubocop --format json"


def test_foundry_wins_over_package_json():
    profile = recommend.detect(FIXTURES / "solidity")
    assert (profile.language, profile.manager) == ("solidity", "foundry")
    assert profile.other_languages == ["node"]


def test_recommend_tool_new_playbook_and_existing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = server.recommend_playbook(str(FIXTURES / "py_uv"))
    assert result["language"] == "python" and "playbook_yaml" in result
    assert "changes" not in result

    existing = server.recommend_playbook(str(FIXTURES / "py_updated"))
    assert existing["existing"] and "playbook_yaml" not in existing
    assert existing["header"].startswith("# satori:recommended v2")

    assert (
        "existing directory"
        in server.recommend_playbook(str(tmp_path / "nope"))["error"]
    )
    assert "No supported project" in server.recommend_playbook(str(empty))["error"]
