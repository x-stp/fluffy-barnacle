# Quick Start

Get cs-proxy running in under a minute.

## Prerequisites

- Python 3.8+
- [GitHub CLI](https://cli.github.com/) (`gh`) installed and authenticated
- `ssh` and `curl` available

## Install

```bash
git clone https://github.com/dstours/fluffy-barnacle.git
cd fluffy-barnacle
pip install -e .
```

## Authenticate

```bash
gh auth login
```

## Start a Proxy

```bash
cs-proxy start
```

This will:

1. Select an existing Codespace (or create one interactively)
2. Start an SSH tunnel with SOCKS5 forwarding on `127.0.0.1:1080`
3. Run in the background with automatic reconnection

## Verify

```bash
cs-tools ipcheck
```

This compares your direct IP with the proxied IP to confirm traffic is routing through the Codespace.

## Use It

### Route tools through the proxy

```bash
cs-tools pcurl https://ifconfig.me
cs-tools pnmap -p 80,443 target.com
cs-tools pffuf -u https://target.com/FUZZ -w wordlist.txt
```

### Serve files publicly

```bash
cs-serve file payload.bin
# Gives you a public https://*.app.github.dev URL
```

### Set up a VPN tunnel

```bash
sudo cs-wg up
sudo cs-wg route add 10.0.0.0/8
```

## Stop

```bash
cs-proxy stop          # stop the proxy tunnel
cs-proxy teardown      # delete the Codespace entirely
```

## Next Steps

- [Installation Guide](user-guide/installation.md) -- platform-specific setup and troubleshooting
- [Configuration](user-guide/configuration.md) -- customize ports, codespace, and behavior
- [Command Reference](user-guide/command-reference/index.md) -- full list of commands
- [Use Cases](use-cases/index.md) -- real-world scenarios and workflows
