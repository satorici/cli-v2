"""Playbook comment directives understood by the MCP server."""

import re

NO_AUTO_RUN_RE = re.compile(r"^\s*#\s*satori:mcp\s+no-auto-run\s*$", re.MULTILINE)


def has_no_auto_run(text: str) -> bool:
    """True if the playbook has a `# satori:mcp no-auto-run` directive."""
    return bool(NO_AUTO_RUN_RE.search(text))
