#!/usr/bin/env python3
"""
Two-hop Codespaces chain management.

The chain data plane is:
  local SOCKS -> Codespace hop 1 -> HTTPS CONNECT relay -> Codespace hop 2 -> target
"""

from __future__ import annotations

import argparse
import os
import shlex
import signal
import subprocess
import textwrap
import time
from string import Template
from typing import Optional

from .codespace import CodespaceSelector
from .github import GitHubManager
from .state import State
from .utils import Config, get_logger

DEFAULT_HOP1_PORT = 18080
DEFAULT_HOP2_PORT = 18081


EXIT_RELAY_SCRIPT = r"""#!/usr/bin/env python3
import select
import socket
import socketserver
from http.server import BaseHTTPRequestHandler

PORT = $PORT


class ConnectHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("[exit] " + fmt % args, flush=True)

    def do_CONNECT(self):
        try:
            host, port_s = self.path.rsplit(":", 1)
            upstream = socket.create_connection((host, int(port_s)), timeout=15)
        except Exception as exc:
            self.send_error(502, str(exc))
            return

        self.send_response(200, "Connection Established")
        self.end_headers()
        self._pump(self.connection, upstream)

    def _pump(self, left, right):
        sockets = [left, right]
        for sock in sockets:
            sock.setblocking(False)
        while True:
            readable, _, errored = select.select(sockets, [], sockets, 60)
            if errored or not readable:
                break
            for sock in readable:
                try:
                    data = sock.recv(65536)
                except OSError:
                    return
                if not data:
                    return
                peer = right if sock is left else left
                try:
                    peer.sendall(data)
                except OSError:
                    return


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", PORT), ConnectHandler) as server:
        print(f"exit relay listening on {PORT}", flush=True)
        server.serve_forever()
"""


SOCKS_RELAY_SCRIPT = r"""#!/usr/bin/env python3
import http.client
import select
import socket
import socketserver
import struct

PORT = $PORT
EXIT_HOST = "$EXIT_HOST"


class SocksHandler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        try:
            if client.recv(1) != b"\x05":
                return
            nmethods = client.recv(1)[0]
            client.recv(nmethods)
            client.sendall(b"\x05\x00")

            header = client.recv(4)
            if len(header) != 4 or header[1] != 1:
                return
            atyp = header[3]
            if atyp == 1:
                target_host = socket.inet_ntoa(client.recv(4))
            elif atyp == 3:
                ln = client.recv(1)[0]
                target_host = client.recv(ln).decode()
            elif atyp == 4:
                target_host = socket.inet_ntop(socket.AF_INET6, client.recv(16))
            else:
                return
            target_port = struct.unpack("!H", client.recv(2))[0]

            conn = http.client.HTTPSConnection(EXIT_HOST, timeout=20)
            conn.set_tunnel(target_host, target_port)
            conn.connect()
            upstream = conn.sock

            client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            self._pump(client, upstream)
        except Exception as exc:
            print(f"[socks] {exc}", flush=True)
            try:
                client.sendall(b"\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00")
            except OSError:
                pass

    def _pump(self, left, right):
        sockets = [left, right]
        for sock in sockets:
            sock.setblocking(False)
        while True:
            readable, _, errored = select.select(sockets, [], sockets, 60)
            if errored or not readable:
                break
            for sock in readable:
                try:
                    data = sock.recv(65536)
                except OSError:
                    return
                if not data:
                    return
                peer = right if sock is left else left
                try:
                    peer.sendall(data)
                except OSError:
                    return


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", PORT), SocksHandler) as server:
        print(f"socks relay listening on {PORT}, exit={EXIT_HOST}", flush=True)
        server.serve_forever()
"""


def _chains(config: Config) -> dict:
    chains = config.get("chains", {})
    return chains if isinstance(chains, dict) else {}


def _chain(config: Config, name: str) -> dict:
    chain = _chains(config).get(name)
    if not isinstance(chain, dict):
        raise ValueError(f"Unknown chain: {name}")
    return chain


