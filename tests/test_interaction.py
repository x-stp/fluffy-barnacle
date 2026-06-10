"""Tests for the interactive-prompt helpers (csproxy.utils.interaction).

These guard the regression where a prompt written to a block-buffered stdout
pipe (e.g. ``cs-proxy delete | tail``) is never shown and the command appears
to hang. Prompts must go to stderr so they survive stdout redirection.
"""

import io

from csproxy.utils import eprint, prompt
from csproxy.utils.interaction import prompt as prompt_direct


def test_prompt_writes_message_to_stderr_not_stdout(monkeypatch):
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    monkeypatch.setattr("builtins.input", lambda: "y")

    answer = prompt("Are you sure? [y/N] ")

    assert answer == "y"
    assert "Are you sure? [y/N] " in err.getvalue()
    assert out.getvalue() == ""  # nothing leaks to stdout


def test_prompt_returns_line_unstripped(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda: "  WestEurope  ")
    assert prompt("> ") == "  WestEurope  "


def test_prompt_empty_message_does_not_write(monkeypatch):
    err = io.StringIO()
    monkeypatch.setattr("sys.stderr", err)
    monkeypatch.setattr("builtins.input", lambda: "")

    assert prompt() == ""
    assert err.getvalue() == ""


def test_eprint_goes_to_stderr(monkeypatch):
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)

    eprint("menu line")

    assert "menu line" in err.getvalue()
    assert out.getvalue() == ""


def test_prompt_is_exported_from_package():
    # The package re-export and the module object are the same callable.
    assert prompt is prompt_direct
