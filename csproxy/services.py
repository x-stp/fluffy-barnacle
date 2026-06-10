#!/usr/bin/env python3
"""
Presentation-free service layer for csproxy.

This module is the structured-data API that both the CLI (`cmd_*` functions in
proxy.py, which print and return exit codes) and richer front-ends (the Textual
TUI, and a possible future loopback web dashboard) consume. Functions here
return plain data (dataclasses / dicts / lists) and raise on error -- they never
print. The CLI commands are thin wrappers that call these and render the result.

The read model underneath (State, GitHubManager, SSHTunnel queries) is already
presentation-free, so these functions are mostly faithful extractions of logic
that previously lived inline inside the cmd_* functions.
"""

from __future__ import annotations

import shutil
import socket
from dataclasses import dataclass
from pathlib import Path

from .github import GitHubManager
from .state import State
from .utils import Config, get_logger


@dataclass
class Check:
    """One diagnostic result from run_diagnostics()."""

    status: str  # "PASS" or "FAIL"
    message: str

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


def run_diagnostics(config: Config, gh: GitHubManager) -> list[Check]:
    """
    Run dependency/configuration health checks and return the structured
    results. Extracted from proxy.cmd_check so the same checks back both the
    CLI and the TUI. Never prints; never raises (failures become FAIL checks).
    """
    checks: list[Check] = []

    def _ok(msg: str) -> None:
        checks.append(Check("PASS", msg))

    def _fail(msg: str) -> None:
        checks.append(Check("FAIL", msg))

    # 1. GitHub CLI
    if shutil.which("gh"):
        _ok("gh CLI is installed")
        result = gh.runner.run(["gh", "auth", "status"], capture_output=True, text=True)
        if result.returncode == 0:
            _ok("gh CLI is authenticated")
        else:
            _fail("gh CLI is not authenticated (run: gh auth login)")
    else:
        _fail("gh CLI is not installed")

    # 2. SSH / 3. curl / 4. proxychains4
    if shutil.which("ssh"):
        _ok("ssh is installed")
    else:
        _fail("ssh is not installed")

    if shutil.which("curl"):
        _ok("curl is installed")
    else:
        _fail("curl is not installed")

    if shutil.which("proxychains4"):
        _ok("proxychains4 is installed")
    else:
        _fail("proxychains4 is not installed (optional: apt install proxychains-ng)")

    # 5. Config directory / file
    if config.config_dir.exists():
        _ok(f"Config directory exists: {config.config_dir}")
    else:
        _fail(f"Config directory missing: {config.config_dir}")

    if config.config_file.exists():
        _ok(f"Config file exists: {config.config_file}")
    else:
        _fail(f"Config file missing: {config.config_file}")

    # 6. SSH key
    key_file = config.config_dir / "codespace_key"
    if key_file.exists():
        _ok(f"SSH key exists: {key_file}")
    else:
        _fail(f"SSH key missing: {key_file} (run: cs-proxy keygen)")

    # 7. Port conflicts
    for port, label in [(config.socks_port, "SOCKS5"), (config.http_proxy_port, "HTTP")]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                _ok(f"{label} port {port} is available")
            except OSError:
                _fail(f"{label} port {port} is already in use")

    # 8. State file health
    try:
        state = State(config.config_dir)
        tunnels = state.load().get("tunnels", [])
        if tunnels:
            _ok(f"State file has {len(tunnels)} tunnel(s)")
        else:
            _ok("State file is healthy (no tunnels)")
    except (TimeoutError, OSError, ValueError) as e:
        _fail(f"State file error: {e}")

    return checks


def list_pool(config: Config, reconcile: bool = True) -> list[dict]:
    """
    Return the tracked SSH tunnels from the state store as plain dicts (the
    shape already persisted in state.json: id, kind, port, pid, status,
    codespace_name, failures, ...). Optionally reconcile dead PIDs first so the
    caller sees fresh statuses.

    Raises TimeoutError if the state file is locked by another process; callers
    that poll (e.g. the TUI) should catch it and retry.
    """
    state = State(config.config_dir)
    if reconcile:
        state.reconcile()
    return state.get_tunnels(kind="ssh")


def list_codespaces_safe(gh: GitHubManager) -> list[dict]:
    """
    Best-effort codespace listing for monitoring views. Returns [] (and logs at
    debug) instead of raising when gh is missing/unauthenticated, so a live
    dashboard degrades gracefully rather than crashing.
    """
    import subprocess

    from .utils import GitHubAuthError

    try:
        return gh.list_codespaces()
    except (GitHubAuthError, subprocess.SubprocessError, ValueError, OSError) as e:
        get_logger().debug(f"Could not list codespaces: {e}")
        return []


def get_logs(config: Config, lines: int = 50) -> list[str]:
    """Return the last `lines` lines of the proxy log, or [] if none exists."""
    log_file: Path = config.config_dir / "proxy.log"
    if not log_file.exists():
        return []
    log_lines = log_file.read_text().splitlines()
    return log_lines[-lines:] if len(log_lines) > lines else log_lines
