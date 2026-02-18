<p align="center">
  <img src="assets/logo.png" alt="fluffy-barnacle" width="280">
</p>

# fluffy-barnacle

**Disposable network infrastructure powered by GitHub Codespaces. SOCKS5 proxies, HTTPS file hosting, and WireGuard VPN tunnels -- free and ephemeral.**

## Overview

fluffy-barnacle is an operator-focused toolkit built around GitHub Codespaces as free, ephemeral network infrastructure. It wraps the GitHub CLI to automate the full lifecycle -- spinning up a Codespace, establishing SSH tunnels, forwarding ports, and tearing everything down cleanly.

Because Codespace IPs rotate each time you create one, it also works as a quick egress rotation mechanism.

## Tools

| Tool | Description |
|------|-------------|
| **[cs-proxy](user-guide/command-reference/cs-proxy.md)** | SOCKS5 and HTTP proxy via SSH tunnel with auto-reconnect and Burp Suite integration |
| **[cs-serve](user-guide/command-reference/cs-serve.md)** | Instant public HTTPS file hosting, redirect servers, and custom HTTP responses via `*.app.github.dev` |
| **[cs-wg](user-guide/command-reference/cs-wg.md)** | Full WireGuard VPN tunnel with route management and traffic monitoring |
| **[cs-tools](user-guide/command-reference/cs-tools.md)** | Drop-in wrappers for nmap, ffuf, httpx, nuclei, sqlmap with automatic SOCKS5 proxy arguments |

Each tool can be used from the CLI or imported directly as a [Python library](development/python-api.md).

## Getting Started

```bash
pip install -e .
gh auth login
cs-proxy start
cs-tools ipcheck
```

See the [Quick Start](quickstart.md) for a full walkthrough, or jump to the [Installation Guide](user-guide/installation.md) for platform-specific setup.
