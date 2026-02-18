# Command Reference

cs-proxy provides four CLI tools, each with its own set of commands.

## Tools Overview

| Tool | Entry Point | Purpose |
|------|-------------|---------|
| [cs-proxy](cs-proxy.md) | `cs-proxy <command>` | SOCKS5/HTTP proxy management |
| [cs-serve](cs-serve.md) | `cs-serve <command>` | Public file hosting and HTTP servers |
| [cs-wg](cs-wg.md) | `sudo cs-wg <command>` | WireGuard VPN tunnel management |
| [cs-tools](cs-tools.md) | `cs-tools <tool> [args]` | Proxied security tool wrappers |

## Global Options

All tools support these flags:

| Flag | Description |
|------|-------------|
| `-c`, `--codespace` | Specify Codespace name (skip interactive selection) |
| `-v`, `--verbose` | Enable debug output |
| `-h`, `--help` | Show help text |

## Common Workflows

### Start a proxy session

```bash
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
cs-tools pffuf -u https://target.com/FUZZ -w wordlist.txt
```
