"""Tests for CLI --notify spec parsing."""

import pytest

from satori_cli.utils.notify import NotifySpecError, parse_notify_spec, parse_notify_specs


def test_parse_full_spec_with_status_ignored():
    assert parse_notify_spec(
        "status=TP,severity=blocker,critical,high,result=fail,to=slack://ID1:ID2"
    ) == {
        "result": "fail",
        "severity": ["blocker", "critical", "high"],
        "to": "slack://ID1:ID2",
    }


def test_parse_pass_without_severity():
    assert parse_notify_spec("result=pass,to=email://security@example.com") == {
        "result": "pass",
        "to": "email://security@example.com",
    }


def test_parse_slash_slack_uri():
    assert parse_notify_spec("result=fail,to=slack://T123/C456") == {
        "result": "fail",
        "to": "slack://T123/C456",
    }


def test_parse_case_insensitive_keys_and_values():
    assert parse_notify_spec("RESULT=FAIL,SEVERITY=HIGH,TO=slack://T:C") == {
        "result": "fail",
        "severity": ["high"],
        "to": "slack://T:C",
    }


def test_parse_omitted_result():
    assert parse_notify_spec("to=slack://T:C") == {"to": "slack://T:C"}


def test_parse_rejects_missing_to():
    with pytest.raises(NotifySpecError, match="to="):
        parse_notify_spec("result=fail")


def test_parse_rejects_bad_result():
    with pytest.raises(NotifySpecError, match="result"):
        parse_notify_spec("result=always,to=slack://T:C")


def test_parse_rejects_bad_severity():
    with pytest.raises(NotifySpecError, match="severity"):
        parse_notify_spec("result=fail,severity=urgent,to=slack://T:C")


def test_parse_rejects_unknown_key():
    with pytest.raises(NotifySpecError, match="unknown"):
        parse_notify_spec("channel=slack,result=fail,to=slack://T:C")


def test_parse_watch_issue_status():
    assert parse_notify_spec(
        "watch=issue-status,severity=blocker,critical,high,result=fail,to=slack://ID1:ID2"
    ) == {
        "result": "fail",
        "severity": ["blocker", "critical", "high"],
        "to": "slack://ID1:ID2",
        "watch": ["issue-status"],
    }


def test_parse_watch_not_leading():
    assert parse_notify_spec("result=fail,watch=ISSUE-STATUS,to=slack://T:C") == {
        "result": "fail",
        "to": "slack://T:C",
        "watch": ["issue-status"],
    }


def test_parse_watch_issue_status_and_finish():
    assert parse_notify_spec(
        "watch=issue-status,finish,result=fail,to=slack://T:C"
    ) == {
        "result": "fail",
        "to": "slack://T:C",
        "watch": ["issue-status", "finish"],
    }


def test_parse_watch_finish():
    assert parse_notify_spec("watch=finish,result=pass,to=slack://T:C")["watch"] == [
        "finish"
    ]


def test_parse_rejects_bad_watch():
    with pytest.raises(NotifySpecError, match="watch"):
        parse_notify_spec("watch=result,result=fail,to=slack://T:C")


def test_parse_notify_specs_none_when_empty():
    assert parse_notify_specs(()) is None
    assert parse_notify_specs([]) is None


def test_parse_notify_specs_multiple():
    assert parse_notify_specs(
        (
            "result=fail,to=slack://T:C1",
            "result=pass,to=slack://T:C2",
        )
    ) == [
        {"result": "fail", "to": "slack://T:C1"},
        {"result": "pass", "to": "slack://T:C2"},
    ]
