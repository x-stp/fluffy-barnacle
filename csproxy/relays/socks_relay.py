#!/usr/bin/env python3
"""SOCKS-to-WebSocket relay for csproxy chain mode."""

from __future__ import annotations

import base64
import os
import select
import socket
import socketserver
import ssl
import struct
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
EXIT_HOST = _env_required("CS_PROXY_EXIT_HOST")
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
        f"X-CSProxy-Chain-Secret: {RELAY_SECRET}\r\n"
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


def main() -> None:
    with Server(("0.0.0.0", PORT), SocksHandler) as server:
        print(f"socks relay listening on {PORT}, websocket exit={EXIT_HOST}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
