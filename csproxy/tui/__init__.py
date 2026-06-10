#!/usr/bin/env python3
"""
Terminal UI for csproxy (optional `tui` extra).

The heavy Textual import lives in `.app`; this launcher keeps it lazy so the
package imports fine without Textual installed and prints a friendly hint when
the extra is missing.
"""

from __future__ import annotations


def main_tui(argv=None) -> int:
    """Entry point for the `cs-tui` command and `cs-proxy tui`."""
    try:
        from .app import run_app
    except ImportError as e:  # textual not installed
        if "textual" in str(e).lower():
            print(
                "The cs-tui interface requires the optional 'tui' extra.\n"
                "Install it with:  pip install 'fluffy-barnacle[tui]'"
            )
            return 1
        raise
    return run_app(argv)
