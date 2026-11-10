from pathlib import Path

from click.testing import CliRunner

from satori_cli.commands.local import local
from tests.ids import pid

EXECUTION_ID = pid("exec", 100)


class _FakeResponse:
    def __init__(self, data=None, content=b"", status_code=200):
        self._data = data
        self.content = content
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeTempDir:
    def __init__(self, path: Path):
        self.name = str(path)
        path.mkdir(parents=True, exist_ok=True)

    def cleanup(self):
        return None


LOCAL_CREATE = {
    "id": pid("job", 50),
    "type": "LOCAL",
    "visibility": "PRIVATE",
    "created_at": "2026-01-01T00:00:00Z",
    "playbook_source": "bundle://abc",
    "status": "WAITING_RESULTS",
    "repository": "acme/app",
    "recipe_url": "https://example.test/recipe",
    "settings_url": "https://example.test/settings",
    "results_upload": {
        "url": "https://example.test/upload",
        "fields": {"key": "value"},
    },
}


def test_local_verify_requires_repo(tmp_path):
    playbook = tmp_path / "playbook.yml"
    playbook.write_text("{ cmd: [echo hi] }\n")
    result = CliRunner().invoke(local, ["--verify", str(playbook)])
    assert result.exit_code != 0
    assert "--verify requires --repo" in result.output


def _fake_local_run(monkeypatch):
    """Fake the API, the bundle upload and the command runner; return (posts, chdirs)."""
    posts: list[dict] = []
    chdirs: list[str] = []

    def fake_post(path, json=None, **kwargs):
        posts.append({"path": path, "json": json})
        assert path == "/jobs/locals"
        return _FakeResponse(LOCAL_CREATE)

    def fake_client_get(path, params=None, **kwargs):
        if path == "/executions":
            return _FakeResponse({"items": [{"id": EXECUTION_ID}]})
        if path == f"/executions/{EXECUTION_ID}":
            return _FakeResponse(
                {"id": EXECUTION_ID, "report": {"total_fails": 0, "detail": {}}}
            )
        raise AssertionError(f"Unexpected GET {path}")

    monkeypatch.setattr("satori_cli.utils.local_run.client.post", fake_post)
    monkeypatch.setattr("satori_cli.utils.local_run.client.get", fake_client_get)
    monkeypatch.setattr(
        "satori_cli.models.BundleCache.get_bundle_id",
        lambda *_a, **_k: "cached-bundle",
    )
    monkeypatch.setattr(
        "satori_cli.utils.local_run.httpx2.get",
        lambda url: _FakeResponse(
            data={} if "settings" in url else None, content=b""
        ),
    )
    monkeypatch.setattr(
        "satori_cli.utils.local_run.httpx2.post",
        lambda *a, **k: _FakeResponse(),
    )
    monkeypatch.setattr(
        "satori_cli.utils.local_run.msgpack.Unpacker",
        lambda *_a, **_k: iter([]),
    )

    async def fake_process_commands(*_a, **k):
        chdirs.append(k.get("cwd"))
        if False:
            yield None

    monkeypatch.setattr(
        "satori_cli.utils.local_run.process_commands",
        fake_process_commands,
    )
    return posts, chdirs


def _no_clone(monkeypatch):
    def fail(*_a, **_k):
        raise AssertionError("a detected repository must not be cloned")

    monkeypatch.setattr("satori_cli.commands.local.require_git", fail)
    monkeypatch.setattr("satori_cli.commands.local.clone_repo", fail)


def test_local_posts_the_origin_repository_of_the_working_directory(
    monkeypatch, tmp_path
):
    (tmp_path / ".satori.yml").write_text("{ cmd: [echo hi] }\n")
    posts, chdirs = _fake_local_run(monkeypatch)
    _no_clone(monkeypatch)
    inspected: list = []

    def fake_origin(directory):
        inspected.append(directory)
        return "acme/app"

    monkeypatch.setattr("satori_cli.commands.local.origin_repository", fake_origin)

    result = CliRunner().invoke(local, [str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert posts[0]["json"]["repository"] == "acme/app"
    assert inspected == [str(tmp_path)]
    assert chdirs == [str(tmp_path)]


def test_local_playbook_file_uses_the_current_directory_origin(monkeypatch, tmp_path):
    playbook = tmp_path / "playbook.yml"
    playbook.write_text("{ cmd: [echo hi] }\n")
    posts, _ = _fake_local_run(monkeypatch)
    _no_clone(monkeypatch)
    inspected: list = []

    def fake_origin(directory):
        inspected.append(directory)
        return "acme/app"

    monkeypatch.setattr("satori_cli.commands.local.origin_repository", fake_origin)

    result = CliRunner().invoke(local, [str(playbook)])

    assert result.exit_code == 0, result.output
    assert posts[0]["json"]["repository"] == "acme/app"
    assert inspected == [None]


def test_local_without_an_origin_posts_no_repository(monkeypatch, tmp_path):
    playbook = tmp_path / "playbook.yml"
    playbook.write_text("{ cmd: [echo hi] }\n")
    posts, _ = _fake_local_run(monkeypatch)
    monkeypatch.setattr(
        "satori_cli.commands.local.origin_repository", lambda directory: None
    )

    result = CliRunner().invoke(local, [str(playbook)])

    assert result.exit_code == 0, result.output
    assert posts[0]["json"]["repository"] is None


def test_local_repo_clones_and_posts_repository(monkeypatch, tmp_path):
    playbook = tmp_path / "playbook.yml"
    playbook.write_text("{ cmd: [echo hi] }\n")

    posts, chdirs = _fake_local_run(monkeypatch)
    clone_calls: list[dict] = []
    verify_calls: list[int] = []

    monkeypatch.setattr(
        "satori_cli.commands.local.origin_repository",
        lambda directory: "other/detected",
    )
    monkeypatch.setattr(
        "satori_cli.commands.local.require_git",
        lambda: "/bin/git",
    )

    def fake_clone(git, repository, dest):
        clone_calls.append(
            {"git": git, "repository": repository, "dest": str(dest)}
        )
        clone_dir = dest / "app"
        clone_dir.mkdir(parents=True, exist_ok=True)
        return clone_dir

    monkeypatch.setattr("satori_cli.commands.local.clone_repo", fake_clone)
    monkeypatch.setattr(
        "satori_cli.commands.local.tempfile.TemporaryDirectory",
        lambda prefix="": _FakeTempDir(tmp_path / "clone"),
    )

    def fake_verify(execution_id, min_severity=None):
        verify_calls.append(execution_id)

    monkeypatch.setattr(
        "satori_cli.commands.local._verify_execution",
        fake_verify,
    )
    monkeypatch.setattr(
        "satori_cli.commands.local.list_issues",
        lambda **kwargs: None,
    )

    result = CliRunner().invoke(
        local,
        [str(playbook), "--repo", "acme/app", "--issues", "--verify"],
    )

    assert result.exit_code == 0, result.output
    assert posts[0]["json"]["repository"] == "acme/app"
    assert clone_calls == [
        {
            "git": "/bin/git",
            "repository": "acme/app",
            "dest": str(tmp_path / "clone"),
        }
    ]
    assert any(Path(p).name == "app" for p in chdirs)
    assert verify_calls == [EXECUTION_ID]
