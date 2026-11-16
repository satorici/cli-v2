from rich.console import Console

from satori_cli.utils.highlight import result_icon, result_text
from satori_cli.utils.wrappers import ReportWrapper


def render(detail: list[dict], monkeypatch) -> str:
    monkeypatch.setattr("satori_cli.utils.wrappers.is_json_output", lambda: False)
    console = Console(width=120, color_system=None)
    with console.capture() as capture:
        console.print(ReportWrapper(detail))
    return capture.get()


def test_passing_statuses_read_as_info():
    assert result_text(["Pass", "Fail"]).plain == "Info\nFail"
    assert result_icon("Pass") != result_icon("Fail")


def test_report_shows_passing_asserts_as_info(monkeypatch):
    out = render(
        [
            {
                "test": "prowler > test > run",
                "test_status": "Pass",
                "asserts": [
                    {"assert": "assertReturnCode", "expected": 0, "status": "Pass"}
                ],
            },
            {
                "test": "prowler > test > broken",
                "test_status": "Fail",
                "asserts": [
                    {"assert": "assertReturnCode", "expected": 0, "status": "Fail"}
                ],
            },
        ],
        monkeypatch,
    )

    assert "Info" in out
    assert "Pass" not in out
    assert "Fail" in out


def test_report_without_asserts_shows_info_status(monkeypatch):
    out = render(
        [{"test": "a > b", "test_status": "Pass", "testcases": 1, "total_fails": 0}],
        monkeypatch,
    )

    assert "Info" in out
    assert "Pass" not in out
