"""Parse CLI --notify rule specs into structured notify rules."""

from __future__ import annotations

import re

# Keys that start a new field. status is accepted then dropped.
KNOWN_KEYS = frozenset({"result", "severity", "to", "status", "watch"})
VALID_RESULTS = frozenset({"pass", "fail"})
VALID_SEVERITIES = frozenset(
    {"info", "low", "medium", "high", "critical", "blocker"}
)
VALID_WATCH = frozenset({"issue-status", "finish"})

_KEY_RE = re.compile(
    r"(?:^|,)(result|severity|to|status|watch)=",
    re.IGNORECASE,
)


class NotifySpecError(ValueError):
    """Invalid --notify specification."""


def parse_notify_spec(spec: str) -> dict:
    """Parse a single --notify string into a notify rule dict.

    Example:
        status=TP,severity=blocker,critical,high,result=fail,to=slack://ID1:ID2
        watch=issue-status,severity=high,result=fail,to=slack://ID1:ID2

    ``status`` is accepted but ignored. ``severity`` and ``watch`` may contain
    commas. ``watch`` picks the events that fire the rule: ``finish`` (execution
    finished) and/or ``issue-status`` (a finding's status changed). Without
    ``watch`` the rule fires on finish only.
    """
    if not isinstance(spec, str) or not spec.strip():
        raise NotifySpecError("notify spec must be a non-empty string")

    text = spec.strip()
    matches = list(_KEY_RE.finditer(text))
    if not matches:
        raise NotifySpecError(
            "notify spec must include key=value fields "
            "(result, severity, to; status is ignored)"
        )

    # Reject unknown leading junk before the first key=
    if matches[0].start() != 0:
        junk = text[: matches[0].start()].strip(" ,")
        if junk:
            raise NotifySpecError(f"unknown notify field: {junk!r}")

    fields: dict[str, str] = {}
    for i, match in enumerate(matches):
        key = match.group(1).lower()
        value_start = match.end()
        value_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[value_start:value_end].strip().rstrip(",")
        if not value:
            raise NotifySpecError(f"notify {key} must not be empty")
        if key in fields:
            raise NotifySpecError(f"duplicate notify key: {key}")
        fields[key] = value

    # status is intentionally ignored
    fields.pop("status", None)

    to = fields.get("to")
    if to is None or not to.strip():
        raise NotifySpecError("notify requires to=<uri>")

    rule: dict = {"to": to.strip()}

    result = fields.get("result")
    if result is not None:
        result_norm = result.strip().lower()
        if result_norm not in VALID_RESULTS:
            raise NotifySpecError(
                f"invalid notify result: {result!r} (use pass or fail)"
            )
        rule["result"] = result_norm

    severity_raw = fields.get("severity")
    if severity_raw is not None:
        rule["severity"] = _parse_names(
            "severity",
            severity_raw,
            VALID_SEVERITIES,
            "info, low, medium, high, critical, blocker",
        )

    watch_raw = fields.get("watch")
    if watch_raw is not None:
        rule["watch"] = _parse_names(
            "watch", watch_raw, VALID_WATCH, "issue-status, finish"
        )

    return rule


def _parse_names(key: str, raw: str, valid: frozenset[str], hint: str) -> list[str]:
    names: list[str] = []
    for part in raw.split(","):
        name = part.strip().lower()
        if not name:
            continue
        if name not in valid:
            raise NotifySpecError(f"invalid notify {key}: {part!r} (use {hint})")
        if name not in names:
            names.append(name)
    if not names:
        raise NotifySpecError(f"notify {key} must not be empty")
    return names


def parse_notify_specs(specs: tuple[str, ...] | list[str]) -> list[dict] | None:
    """Parse repeated --notify values. Returns None when empty."""
    if not specs:
        return None
    return [parse_notify_spec(spec) for spec in specs]
