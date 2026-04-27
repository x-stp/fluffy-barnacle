#!/usr/bin/env python3
"""
Two-hop Codespaces chain management.

The chain data plane is:
  local SOCKS -> Codespace hop 1 -> WebSocket relay -> Codespace hop 2 -> target
"""

from __future__ import annotations

import argparse
import os
import shlex
import signal
import socket
import subprocess
import textwrap
import time
from string import Template
from typing import Optional

from .accounts import GitHubAccount
from .codespace import CodespaceSelector
from .github import GitHubManager
from .state import State
from .utils import Config, get_logger

DEFAULT_HOP1_PORT = 18080
DEFAULT_HOP2_PORT = 18081


EXIT_RELAY_SCRIPT = r"""#!/usr/bin/env python3
import base64
import hashlib
import select
import socket
import socketserver
import struct
from http.server import BaseHTTPRequestHandler

PORT = $PORT


def _recvall(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise OSError("socket closed")
        data += chunk
    return data


def read_frame(sock):
    first = _recvall(sock, 2)
    opcode = first[0] & 0x0F
    masked = bool(first[1] & 0x80)
    length = first[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recvall(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recvall(sock, 8))[0]
    mask = _recvall(sock, 4) if masked else b""
    payload = _recvall(sock, length) if length else b""
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def send_frame(sock, payload, opcode=2):
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    sock.sendall(header + payload)


class WebSocketConnectHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("[exit] " + fmt % args, flush=True)

    def do_GET(self):
        if self.headers.get("Upgrade", "").lower() != "websocket":
            self.send_error(426, "WebSocket upgrade required")
            return
        key = self.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        self.connection.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )

        try:
            opcode, target = read_frame(self.connection)
            if opcode == 8:
                return
            host, port_s = target.decode().rsplit(":", 1)
            upstream = socket.create_connection((host, int(port_s)), timeout=15)
        except Exception as exc:
            print(f"[exit] connect failed: {exc}", flush=True)
            try:
                send_frame(self.connection, str(exc).encode(), opcode=8)
            except OSError:
                pass
            return

        self._pump(self.connection, upstream)

    def _pump(self, ws_sock, upstream):
        sockets = [ws_sock, upstream]
        upstream.setblocking(False)
        while True:
            readable, _, errored = select.select(sockets, [], sockets, 60)
            if errored or not readable:
                break
            for sock in readable:
                if sock is ws_sock:
                    try:
                        opcode, data = read_frame(ws_sock)
                    except OSError:
                        return
                    if opcode == 8 or not data:
                        return
                    upstream.sendall(data)
                else:
                    try:
                        data = upstream.recv(65536)
                    except OSError:
                        return
                    if not data:
                        return
                    send_frame(ws_sock, data)


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", PORT), WebSocketConnectHandler) as server:
        print(f"websocket exit relay listening on {PORT}", flush=True)
        server.serve_forever()
"""


