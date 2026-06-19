# Command Reference

cs-proxy provides five commands, each with its own set of subcommands.

## Tools Overview

| Tool | Entry Point | Purpose |
|------|-------------|---------|
| [cs-proxy](cs-proxy.md) | `cs-proxy [options] <command>` | SOCKS5/HTTP proxy management with circuit breaker, dry-run, diagnostics, pool commands, and two-hop chains |
| [cs-serve](cs-serve.md) | `cs-serve <command>` | Public file hosting and HTTP servers |
| [cs-wg](cs-wg.md) | `sudo cs-wg <command>` | WireGuard VPN tunnel management |
| [cs-tools](cs-tools.md) | `cs-tools <tool> [args]` | Proxied security tool wrappers with smart tunnel rotation |
| [cs-tui](cs-tui.md) | `cs-tui` | Interactive terminal dashboard to monitor and manage tunnels, codespaces, and chains |
| [cs-mcp](cs-mcp.md) | `cs-mcp` | MCP server exposing the toolkit to MCP-aware clients (Claude Desktop, Claude Code, Cursor) |

## Global Options

All tools support these flags:

| Flag | Description |
|------|-------------|
| `-c`, `--codespace` | Specify Codespace name (skip interactive selection) |
| `-v`, `--verbose` | Enable debug output |
| `-h`, `--help` | Show help text |
| `--dry-run` | Show what would happen without making changes (`cs-proxy` only) |

## Common Workflows

### Start a proxy session

```bash
cs-proxy check          # verify setup first
cs-proxy start
cs-proxy status
cs-tools ipcheck
```

### Serve a file publicly

```bash
cs-serve file payload.bin
# Access via the printed https://*.app.github.dev URL
```

### Full VPN tunnel

```bash
sudo cs-wg up
sudo cs-wg route all
sudo cs-wg status
```

### Scan through the proxy

```bash
cs-proxy start
cs-tools pnmap -p 80,443,8080 target.com
cs-tools pffuf -u https://target.com/FUZZ -w list.txt
```

### Route through a two-hop chain

```bash
cs-proxy chain create eu-us --hop WestEurope --hop EastUs
cs-proxy chain start eu-us --port 1080
curl --socks5-hostname 127.0.0.1:1080 https://ifconfig.me
cs-proxy chain stop eu-us
```
