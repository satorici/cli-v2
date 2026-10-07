from satori_cli.mcp_server import shaping


def test_tail_lines_pages_backwards():
    text = "\n".join(f"l{i}" for i in range(10))
    first = shaping.tail_lines(text, 3)
    assert first["text"] == "l7\nl8\nl9"
    assert first["next_offset_from_end"] == 3
    assert first["truncated"] is True
    second = shaping.tail_lines(text, 3, first["next_offset_from_end"])
    assert second["text"] == "l4\nl5\nl6"


def test_tail_lines_whole_text_not_truncated():
    result = shaping.tail_lines("a\nb", 100)
    assert result["text"] == "a\nb"
    assert result["truncated"] is False
    assert result["next_offset_from_end"] is None


def test_tail_lines_caps_chars_and_lines():
    text = "\n".join("x" * 100 for _ in range(1000))
    result = shaping.tail_lines(text, 10_000, max_chars=1000)
    assert len(result["text"]) <= 1000
    assert result["truncated"] is True
    assert result["next_offset_from_end"] == result["shown_lines"]


def test_summarize_execution_caps_tests_and_drops_logs():
    detail = [
        {"path": f"cmd.{i}", "output": {"stdout": "x" * 10_000}} for i in range(80)
    ]
    detail[0]["asserts"] = [{"msg": "y" * 5000}]
    summary = shaping.summarize_execution(
        {"id": 1, "status": "FINISHED", "report": {"total_fails": 2, "detail": detail}},
        "http://r/1",
    )
    assert len(summary["tests"]) == shaping.MAX_TESTS
    assert summary["truncated"] and summary["tests_total"] == 80
    assert "output" not in summary["tests"][0]
    assert len(summary["tests"][0]["asserts"][0]["msg"]) < 600
    assert summary["report_url"] == "http://r/1"


def test_output_index_has_counts_not_content():
    index = shaping.output_index(
        [{"path": "cmd.0", "output": {"stdout": "a\nb\nc", "stderr": ""}}]
    )
    assert index == [{"path": "cmd.0", "stdout_lines": 3}]


def test_detail_finding_clips_snapshot():
    result = shaping.detail_finding({"id": 1, "snapshot": "z" * 100_000})
    assert len(result["snapshot"]) < shaping.MAX_SNAPSHOT_CHARS + 100
