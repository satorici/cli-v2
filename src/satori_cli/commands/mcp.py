import rich_click as click


@click.command("mcp")
def mcp():
    """Run a local MCP server over stdio for AI agents (Cursor, Claude Code, Codex)."""
    from ..mcp_server.server import serve

    serve()
