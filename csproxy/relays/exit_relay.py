#!/usr/bin/env python3
"""WebSocket-to-TCP exit relay for csproxy chain mode."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import select
import socket
import socketserver
import struct
from http.server import BaseHTTPRequestHandler
from pathlib import Path


def _env_required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _secret() -> str:
    secret_file = os.environ.get("CS_PROXY_RELAY_SECRET_FILE", "")
    if secret_file:
        return Path(secret_file).read_text().strip()
    return _env_required("CS_PROXY_RELAY_SECRET")


PORT = int(_env_required("CS_PROXY_RELAY_PORT"))
RELAY_SECRET = _secret()


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
        provided_secret = self.headers.get("X-CSProxy-Chain-Secret", "")
        if not hmac.compare_digest(provided_secret, RELAY_SECRET):
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
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


def main() -> None:
    with Server(("0.0.0.0", PORT), WebSocketConnectHandler) as server:
        print(f"websocket exit relay listening on {PORT}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
