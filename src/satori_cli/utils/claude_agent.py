"""Shared plumbing for running Claude Code as a short-lived, read-only judge/editor over a
cloned repo: the local-subscription environment, the usage-limit detector, and the finding
formatting helpers. Used by both verify_issue (TP/FP judging) and improve_report (advisory
rewriting) so the two agent pipelines stay byte-identical where their needs overlap.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

_RISK_LABELS = {
    0: "Blocker",
    1: "Critical",
    2: "High",
    3: "Medium",
    4: "Low",
    5: "Info",
}
_SEVERITY_RANK = {label.lower(): value for value, label in _RISK_LABELS.items()}

_SNAPSHOT_MAX_CHARS = 12_000

# tries per agent: a model may answer with prose instead of the expected JSON, or be briefly
# overloaded; a usage limit is terminal and stops at once
CLAUDE_ATTEMPTS = 3
RETRY_BACKOFF_S = 2.0

USAGE_LIMIT_RE = re.compile(
    r"usage limit|session limit|rate.?limit|quota exceeded|credit balance"
    r"|insufficient_quota|overloaded_error|try again later"
    r"|hit your (?:\d+(?:-hour)?|[^\r\n]+?) limit",
    re.IGNORECASE,
)


def claude_env() -> dict[str, str]:
    """The environment for Claude, stripped of the API key/base-url/model so every agent
    pass always uses the local subscription rather than a billed API or another model.
    (Secrets are not scrubbed here: the untrusted repo can't reach this environment anyway,
    its hooks are renamed away before Claude starts and the agent's tools are read-only, and
    a name-based denylist would be a fragile, bypassable guard, not a boundary.)"""
    return {
        key: value
        for key, value in os.environ.items()
        if key not in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL")
    }


def severity_label(severity: Any) -> str:
    if severity is None:
        return "N/A"
    if isinstance(severity, int):
        return _RISK_LABELS.get(severity, str(severity))
    return str(severity)


def severity_floor(min_severity: Any) -> "int | None":
    if min_severity is None:
        return None
    if isinstance(min_severity, int):
        return min_severity
    return _SEVERITY_RANK.get(str(min_severity).lower())


def snapshot_text(snapshot: Any) -> str:
    if snapshot is None:
        return "null"
    try:
        text = json.dumps(snapshot, indent=2, default=str)
    except (TypeError, ValueError):
        text = str(snapshot)
    if len(text) > _SNAPSHOT_MAX_CHARS:
        return text[:_SNAPSHOT_MAX_CHARS] + "\n... [truncated]"
    return text


def finding_location(finding: dict[str, Any]) -> str:
    """file:line the finding points at (from its snapshot, falling back to identity), so the
    agent can open the exact code rather than dig it out of the snapshot JSON."""
    snapshot = finding.get("snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    identity = finding.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    path = snapshot.get("filePath") or identity.get("path") or "?"
    line = snapshot.get("lineNumber") or identity.get("start_line") or "?"
    return f"{path}:{line}"
