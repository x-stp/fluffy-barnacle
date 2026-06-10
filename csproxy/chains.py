#!/usr/bin/env python3
"""
Two-hop Codespaces chain management.

The chain data plane is:
  local SOCKS -> Codespace hop 1 -> WebSocket relay -> Codespace hop 2 -> target
"""

from __future__ import annotations

import argparse
import os
import secrets
import shlex
import signal
import socket
import subprocess
import textwrap
import time
from pathlib import Path
from typing import Optional

from .accounts import GitHubAccount
from .codespace import CodespaceSelector
from .github import GitHubManager
from .state import State
from .utils import Config, get_logger

DEFAULT_HOP1_PORT = 18080
DEFAULT_HOP2_PORT = 18081


RELAYS_DIR = Path(__file__).with_name("relays")


def _relay_source(name: str) -> str:
    return (RELAYS_DIR / name).read_text(encoding="utf-8")


EXIT_RELAY_SCRIPT = _relay_source("exit_relay.py")
SOCKS_RELAY_SCRIPT = _relay_source("socks_relay.py")


def _chains(config: Config) -> dict:
    chains = config.get("chains", {})
    return chains if isinstance(chains, dict) else {}


def _chain(config: Config, name: str) -> dict:
    chain = _chains(config).get(name)
    if not isinstance(chain, dict):
        raise ValueError(f"Unknown chain: {name}")
    return chain


def _chain_secret(chain: dict) -> str:
    """Return the per-chain relay secret, creating one for older configs."""
    secret = str(chain.get("relay_secret") or "")
    if not secret:
        secret = secrets.token_urlsafe(32)
        chain["relay_secret"] = secret
    return secret


def parse_hop_spec(spec: str) -> dict:
    """Parse REGION or ACCOUNT:REGION into a hop dict."""
    if ":" in spec:
        account, location = spec.split(":", 1)
        if not account or not location:
            raise ValueError(f"Invalid hop spec: {spec}")
        return {"account": account, "location": location, "codespace_name": ""}
    return {"location": spec, "codespace_name": ""}


def _manager_for_hop(hop: dict, config: Config, default_gh: GitHubManager) -> GitHubManager:
    account_name = hop.get("account", "")
    if not account_name:
        return default_gh
    account = GitHubAccount.from_config(config, account_name)
    return GitHubManager(config_dir=config.config_dir, account=account)


def _popen_env_for_gh(gh: GitHubManager) -> Optional[dict]:
    token = gh.load_token()
    if not token:
        return None
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    return env


def _runner_env_for_gh(gh: GitHubManager) -> Optional[dict]:
    token = gh.load_token()
    return {"GH_TOKEN": token} if token else None


