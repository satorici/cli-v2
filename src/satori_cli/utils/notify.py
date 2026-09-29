"""Parse CLI --notify rule specs into structured notify rules."""

from __future__ import annotations

import re

# Keys that start a new field. status is accepted then dropped.
KNOWN_KEYS = frozenset({"result", "severity", "to", "status"})
VALID_RESULTS = frozenset({"pass", "fail"})
VALID_SEVERITIES = frozenset(
    {"info", "low", "medium", "high", "critical", "blocker"}
)

_KEY_RE = re.compile(
    r"(?:^|,)(result|severity|to|status)=",
    re.IGNORECASE,
)


class NotifySpecError(ValueError):
    """Invalid --notify specification."""


def parse_notify_spec(spec: str) -> dict:
    """Parse a single --notify string into a notify rule dict.

    Example:
        status=TP,severity=blocker,critical,high,result=fail,to=slack://ID1:ID2

    ``status`` is accepted but ignored. ``severity`` may contain commas.
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

    result = fields.get("result")
    if result is None:
        raise NotifySpecError("notify requires result=pass|fail")
    result_norm = result.strip().lower()
    if result_norm not in VALID_RESULTS:
        raise NotifySpecError(f"invalid notify result: {result!r} (use pass or fail)")

    to = fields.get("to")
    if to is None or not to.strip():
        raise NotifySpecError("notify requires to=<uri>")

    rule: dict = {"result": result_norm, "to": to.strip()}

    severity_raw = fields.get("severity")
    if severity_raw is not None:
        names: list[str] = []
        for part in severity_raw.split(","):
            name = part.strip().lower()
            if not name:
                continue
            if name not in VALID_SEVERITIES:
                raise NotifySpecError(
                    f"invalid notify severity: {part!r} "
                    "(use info, low, medium, high, critical, blocker)"
                )
            if name not in names:
                names.append(name)
        if not names:
            raise NotifySpecError("notify severity must not be empty")
        rule["severity"] = names

    return rule


def parse_notify_specs(specs: tuple[str, ...] | list[str]) -> list[dict] | None:
    """Parse repeated --notify values. Returns None when empty."""
    if not specs:
        return None
    return [parse_notify_spec(spec) for spec in specs]