SOCKS_RELAY_SCRIPT = r"""#!/usr/bin/env python3
import base64
import os
import select
import socket
import socketserver
import ssl
import struct

PORT = $PORT
EXIT_HOST = "$EXIT_HOST"


def _recvall(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise OSError("socket closed")
        data += chunk
    return data


def read_frame(sock):
    first = _recvall(sock, 2)
    opcode = first[0] & 0x0F
    masked = bool(first[1] & 0x80)
    length = first[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recvall(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recvall(sock, 8))[0]
    mask = _recvall(sock, 4) if masked else b""
    payload = _recvall(sock, length) if length else b""
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def send_frame(sock, payload, opcode=2, mask=True):
    header = bytearray([0x80 | opcode])
    length = len(payload)
    mask_bit = 0x80 if mask else 0
    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))
    if mask:
        key = os.urandom(4)
        header.extend(key)
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    sock.sendall(header + payload)


def open_exit_socket(target_host, target_port):
    raw = socket.create_connection((EXIT_HOST, 443), timeout=20)
    ws = ssl.create_default_context().wrap_socket(raw, server_hostname=EXIT_HOST)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        "GET / HTTP/1.1\r\n"
        f"Host: {EXIT_HOST}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    ws.sendall(req.encode())
    response = b""
    while b"\r\n\r\n" not in response:
        response += ws.recv(4096)
        if len(response) > 65536:
            raise OSError("oversized websocket response")
    if b" 101 " not in response.split(b"\r\n", 1)[0]:
        raise OSError(response.split(b"\r\n", 1)[0].decode(errors="replace"))
    send_frame(ws, f"{target_host}:{target_port}".encode())
    return ws


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

            upstream = open_exit_socket(target_host, target_port)

            client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            self._pump(client, upstream)
        except Exception as exc:
            print(f"[socks] {exc}", flush=True)
            try:
                client.sendall(b"\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00")
            except OSError:
                pass

    def _pump(self, client, ws_sock):
        sockets = [client, ws_sock]
        client.setblocking(False)
        while True:
            readable, _, errored = select.select(sockets, [], sockets, 60)
            if errored or not readable:
                break
            for sock in readable:
                if sock is client:
                    try:
                        data = client.recv(65536)
                    except OSError:
                        return
                    if not data:
                        return
                    send_frame(ws_sock, data)
                else:
                    try:
                        opcode, data = read_frame(ws_sock)
                    except OSError:
                        return
                    if opcode == 8 or not data:
                        return
                    client.sendall(data)


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", PORT), SocksHandler) as server:
        print(f"socks relay listening on {PORT}, websocket exit={EXIT_HOST}", flush=True)
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


def _ssh(gh: GitHubManager, codespace: str, command: str, *, timeout: int = 30) -> subprocess.CompletedProcess:
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


def _start_remote_script(gh: GitHubManager, codespace: str, script_path: str, label: str) -> None:
    quoted = shlex.quote(script_path)
    cmd = f"nohup python3 {quoted} > {quoted}.log 2>&1 &"
    result = _ssh(gh, codespace, cmd, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Failed to start {script_path}")
    time.sleep(1)


def _wait_local_forward(port: int, process: subprocess.Popen, label: str, timeout: int = 20) -> None:
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
    logger = get_logger()

    if parsed.action == "create":
        if len(parsed.hop) != 2:
            raise ValueError("Exactly two --hop values are required")
        chains = _chains(config)
        chains[parsed.name] = {
            "name": parsed.name,
            "hops": [parse_hop_spec(parsed.hop[0]), parse_hop_spec(parsed.hop[1])],
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

        hops = _ensure_chain_hops(chain, config, gh)
        if len(hops) != 2:
            raise ValueError("Chains must have exactly two hops")

        chains = _chains(config)
        chains[parsed.name] = chain
        config.set("chains", chains)
        config.save()

        hop1, hop2 = hops
        hop1_gh = _manager_for_hop(hop1, config, gh)
        hop2_gh = _manager_for_hop(hop2, config, gh)
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

        _upload(hop2_gh, hop2_name, exit_path, exit_script)
        _start_remote_script(hop2_gh, hop2_name, exit_path, f"csproxy_chain_exit_{hop2_port}")
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

        _upload(hop1_gh, hop1_name, socks_path, socks_script)
        _start_remote_script(hop1_gh, hop1_name, socks_path, f"csproxy_chain_socks_{hop1_port}")

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
        for pid in (entry.get("pid"), entry.get("exit_forward_pid")):
            if not pid:
                continue
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (OSError, ValueError):
                pass
        for hop in entry.get("hops", []):
            name = hop.get("codespace_name")
            if name:
                hop_gh = _manager_for_hop(hop, config, gh)
                _ssh(hop_gh, name, "pkill -f csproxy_chain_ 2>/dev/null || true", timeout=10)
        state.remove_tunnel(tunnel_id=f"chain-{parsed.name}")
        logger.info(f"Stopped chain: {parsed.name}")
        return 0

    return 1


def chain_help() -> str:
    return textwrap.dedent(
        """\
        Chain commands:
          cs-proxy chain create NAME --hop WestEurope --hop EastUs
          cs-proxy chain create NAME --hop eu:WestEurope --hop us:EastUs
          cs-proxy chain start NAME [--port 1080]
          cs-proxy chain status [NAME]
          cs-proxy chain stop NAME
        """
    )
