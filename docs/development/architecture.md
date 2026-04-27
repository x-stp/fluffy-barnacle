# Architecture

## Module Structure

```
csproxy/
├── __init__.py          # Public API exports
├── __main__.py          # python -m csproxy entry point
├── cli.py               # CLI argument parsing and dispatch
│
├── proxy.py             # SOCKS5/HTTP proxy commands and config
├── chains.py            # Two-hop Codespaces chain commands and relays
├── accounts.py          # Named GitHub account configuration
├── serve.py             # File server commands
├── wireguard.py         # WireGuard VPN commands
├── tools.py             # Proxied tool wrappers
│
├── github.py            # GitHub CLI integration (gh wrapper)
├── runner.py            # Shared subprocess command runner
├── codespace.py         # Codespace selection and lifecycle
├── state.py             # Local tunnel/process state store
├── tunnel.py            # SSHTunnel and HTTPProxyManager classes
├── display.py           # Output formatting (status, help, env exports)
├── templates.py         # Embedded server/setup script templates
│
├── wg_setup.py          # WireGuard key generation and codespace setup
├── wg_routes.py         # WireGuard route management
├── wg_monitor.py        # WireGuard traffic monitoring
│
└── utils/
    ├── __init__.py      # Re-exports Config, get_logger, etc.
    ├── config.py        # YAML configuration management
    ├── logging.py       # Colored logging setup
    ├── errors.py        # Exception hierarchy
    └── deps.py          # External dependency checking
```

## Entry Points

Four CLI tools are defined in `pyproject.toml`:

| Entry Point | Function | Module |
|-------------|----------|--------|
| `cs-proxy` | `main_proxy()` | `csproxy.cli` |
| `cs-serve` | `main_serve()` | `csproxy.cli` |
| `cs-wg` | `main_wg()` | `csproxy.cli` |
| `cs-tools` | `main_tools()` | `csproxy.tools` |

Each entry point in `cli.py` parses arguments, initializes `Config` and `GitHubManager`, then dispatches to a `COMMANDS` dict in the corresponding module (e.g., `proxy.COMMANDS`, `serve.COMMANDS`).

## Command Dispatch

Each main module (`proxy.py`, `serve.py`, `wireguard.py`) follows the same pattern:

```python
# Command handlers
def cmd_start(args, config, gh):
    ...
    return 0

def cmd_stop(args, config, gh):
    ...
    return 0

# Dispatch table
COMMANDS = {
    'start': cmd_start,
    'stop': cmd_stop,
    ...
}
```

`cli.py` looks up the command string in the `COMMANDS` dict and calls the handler.

`cs-proxy chain` is implemented in `chains.py` and is exposed through `proxy.COMMANDS` so it shares the same config, logging, dry-run, and account infrastructure as other proxy commands.

## Key Classes

### `SSHTunnel` (tunnel.py)

Manages the SSH SOCKS5 tunnel lifecycle. Handles starting `gh codespace ssh` with dynamic port forwarding, PID tracking, health checks, and automatic reconnection with exponential backoff.

### `HTTPProxyManager` (tunnel.py)

Manages tinyproxy as an HTTP proxy upstream of the SOCKS5 tunnel. Used for Burp Suite integration and tools that only support HTTP proxies.

### `CodespaceSelector` (codespace.py)

Interactive Codespace selection and creation. Handles auto-selection (single Codespace), interactive prompts (multiple), and creation of new Codespaces.

### `GitHubManager` (github.py)

Thin wrapper around the `gh` CLI. Provides methods for listing Codespaces, running arbitrary `gh` commands, and managing authentication. It can run against a `GitHubAccount`, which injects a token from the configured environment variable for account-aware workflows.

### `GitHubAccount` (accounts.py)

Named account metadata for multi-account workflows. Accounts store the token environment variable name, not the token value.

### `CommandRunner` (runner.py)

Shared subprocess wrapper used by `GitHubManager` and tests. It centralizes timeout defaults, environment merging, dry-run behavior, and token redaction.

### `State` (state.py)

JSON-backed local state for tracked tunnels. It records tunnel PIDs, ports, health, Codespace names, and chain entries so status, pool, and cleanup commands can reconcile local process state.

### Chain Relay (`chains.py`)

Chain mode starts a SOCKS relay on the first Codespace and a WebSocket exit relay on the second Codespace. Local traffic enters through a `gh codespace ports forward` listener, traverses the first hop, then exits from the second hop to the final target. Startup waits for local forwards before reporting a chain as healthy.

### `Config` (utils/config.py)

YAML-based configuration with environment variable overrides. Provides property accessors for all settings and handles file I/O with secure permissions.

## Design Decisions

**Why subprocess over API calls?**
cs-proxy delegates to `gh` (GitHub CLI) rather than calling the GitHub API directly. This leverages `gh`'s built-in authentication, SSH key management, and Codespace SSH tunneling without reimplementing them.

**Why embedded script templates?**
Server scripts and WireGuard setup scripts are generated locally and uploaded via stdin to the Codespace. This avoids file-level dependencies on the Codespace and makes the setup self-contained.

**Why socat for WireGuard?**
WireGuard uses UDP, but `gh codespace ssh` only supports TCP port forwarding. socat bridges UDP-to-TCP on both ends of the SSH tunnel.
