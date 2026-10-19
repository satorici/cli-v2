"""git_clone.py: shallow clone, quiet, with retry on transient network failures."""
import subprocess

import pytest

from satori_cli.exceptions import SatoriError
from satori_cli.utils import git_clone


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
