"""Pure helpers that cap and summarize API payloads for MCP responses.

Agents have a small context window, so every tool response goes through one of these.
"""

from typing import Any

MAX_TESTS = 50
MAX_ASSERTS_PER_TEST = 10
MAX_FIELD_CHARS = 500
MAX_OUTPUT_TAIL_LINES = 500
MAX_OUTPUT_CHARS = 20_000
MAX_SNAPSHOT_CHARS = 4_000
OUTPUT_STREAMS = ("stdout", "stderr", "os_error")


def clip(value: Any, limit: int = MAX_FIELD_CHARS) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"... [{len(value) - limit} chars truncated]"
    if isinstance(value, bytes):
        return clip(value.decode(errors="replace"), limit)
    return value


def _clip_deep(value: Any, limit: int = MAX_FIELD_CHARS) -> Any:
    if isinstance(value, dict):
        return {k: _clip_deep(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip_deep(v, limit) for v in value[:MAX_ASSERTS_PER_TEST]]
    return clip(value, limit)


def summarize_execution(execution: dict, report_url: str | None = None) -> dict:
    """Status plus assertion results, never raw logs."""
    report = execution.get("report") or {}
    detail = report.get("detail") or []

    tests = []
    for item in detail[:MAX_TESTS]:
        if not isinstance(item, dict):
            continue
        test = {
            k: _clip_deep(v)
            for k, v in item.items()
            if k not in ("output", "stdout", "stderr")
        }
        tests.append(test)

    summary = {
        "id": execution.get("id"),
        "status": execution.get("status"),
        "created_at": execution.get("created_at"),
        "job_id": execution.get("job_id"),
        "total_fails": report.get("total_fails"),
        "severities": report.get("severities"),
        "tests": tests,
        "tests_total": len(detail),
        "truncated": len(detail) > MAX_TESTS,
        "report_url": report_url,
    }
    if not report:
        summary["hint"] = "No report yet; the execution may still be running."
    elif summary["truncated"]:
        summary["hint"] = (
            f"Only the first {MAX_TESTS} tests are shown. "
            "Use list_findings(execution_id=...) for the failures."
        )
    return summary


def output_index(outputs: list[dict]) -> list[dict]:
    """One entry per test with line counts per stream, no content."""
    index = []
    for test in outputs:
        out = test.get("output") or {}
        entry = {"path": test.get("path")}
        for stream in OUTPUT_STREAMS:
            if out.get(stream):
                entry[f"{stream}_lines"] = len(str(out[stream]).splitlines())
        index.append(entry)
    return index


def tail_lines(
    text: str, tail: int, offset_from_end: int = 0, max_chars: int = MAX_OUTPUT_CHARS
) -> dict:
    """Return `tail` lines ending `offset_from_end` lines before the end of `text`."""
    tail = max(1, min(tail, MAX_OUTPUT_TAIL_LINES))
    offset_from_end = max(0, offset_from_end)

    lines = text.splitlines()
    total = len(lines)
    end = max(total - offset_from_end, 0)
    start = max(end - tail, 0)
    chunk = "\n".join(lines[start:end])

    truncated_chars = False
    if len(chunk) > max_chars:
        # Keep the end of the chunk (most recent lines) and report how many lines survived.
        chunk = chunk[-max_chars:]
        chunk = chunk[chunk.find("\n") + 1 :] if "\n" in chunk else chunk
        truncated_chars = True
        start = end - len(chunk.splitlines())

    shown = end - start
    next_offset = offset_from_end + shown
    result = {
        "text": chunk,
        "total_lines": total,
        "shown_lines": shown,
        "next_offset_from_end": next_offset if start > 0 else None,
        "truncated": start > 0 or truncated_chars,
    }
    if start > 0:
        result["hint"] = (
            f"{start} earlier lines not shown. "
            f"Call again with offset_from_end={next_offset} for the previous page."
        )
    return result


def summarize_finding(finding: dict) -> dict:
    identity = finding.get("identity") or {}
    return {
        "id": finding.get("id"),
        "title": clip(finding.get("title")),
        "severity": finding.get("severity"),
        "status": finding.get("status"),
        "source": finding.get("source"),
        "execution_id": finding.get("execution_id"),
        "location": _clip_deep(identity),
    }


def detail_finding(finding: dict) -> dict:
    result = summarize_finding(finding)
    result["created_at"] = finding.get("created_at")
    snapshot = finding.get("snapshot")
    if snapshot is not None:
        text = snapshot if isinstance(snapshot, str) else repr(snapshot)
        result["snapshot"] = clip(text, MAX_SNAPSHOT_CHARS)
    return result


def summarize_repo(repo: dict) -> dict:
    last = repo.get("last_execution") or {}
    return {
        "full_name": repo.get("full_name"),
        "private": repo.get("private"),
        "last_execution": (
            {
                "execution_id": last.get("execution_id"),
                "status": last.get("status"),
                "total_fails": last.get("total_fails"),
            }
            if last
            else None
        ),
    }


def paged(items: list, total: int | None, page: int, quantity: int) -> dict:
    result: dict = {"items": items, "total": total, "page": page}
    if total is not None and page * quantity < total:
        result["next_page"] = page + 1
    return result