def _ssh(gh: GitHubManager, codespace: str, command: str, *, timeout: int = 30) -> subprocess.CompletedProcess:
    return gh.runner.run(
        ["gh", "codespace", "ssh", "--codespace", codespace, "--", command],
        capture_output=True,
        text=True,
        timeout=timeout,
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
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Failed to upload {remote_path}")


def _start_remote_script(gh: GitHubManager, codespace: str, script_path: str, label: str) -> None:
    quoted = shlex.quote(script_path)
    cmd = f"pkill -f {shlex.quote(label)} 2>/dev/null || true; nohup python3 {quoted} > {quoted}.log 2>&1 &"
    result = _ssh(gh, codespace, cmd, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Failed to start {script_path}")
    time.sleep(1)


def _ensure_chain_hops(chain: dict, config: Config, gh: GitHubManager) -> list[dict]:
    selector = CodespaceSelector(gh, config)
    hops = list(chain.get("hops", []))
    for idx, hop in enumerate(hops):
        if hop.get("codespace_name"):
            selector.ensure_running(hop["codespace_name"])
            continue
        location = hop.get("location", "")
        name = selector._create_and_wait(CodespaceSelector.BLANK_REPO, location=location)
        hop["codespace_name"] = name
        hops[idx] = hop
    chain["hops"] = hops
    return hops


def cmd_chain(args, config: Config, gh: GitHubManager) -> int:
    """Manage two-hop Codespaces proxy chains."""
    parser = argparse.ArgumentParser(prog="cs-proxy chain")
    sub = parser.add_subparsers(dest="action", required=True)

    p_create = sub.add_parser("create", help="Create a two-hop chain definition")
    p_create.add_argument("name")
    p_create.add_argument("--hop", action="append", required=True, metavar="REGION")

    p_start = sub.add_parser("start", help="Start a chain")
    p_start.add_argument("name")
    p_start.add_argument("--port", type=int, default=None)

    p_status = sub.add_parser("status", help="Show chain status")
    p_status.add_argument("name", nargs="?")

    p_stop = sub.add_parser("stop", help="Stop a chain")
    p_stop.add_argument("name")

    parsed = parser.parse_args(args)
    logger = get_logger()

    if parsed.action == "create":
        if len(parsed.hop) != 2:
            raise ValueError("Exactly two --hop values are required")
        chains = _chains(config)
        chains[parsed.name] = {
            "name": parsed.name,
            "hops": [
                {"location": parsed.hop[0], "codespace_name": ""},
                {"location": parsed.hop[1], "codespace_name": ""},
            ],
            "hop1_port": DEFAULT_HOP1_PORT,
            "hop2_port": DEFAULT_HOP2_PORT,
        }
        config.set("chains", chains)
        config.save()
        logger.info(f"Created chain: {parsed.name}")
        return 0

    if parsed.action == "status":
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

    chain = _chain(config, parsed.name)

    if parsed.action == "start":
        if getattr(config, "_dry_run", False):
            print(f"[dry-run] Would start chain {parsed.name}")
            return 0

        gh.check_auth()
        hops = _ensure_chain_hops(chain, config, gh)
        if len(hops) != 2:
            raise ValueError("Chains must have exactly two hops")

        chains = _chains(config)
        chains[parsed.name] = chain
        config.set("chains", chains)
        config.save()

        hop1, hop2 = hops
        hop1_name = hop1["codespace_name"]
        hop2_name = hop2["codespace_name"]
        hop1_port = int(chain.get("hop1_port", DEFAULT_HOP1_PORT))
        hop2_port = int(chain.get("hop2_port", DEFAULT_HOP2_PORT))
        local_port = parsed.port or config.socks_port
        exit_host = f"{hop2_name}-{hop2_port}.app.github.dev"

        exit_script = Template(EXIT_RELAY_SCRIPT).substitute(PORT=hop2_port)
        socks_script = Template(SOCKS_RELAY_SCRIPT).substitute(
            PORT=hop1_port,
            EXIT_HOST=exit_host,
        )
        exit_path = f"/tmp/csproxy_chain_exit_{hop2_port}.py"
        socks_path = f"/tmp/csproxy_chain_socks_{hop1_port}.py"

        _upload(gh, hop2_name, exit_path, exit_script)
        _start_remote_script(gh, hop2_name, exit_path, f"csproxy_chain_exit_{hop2_port}")
        gh.run_gh_command(
            ["codespace", "ports", "visibility", f"{hop2_port}:public", "--codespace", hop2_name],
            check=False,
        )

        _upload(gh, hop1_name, socks_path, socks_script)
        _start_remote_script(gh, hop1_name, socks_path, f"csproxy_chain_socks_{hop1_port}")

        fwd = subprocess.Popen(
            [
                "gh",
                "codespace",
                "ports",
                "forward",
                f"{local_port}:{hop1_port}",
                "--codespace",
                hop1_name,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        State(config.config_dir).add_tunnel(
            id=f"chain-{parsed.name}",
            kind="chain",
            name=parsed.name,
            status="healthy",
            local_port=local_port,
            pid=fwd.pid,
            hops=hops,
            exit_host=exit_host,
            created=int(time.time()),
        )
        logger.info(f"Chain {parsed.name} started: socks5://127.0.0.1:{local_port}")
        logger.info(f"Exit relay: https://{exit_host}/")
        return 0

    if parsed.action == "stop":
        state = State(config.config_dir)
        entry = next((e for e in state.get_tunnels(kind="chain") if e.get("name") == parsed.name), None)
        if not entry:
            logger.warning(f"Chain not running: {parsed.name}")
            return 0
        pid = entry.get("pid")
        if pid:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (OSError, ValueError):
                pass
        for hop in entry.get("hops", []):
            name = hop.get("codespace_name")
            if name:
                _ssh(gh, name, "pkill -f csproxy_chain_ 2>/dev/null || true", timeout=10)
        state.remove_tunnel(tunnel_id=f"chain-{parsed.name}")
        logger.info(f"Stopped chain: {parsed.name}")
        return 0

    return 1


def chain_help() -> str:
    return textwrap.dedent(
        """\
        Chain commands:
          cs-proxy chain create NAME --hop WestEurope --hop EastUs
          cs-proxy chain start NAME [--port 1080]
          cs-proxy chain status [NAME]
          cs-proxy chain stop NAME
        """
    )
