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
| **[cs-proxy](user-guide/command-reference/cs-proxy.md)** | SOCKS5 and HTTP proxy via SSH tunnel with auto-reconnect, circuit breaker, pool commands, diagnostics, and two-hop chain mode |
| **[cs-serve](user-guide/command-reference/cs-serve.md)** | Instant public HTTPS file hosting, redirect servers, custom HTTP responses, and data capture via `*.app.github.dev` |
| **[cs-wg](user-guide/command-reference/cs-wg.md)** | Full WireGuard VPN tunnel with route management and traffic monitoring |
| **[cs-tools](user-guide/command-reference/cs-tools.md)** | Drop-in wrappers for nmap, ffuf, httpx, nuclei, sqlmap with automatic SOCKS5 proxy arguments and smart tunnel rotation |

Each tool can be used from the CLI or imported directly as a [Python library](development/python-api.md).

## What's New

- **Smart tunnel rotation** — `cs-tools` automatically distributes traffic across healthy tunnels
- **`cs-proxy check`** — One-command diagnostics for setup, auth, ports, and state health
- **`cs-proxy doctor --fix`** — Safe local repair for config, proxychains output, and stale tunnel state
- **`cs-proxy pool`** — Inspect healthy tunnel entries, drain ports, and print a rotatable port for scripts
- **Two-hop chains** — Route one local SOCKS endpoint through two Codespaces, with optional named accounts per hop
- **`--dry-run`** — Preview what `start`/`stop` would do without making changes
- **Profiles** — Switch between preset configs (e.g. `redteam` / `stealth`) without editing files
- **Circuit breaker** — Tunnels that fail health checks 3× in a row are automatically marked dead
- **Shell completion** — Bash and zsh completion via `cs-proxy completion bash`
- **PAC file generation** — `cs-proxy pac` outputs a Proxy Auto-Config script for browser routing
- **Status watch mode** — `cs-proxy status --watch` auto-refreshes every 2 seconds
- **cs-tools global flags** — `--port`, `--host`, `--dry-run`, and `--timeout` work across all wrappers
- **nmap sanitization** — `pnmap` strips incompatible flags (`-sS`, `-sU`, `-O`) and warns about root/SYN-scan IP leakage
- **Health check caching** — `cs-tools` caches proxy health for 5 seconds instead of checking on every invocation
- **Unified proxy env** — Tools with native proxy support automatically get `ALL_PROXY`, `HTTP_PROXY`, `HTTPS_PROXY`

## Getting Started

```bash
pip install -e .
gh auth login
cs-proxy check
cs-proxy start
cs-tools ipcheck
```

See the [Quick Start](quickstart.md) for a full walkthrough, or jump to the [Installation Guide](user-guide/installation.md) for platform-specific setup.
