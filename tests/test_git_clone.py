"""git_clone.py: shallow clone, quiet, with retry on transient network failures."""
import subprocess

import pytest

from satori_cli.exceptions import SatoriError
from satori_cli.utils import git_clone
from satori_cli.utils.repo import parse_github_remote


def _result(returncode, stderr=""):
    return subprocess.CompletedProcess(["git"], returncode, "", stderr)


def _patch(monkeypatch, results):
    """Feed clone_repo a sequence of fake `git clone` results; return the calls list."""
    calls = []
    seq = iter(results)

    def run(cmd, **kwargs):
        calls.append(cmd)
        return next(seq)

    monkeypatch.setattr(git_clone.subprocess, "run", run)
    monkeypatch.setattr(git_clone.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(git_clone.shutil, "rmtree", lambda path, ignore_errors=False: None)
    return calls


def test_clone_retries_a_transient_failure_then_succeeds(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, [
        _result(128, "error: RPC failed; curl 56 Recv failure: Connection reset by peer"),
        _result(0),
    ])
    out = git_clone.clone_repo("git", "a/b", tmp_path, quiet=True)
    assert out == tmp_path / "b"
    assert len(calls) == 2  # retried once, then succeeded
    assert calls[0][:5] == ["git", "clone", "--quiet", "--depth", "1"]  # still shallow + quiet


def test_clone_does_not_retry_a_missing_repo(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, [
        _result(128, "fatal: repository 'https://github.com/a/b.git/' not found"),
        _result(0),  # would succeed, but a non-transient error must not reach a retry
    ])
    with pytest.raises(SatoriError):
        git_clone.clone_repo("git", "a/b", tmp_path, quiet=True)
    assert len(calls) == 1  # failed fast, no retry


def test_clone_gives_up_after_the_attempt_cap(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, [_result(128, "early EOF")] * 10)
    with pytest.raises(SatoriError):
        git_clone.clone_repo("git", "a/b", tmp_path, quiet=True)
    assert len(calls) == git_clone._CLONE_ATTEMPTS  # transient, but capped


@pytest.mark.parametrize(
    "url, expected",
    [
        ("git@github.com:acme/app.git", "acme/app"),
        ("git@github.com:acme/app", "acme/app"),
        ("ssh://git@github.com/acme/app.git", "acme/app"),
        ("ssh://git@github.com:22/acme/app.git", "acme/app"),
        ("https://github.com/acme/app.git", "acme/app"),
        ("https://github.com/acme/app", "acme/app"),
        ("https://github.com/acme/app/", "acme/app"),
        ("https://token@github.com/Acme/my.app.git\n", "Acme/my.app"),
        ("git://github.com/acme/app.git", "acme/app"),
        ("https://gitlab.com/acme/app.git", None),
        ("git@github.com.evil.test:acme/app.git", None),
        ("https://evil.test/github.com/acme/app", None),
        ("https://github.com/acme", None),
        ("https://github.com/acme/app/tree/main", None),
        ("/srv/git/app.git", None),
        ("", None),
    ],
)
def test_parse_github_remote(url, expected):
    assert parse_github_remote(url) == expected


def _patch_origin(monkeypatch, result, git="/bin/git"):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return result

    monkeypatch.setattr(git_clone.shutil, "which", lambda name: git)
    monkeypatch.setattr(git_clone.subprocess, "run", run)
    return calls


def test_origin_repository_reads_the_origin_remote(monkeypatch):
    done = subprocess.CompletedProcess(["git"], 0, "git@github.com:acme/app.git\n", "")
    calls = _patch_origin(monkeypatch, done)
    assert git_clone.origin_repository("/work") == "acme/app"
    assert calls == [["/bin/git", "-C", "/work", "remote", "get-url", "origin"]]


def test_origin_repository_is_none_without_an_origin(monkeypatch):
    _patch_origin(monkeypatch, _result(2, "error: No such remote 'origin'"))
    assert git_clone.origin_repository() is None


def test_origin_repository_is_none_without_git(monkeypatch):
    calls = _patch_origin(monkeypatch, _result(0), git=None)
    assert git_clone.origin_repository() is None
    assert calls == []
