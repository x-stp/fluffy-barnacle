<p align="center">
  <img src="assets/logo.png" alt="fluffy-barnacle" width="280">
</p>

# Fluffy-Barnacle

**Disposable, ephemeral network infrastructure powered by GitHub Codespaces.** 

Deploy SOCKS5 proxies, HTTPS file hosting, and WireGuard tunnels in seconds, for free.

## Overview

Fluffy-Barnacle is an operator-focused toolkit that turns GitHub Codespaces into free, ephemeral network infrastructure. It provides a suite of CLI tools for rapid deployment and teardown.

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
