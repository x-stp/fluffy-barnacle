#!/usr/bin/env python3
"""
Embedded text templates for remote server scripts, configuration files, and help text.

These templates are used across proxy, wireguard, and serve modules.
Separated to keep source modules focused on logic.
"""

# =============================================================================
# Serve module templates - Python HTTP server scripts uploaded to Codespace
# =============================================================================

_START_HELPER = """\
import time, subprocess, os

def start_server(handler, port, retries=5):
    from http.server import HTTPServer
    HTTPServer.allow_reuse_address = True
    for attempt in range(retries):
        try:
            server = HTTPServer(('', port), handler)
            server.serve_forever()
        except OSError as e:
            if attempt < retries - 1:
                print(f'Port {{port}} busy, killing and retrying ({{attempt+1}}/{{retries}})...', flush=True)
                subprocess.run(f'fuser -k -9 {{port}}/tcp 2>/dev/null; lsof -ti:{{port}} | xargs kill -9 2>/dev/null', shell=True)
                time.sleep(2)
            else:
                raise
"""

FILE_SERVER_SCRIPT = _START_HELPER + """\
from http.server import SimpleHTTPRequestHandler

class NoListingHandler(SimpleHTTPRequestHandler):
    def list_directory(self, path):
        self.send_error(403, "Directory listing disabled")
        return None

    def log_message(self, format, *args):
        print(f"[REQUEST] {{args[0]}}", flush=True)

os.chdir("/tmp/serve")
print(f"Serving on port {PORT}...", flush=True)
start_server(NoListingHandler, {PORT})
"""

REDIRECT_SERVER_SCRIPT = _START_HELPER + """\
from http.server import BaseHTTPRequestHandler

TARGET_URL = {TARGET_URL!r}
REDIRECT_CODE = {REDIRECT_CODE}

class RedirectHandler(BaseHTTPRequestHandler):
    def _redirect(self):
        if TARGET_URL.startswith(('http://', 'https://')) and self.path not in ('/', ''):
            redirect_url = TARGET_URL.rstrip('/') + self.path
        else:
            redirect_url = TARGET_URL

        print(f'[REDIRECT {{REDIRECT_CODE}}] {{self.path}} -> {{redirect_url}}', flush=True)
        print(f'  Client: {{self.client_address[0]}}', flush=True)
        print(f'  User-Agent: {{self.headers.get("User-Agent", "N/A")}}', flush=True)

        self.send_response(REDIRECT_CODE)
        self.send_header('Location', redirect_url)
        self.send_header('Content-Length', '0')
        self.end_headers()

    do_GET = do_POST = do_HEAD = _redirect

    def log_message(self, format, *args):
        pass

print(f'Redirect server on port {PORT}', flush=True)
print(f'Redirecting to: {{TARGET_URL}}', flush=True)
print(f'Redirect type: {{REDIRECT_CODE}}', flush=True)
print('=' * 50, flush=True)
start_server(RedirectHandler, {PORT})
"""

CUSTOM_SERVER_SCRIPT = _START_HELPER + """\
from http.server import BaseHTTPRequestHandler

RESPONSE_BODY = {RESPONSE_BODY!r}
CONTENT_TYPE = {CONTENT_TYPE!r}
STATUS_CODE = {STATUS_CODE}

class CustomHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        print(f'[REQUEST] {{self.command}} {{self.path}}', flush=True)
        print(f'  Client: {{self.client_address[0]}}', flush=True)
        for header, value in self.headers.items():
            print(f'  {{header}}: {{value}}', flush=True)
        print(flush=True)

        body = RESPONSE_BODY.encode('utf-8')
        self.send_response(STATUS_CODE)
        self.send_header('Content-Type', CONTENT_TYPE)
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        print(f'[REQUEST] {{self.command}} {{self.path}}', flush=True)
        print(f'  Client: {{self.client_address[0]}}', flush=True)
        print(f'  Body: {{post_data.decode("utf-8", errors="replace")}}', flush=True)
        print(flush=True)
        self.do_GET()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    def log_message(self, format, *args):
        pass

print(f'Custom server on port {PORT}', flush=True)
print(f'Status: {{STATUS_CODE}}, Content-Type: {{CONTENT_TYPE}}', flush=True)
print('=' * 50, flush=True)
start_server(CustomHandler, {PORT})
"""


# =============================================================================
# WireGuard remote setup script template
# =============================================================================

WG_REMOTE_SETUP_SCRIPT = """\
#!/usr/bin/env bash
set -euo pipefail

echo "[*] Fixing apt sources if needed..."
sudo rm -f /etc/apt/sources.list.d/yarn.list 2>/dev/null || true

echo "[*] Installing WireGuard..."
sudo apt-get update -o Acquire::AllowInsecureRepositories=true 2>/dev/null || true
sudo apt-get install -y wireguard-tools iptables socat --no-install-recommends 2>/dev/null || {{
    echo "[!] apt install failed, trying with --fix-broken"
    sudo apt-get install -y --fix-broken wireguard-tools iptables socat --no-install-recommends
}}

echo "[*] Creating WireGuard config..."
sudo mkdir -p /etc/wireguard

sudo tee /etc/wireguard/wg0.conf > /dev/null << 'WGCONF'
[Interface]
PrivateKey = {remote_private_key}
Address = {wg_remote_ip}
ListenPort = {wg_port}
PostUp = iptables -I FORWARD 1 -i wg0 -o eth0 -j ACCEPT; iptables -I FORWARD 2 -i eth0 -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -A POSTROUTING -s {wg_network} -o eth0 -j MASQUERADE; sysctl -w net.ipv4.ip_forward=1
PostDown = iptables -D FORWARD -i wg0 -o eth0 -j ACCEPT; iptables -D FORWARD -i eth0 -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -D POSTROUTING -s {wg_network} -o eth0 -j MASQUERADE || true

[Peer]
PublicKey = {local_public_key}
AllowedIPs = {local_ip_host}/32
WGCONF

sudo chmod 600 /etc/wireguard/wg0.conf

echo "[*] Stopping any existing WireGuard..."
sudo wg-quick down wg0 2>/dev/null || true

echo "[*] Starting WireGuard..."
sudo wg-quick up wg0

echo "[*] WireGuard status:"
sudo wg show

echo "[*] Starting TCP-to-UDP relay for tunnel..."
pkill -f 'socat.*TCP-LISTEN.*51821' 2>/dev/null || true
nohup socat TCP-LISTEN:51821,reuseaddr,fork UDP:127.0.0.1:51820 > /tmp/socat_relay.log 2>&1 &
sleep 1
if pgrep -f 'socat.*TCP-LISTEN.*51821' > /dev/null; then
    echo "[+] Socat relay started on port 51821"
else
    echo "[!] Warning: socat relay may not have started"
fi

echo ""
echo "[+] WireGuard is running on port {wg_port}"
echo "[+] Remote IP: {remote_ip_host}"
echo "[+] TCP relay port: 51821"
"""