def _ssh(
    gh: GitHubManager, codespace: str, command: str, *, timeout: int = 30
) -> subprocess.CompletedProcess:
    return gh.runner.run(
        ["gh", "codespace", "ssh", "--codespace", codespace, "--", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_runner_env_for_gh(gh),
    )


def _upload(gh: GitHubManager, codespace: str, remote_path: str, content: str) -> None:
    result = gh.runner.run(
        [
            "gh",
            "codespace",
            "ssh",
            "--codespace",
            codespace,
            "--",
            f"cat > {shlex.quote(remote_path)}",
        ],
        input=content,
        capture_output=True,
        text=True,
        timeout=30,
        env=_runner_env_for_gh(gh),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Failed to upload {remote_path}")


def _start_remote_script(
    gh: GitHubManager,
    codespace: str,
    script_path: str,
    label: str,
    *,
    env: Optional[dict[str, str]] = None,
) -> None:
    quoted = shlex.quote(script_path)
    env_prefix = ""
    if env:
        env_prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items()) + " "
    cmd = f"{env_prefix}nohup python3 {quoted} > {quoted}.log 2>&1 &"
    result = _ssh(gh, codespace, cmd, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Failed to start {script_path}")
    time.sleep(1)


def _wait_local_forward(
    port: int, process: subprocess.Popen, label: str, timeout: int = 20
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{label} port forward exited before becoming ready")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {label} on 127.0.0.1:{port}")


def _terminate_process(process: Optional[subprocess.Popen]) -> None:
    """Best-effort termination for local gh port-forward processes."""
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except OSError:
            pass


def _cleanup_remote_script(gh: GitHubManager, codespace: str, script_path: str) -> None:
    """Best-effort cleanup for uploaded chain scripts and logs."""
    if not codespace or not script_path:
        return
    quoted = shlex.quote(script_path)
    process_pattern = script_path
    if process_pattern.startswith("/"):
        process_pattern = "[/]" + process_pattern[1:]
    process_pattern = shlex.quote(f"[p]ython3 .*{process_pattern}")
    try:
        _ssh(
            gh,
            codespace,
            "for pid in $(pgrep -f "
            f'{process_pattern} 2>/dev/null); do kill "$pid" 2>/dev/null || true; done; '
            f"rm -f {quoted} {quoted}.log",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as e:
        get_logger().debug(f"Best-effort remote script cleanup failed: {e}")


def _upload_secret_file(gh: GitHubManager, codespace: str, remote_path: str, secret: str) -> None:
    _upload(gh, codespace, remote_path, secret + "\n")
    result = _ssh(gh, codespace, f"chmod 600 {shlex.quote(remote_path)}", timeout=10)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Failed to secure {remote_path}")


def _cleanup_remote_file(gh: GitHubManager, codespace: str, remote_path: str) -> None:
    if not codespace or not remote_path:
        return
    try:
        _ssh(gh, codespace, f"rm -f {shlex.quote(remote_path)}", timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        get_logger().debug(f"Best-effort remote file cleanup failed: {e}")


def _set_port_private(gh: GitHubManager, codespace: str, port: int) -> None:
    """Best-effort reset for public chain relay ports."""
    if not codespace or not port:
        return
    try:
        gh.run_gh_command(
            ["codespace", "ports", "visibility", f"{port}:private", "--codespace", codespace],
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        get_logger().debug(f"Best-effort port visibility reset failed: {e}")


def _ensure_chain_hops(chain: dict, config: Config, gh: GitHubManager) -> list[dict]:
    hops = list(chain.get("hops", []))
    for idx, hop in enumerate(hops):
        hop_gh = _manager_for_hop(hop, config, gh)
        hop_gh.check_auth()
        selector = CodespaceSelector(hop_gh, config)
        if hop.get("codespace_name"):
            selector.ensure_running(hop["codespace_name"])
            continue
        location = hop.get("location", "")
        name = selector._create_and_wait(CodespaceSelector.BLANK_REPO, location=location)
        hop["codespace_name"] = name
        hops[idx] = hop
    chain["hops"] = hops
    return hops


def _cmd_chain_create(parsed, config: Config) -> int:
    logger = get_logger()
    if len(parsed.hop) != 2:
        raise ValueError("Exactly two --hop values are required")
    chains = _chains(config)
    chains[parsed.name] = {
        "name": parsed.name,
        "hops": [parse_hop_spec(parsed.hop[0]), parse_hop_spec(parsed.hop[1])],
        "hop1_port": DEFAULT_HOP1_PORT,
        "hop2_port": DEFAULT_HOP2_PORT,
        "relay_secret": secrets.token_urlsafe(32),
    }
    config.set("chains", chains)
    config.save()
    logger.info(f"Created chain: {parsed.name}")
    return 0


def _cmd_chain_status(parsed, config: Config) -> int:
    state = State(config.config_dir)
    entries = state.get_tunnels(kind="chain")
    if parsed.name:
        entries = [e for e in entries if e.get("name") == parsed.name]
    if not entries:
        print("No running chains.")
        return 0
    for entry in entries:
        print(f"{entry.get('name')}: {entry.get('status')} local=:{entry.get('local_port')}")
        for hop in entry.get("hops", []):
            print(f"  - {hop.get('codespace_name')} {hop.get('location', '')}")
    return 0


def _persist_chain(config: Config, name: str, chain: dict) -> None:
    chains = _chains(config)
    chains[name] = chain
    config.set("chains", chains)
    config.save()


def _cmd_chain_start(parsed, config: Config, gh: GitHubManager) -> int:
    logger = get_logger()
    chain = _chain(config, parsed.name)
    if getattr(config, "_dry_run", False):
        print(f"[dry-run] Would start chain {parsed.name}")
        return 0

    hops = _ensure_chain_hops(chain, config, gh)
    if len(hops) != 2:
        raise ValueError("Chains must have exactly two hops")

    hop1, hop2 = hops
    hop1_gh = _manager_for_hop(hop1, config, gh)
    hop2_gh = _manager_for_hop(hop2, config, gh)
    hop1_name = hop1["codespace_name"]
    hop2_name = hop2["codespace_name"]
    hop1_port = int(chain.get("hop1_port", DEFAULT_HOP1_PORT))
    hop2_port = int(chain.get("hop2_port", DEFAULT_HOP2_PORT))
    local_port = parsed.port or config.socks_port
    exit_host = f"{hop2_name}-{hop2_port}.app.github.dev"
    relay_secret = _chain_secret(chain)
    _persist_chain(config, parsed.name, chain)

    exit_path = f"/tmp/csproxy_chain_exit_{hop2_port}.py"
    socks_path = f"/tmp/csproxy_chain_socks_{hop1_port}.py"
    exit_secret_path = f"/tmp/csproxy_chain_exit_{hop2_port}.secret"
    socks_secret_path = f"/tmp/csproxy_chain_socks_{hop1_port}.secret"
    fwd: Optional[subprocess.Popen] = None
    exit_fwd: Optional[subprocess.Popen] = None

    try:
        _upload(hop2_gh, hop2_name, exit_path, EXIT_RELAY_SCRIPT)
        _upload_secret_file(hop2_gh, hop2_name, exit_secret_path, relay_secret)
        _start_remote_script(
            hop2_gh,
            hop2_name,
            exit_path,
            f"csproxy_chain_exit_{hop2_port}",
            env={
                "CS_PROXY_RELAY_PORT": str(hop2_port),
                "CS_PROXY_RELAY_SECRET_FILE": exit_secret_path,
            },
        )
        exit_fwd = subprocess.Popen(
            [
                "gh",
                "codespace",
                "ports",
                "forward",
                f"{hop2_port}:{hop2_port}",
                "--codespace",
                hop2_name,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=_popen_env_for_gh(hop2_gh),
        )
        _wait_local_forward(hop2_port, exit_fwd, "exit relay")
        hop2_gh.run_gh_command(
            ["codespace", "ports", "visibility", f"{hop2_port}:public", "--codespace", hop2_name],
            check=False,
        )

        _upload(hop1_gh, hop1_name, socks_path, SOCKS_RELAY_SCRIPT)
        _upload_secret_file(hop1_gh, hop1_name, socks_secret_path, relay_secret)
        _start_remote_script(
            hop1_gh,
            hop1_name,
            socks_path,
            f"csproxy_chain_socks_{hop1_port}",
            env={
                "CS_PROXY_RELAY_PORT": str(hop1_port),
                "CS_PROXY_RELAY_SECRET_FILE": socks_secret_path,
                "CS_PROXY_EXIT_HOST": exit_host,
            },
        )

        fwd = subprocess.Popen(
            [
                "gh",
                "codespace",
                "ports",
                "forward",
                f"{hop1_port}:{local_port}",
                "--codespace",
                hop1_name,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=_popen_env_for_gh(hop1_gh),
        )
        _wait_local_forward(local_port, fwd, "chain SOCKS")

        State(config.config_dir).add_tunnel(
            id=f"chain-{parsed.name}",
            kind="chain",
            name=parsed.name,
            status="healthy",
            local_port=local_port,
            pid=fwd.pid,
            exit_forward_pid=exit_fwd.pid,
            hops=hops,
            exit_host=exit_host,
            hop1_port=hop1_port,
            hop2_port=hop2_port,
            created=int(time.time()),
        )
        logger.info(f"Chain {parsed.name} started: socks5://127.0.0.1:{local_port}")
        logger.info(f"Exit relay: https://{exit_host}/")
        return 0
    except Exception:
        _terminate_process(fwd)
        _terminate_process(exit_fwd)
        _cleanup_remote_script(hop1_gh, hop1_name, socks_path)
        _cleanup_remote_script(hop2_gh, hop2_name, exit_path)
        _cleanup_remote_file(hop1_gh, hop1_name, socks_secret_path)
        _cleanup_remote_file(hop2_gh, hop2_name, exit_secret_path)
        _set_port_private(hop1_gh, hop1_name, hop1_port)
        _set_port_private(hop2_gh, hop2_name, hop2_port)
        State(config.config_dir).remove_tunnel(tunnel_id=f"chain-{parsed.name}")
        raise


def _cmd_chain_stop(parsed, config: Config, gh: GitHubManager) -> int:
    logger = get_logger()
    state = State(config.config_dir)
    entry = next((e for e in state.get_tunnels(kind="chain") if e.get("name") == parsed.name), None)
    if not entry:
        logger.warning(f"Chain not running: {parsed.name}")
        return 0
    for pid in (entry.get("pid"), entry.get("exit_forward_pid")):
        if not pid:
            continue
        try:
            os.kill(int(pid), signal.SIGTERM)
        except (OSError, ValueError):
            pass
    for hop_idx, hop in enumerate(entry.get("hops", [])):
        name = hop.get("codespace_name")
        if name:
            hop_gh = _manager_for_hop(hop, config, gh)
            port = int(
                entry.get("hop1_port" if hop_idx == 0 else "hop2_port")
                or (DEFAULT_HOP1_PORT if hop_idx == 0 else DEFAULT_HOP2_PORT)
            )
            _ssh(
                hop_gh,
                name,
                "for pid in $(pgrep -f '[p]ython3 .*[/]tmp/csproxy_chain_' 2>/dev/null); "
                'do kill "$pid" 2>/dev/null || true; done; '
                "rm -f /tmp/csproxy_chain_*",
                timeout=10,
            )
            _set_port_private(hop_gh, name, port)
    state.remove_tunnel(tunnel_id=f"chain-{parsed.name}")
    logger.info(f"Stopped chain: {parsed.name}")
    return 0


def cmd_chain(args, config: Config, gh: GitHubManager) -> int:
    """Manage two-hop Codespaces proxy chains."""
    parser = argparse.ArgumentParser(prog="cs-proxy chain")
    sub = parser.add_subparsers(dest="action", required=True)

    p_create = sub.add_parser("create", help="Create a two-hop chain definition")
    p_create.add_argument("name")
    p_create.add_argument("--hop", action="append", required=True, metavar="REGION|ACCOUNT:REGION")

    p_start = sub.add_parser("start", help="Start a chain")
    p_start.add_argument("name")
    p_start.add_argument("--port", type=int, default=None)

    p_status = sub.add_parser("status", help="Show chain status")
    p_status.add_argument("name", nargs="?")

    p_stop = sub.add_parser("stop", help="Stop a chain")
    p_stop.add_argument("name")

    parsed = parser.parse_args(args)
    handlers = {
        "create": lambda: _cmd_chain_create(parsed, config),
        "status": lambda: _cmd_chain_status(parsed, config),
        "start": lambda: _cmd_chain_start(parsed, config, gh),
        "stop": lambda: _cmd_chain_stop(parsed, config, gh),
    }
    return handlers[parsed.action]()


def chain_help() -> str:
    return textwrap.dedent("""\
        Chain commands:
          cs-proxy chain create NAME --hop WestEurope --hop EastUs
          cs-proxy chain create NAME --hop eu:WestEurope --hop us:EastUs
          cs-proxy chain start NAME [--port 1080]
          cs-proxy chain status [NAME]
          cs-proxy chain stop NAME
        """)
