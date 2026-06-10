#!/usr/bin/env python3
"""Helpers for interactive terminal prompts.

Prompts and their surrounding menus are written to stderr rather than stdout so
they stay visible when stdout is piped or captured -- e.g. ``cs-proxy delete |
tail``. A prompt written to a block-buffered stdout pipe never reaches the
terminal, so the command appears to hang with no visible question while it
blocks on ``input()``. Routing prompts to stderr also follows the usual Unix
split: machine-readable data on stdout, human interaction on stderr.
"""

import sys
from typing import Any


def eprint(*args: Any, **kwargs: Any) -> None:
    """``print`` to stderr, so interactive output survives stdout redirection."""
    kwargs.setdefault("file", sys.stderr)
    print(*args, **kwargs)


def prompt(message: str = "") -> str:
    """Write ``message`` to stderr and read one line from stdin.

    Mirrors ``input(message)`` but routes the prompt to stderr so it is not
    swallowed by a piped or block-buffered stdout. Returns the line as typed
    (callers strip as needed).
    """
    if message:
        sys.stderr.write(message)
        sys.stderr.flush()
    return input()
