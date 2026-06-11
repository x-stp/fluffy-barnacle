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
from typing import Optional

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


# =============================================================================
# Actions (mutating; presentation-free, raise on error). These back the TUI's
# key bindings and mirror the logic inside the cmd_* pool/stop commands.
# =============================================================================


def _pid_suffix_for_port(config: Config, port: int) -> str:
    """Derive a tunnel's pid-file suffix from its port (matches cmd_start/stop)."""
    index = port - config.socks_port
    return "" if index <= 0 else str(index + 1)


def stop_tunnel(config: Config, port: int) -> None:
    """Stop the SSH tunnel bound to `port` and remove it from the pool."""
    from .tunnel import SSHTunnel

    suffix = _pid_suffix_for_port(config, port)
    SSHTunnel(config, "", port=port, pid_suffix=suffix).stop()


def drain_tunnel(config: Config, port: int) -> None:
    """Mark the tunnel on `port` as draining. Raises if no such tunnel exists."""
    state = State(config.config_dir)
    if not state.get_tunnel_by_port(port):
        raise ValueError(f"No tunnel on port {port}")
    state.update_tunnel(port, status="draining")


def rotate_pool(config: Config) -> int:
    """Return a random healthy tunnel port. Raises if none are healthy."""
    import random

    state = State(config.config_dir)
    healthy = state.get_tunnels(kind="ssh", status="healthy")
    if not healthy:
        raise RuntimeError("No healthy tunnels available")
    port: int = random.choice(healthy)["port"]
    return port


def stop_all_tunnels(config: Config) -> None:
    """Stop the primary tunnel, any pool tunnels, and the HTTP proxy."""
    from .tunnel import HTTPProxyManager, SSHTunnel

    SSHTunnel(config, config.codespace_name or "").stop()
    for i in range(1, len(config.codespace_names)):
        SSHTunnel(config, "", port=config.socks_port + i, pid_suffix=str(i + 1)).stop()
    HTTPProxyManager(config).stop()


# =============================================================================
# Chains (two-hop Codespace chains). Combines defined chains (config["chains"])
# with running chains (state, kind="chain") into one display model, and wraps
# the chain start/stop/delete logic for the TUI.
# =============================================================================


def _chain_row(name: str, definition: dict, running: Optional[dict]) -> dict:
    """Build one display row, preferring the definition's hops (which carry the
    account each hop's PAT belongs to) and overlaying running status/port."""
    # Defined hops carry account + location; fall back to the running entry's
    # hops for a chain that is running without a stored definition.
    hops = definition.get("hops") or (running.get("hops", []) if running else [])
    return {
        "name": name,
        "status": running.get("status", "running") if running else "defined",
        "local_port": running.get("local_port") if running else None,
        "running": running is not None,
        "hops": [
            {"location": h.get("location", ""), "account": h.get("account", "")} for h in hops
        ],
    }


def list_chains(config: Config) -> list[dict]:
    """Return a combined view of defined and running two-hop chains."""
    from .chains import _chains

    state = State(config.config_dir)
    running: dict[str, dict] = {}
    for entry in state.get_tunnels(kind="chain"):
        entry_name = entry.get("name")
        if entry_name:
            running[str(entry_name)] = entry
    defined = _chains(config)

    rows = [_chain_row(str(name), chain, running.get(str(name))) for name, chain in defined.items()]
    # Surface any running chain that no longer has a stored definition.
    rows += [_chain_row(name, {}, entry) for name, entry in running.items() if name not in defined]
    return rows


def start_chain(config: Config, gh: GitHubManager, name: str, port: Optional[int] = None) -> None:
    """Start a defined chain. Slow (provisions/links two hops); raises on failure."""
    from types import SimpleNamespace

    from .chains import _cmd_chain_start

    parsed = SimpleNamespace(name=name, port=port)
    if _cmd_chain_start(parsed, config, gh) != 0:
        raise RuntimeError(f"Failed to start chain {name}")


def stop_chain(config: Config, gh: GitHubManager, name: str) -> None:
    """Stop a running chain and clean up its remote relays."""
    from types import SimpleNamespace

    from .chains import _cmd_chain_stop

    _cmd_chain_stop(SimpleNamespace(name=name), config, gh)


def delete_chain(config: Config, name: str) -> None:
    """Remove a chain definition from config. Raises if it does not exist."""
    from .chains import _chains

    chains = _chains(config)
    if name not in chains:
        raise ValueError(f"Unknown chain: {name}")
    del chains[name]
    config.set("chains", chains)
    config.save()
