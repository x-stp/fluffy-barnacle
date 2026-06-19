#!/usr/bin/env python3
"""
Model Context Protocol (MCP) server for csproxy (optional `mcp` extra).

Exposes the same operations as the CLI and TUI over MCP so the toolkit can be
driven from MCP-aware clients (Claude Desktop, Claude Code, Cursor, ...). The
heavy `mcp` SDK import lives in `.server`; this launcher keeps it lazy so the
package imports fine without the SDK installed and prints a friendly hint when
the extra is missing -- mirroring the `tui` launcher.
"""

from __future__ import annotations


def main_mcp(argv=None) -> int:
    """Entry point for the `cs-mcp` command. Runs the MCP server over stdio."""
    try:
        from .server import run_server
    except ImportError as e:  # mcp SDK not installed
        if "mcp" in str(e).lower():
            print(
                "The cs-mcp server requires the optional 'mcp' extra.\n"
                "Install it with:  pip install 'fluffy-barnacle[mcp]'"
            )
            return 1
        raise
    return run_server(argv)
