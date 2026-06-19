# cs-mcp

A [Model Context Protocol](https://modelcontextprotocol.io/) server that exposes the csproxy toolkit to MCP-aware clients (Claude Desktop, Claude Code, Cursor, and any other MCP host). It wraps the same presentation-free service layer as the CLI and TUI, so anything you do through MCP is reflected by `cs-proxy` and vice versa — no logic is reimplemented, only adapted to MCP tools and resources.

The server ships as an optional extra (it pulls in the official `mcp` SDK):

```bash
pip install 'fluffy-barnacle[mcp]'   # one-time: install the optional MCP extra
cs-mcp                               # run the server over stdio
```

`cs-mcp` speaks the **stdio** transport: it reads JSON-RPC on stdin and writes on stdout, and is meant to be launched by an MCP client rather than run by hand. (Running it in a terminal will simply wait for a client to connect.) Logs go to stderr so the transport on stdout stays clean.

## Tools

| Tool | What it does |
|------|--------------|
| `diagnostics` | Dependency/config health checks (same set as `cs-proxy check`) |
| `list_pool` | List tracked SSH proxy tunnels (optionally reconciling dead PIDs) |
| `list_codespaces` | List your GitHub Codespaces (best effort) |
| `get_codespace` | Look up a single codespace by name |
| `get_logs` | Tail `proxy.log` |
| `list_chains` | List defined + running two-hop chains |
| `stop_tunnel` | Stop the tunnel on a port and remove it from the pool |
| `drain_tunnel` | Mark a tunnel draining |
| `rotate_pool` | Return a random healthy tunnel port |
| `stop_all_tunnels` | **Destructive** — stop all tunnels and the HTTP proxy |
| `start_chain` | Start a defined two-hop chain |
| `stop_chain` | **Destructive** — stop a running chain and clean up relays |
| `delete_chain` | **Destructive** — remove a chain definition |
| `create_codespace` | Provision a new Codespace (real, billable infra) |
| `delete_codespace` | **Destructive** — permanently delete a Codespace |
| `start_codespace` | Start a stopped Codespace |
| `stop_codespace` | Stop a running Codespace (keeps it) |

Destructive tools are flagged as such in their descriptions; well-behaved MCP clients surface that and confirm before calling.

## Resources

| URI | Contents |
|-----|----------|
| `cs://pool` | The current SSH tunnel pool (reconciled) |
| `cs://codespaces` | Your current GitHub Codespaces |

Resources let a client pull read-only state without invoking a tool.

## Connecting a client

**Claude Code** — register the server once:

```bash
claude mcp add cs-proxy -- cs-mcp
```

**Claude Desktop / Cursor** — add an entry to the client's MCP config (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "cs-proxy": {
      "command": "cs-mcp"
    }
  }
}
```

If `cs-mcp` is not on the client's `PATH` (for example when it runs outside your shell environment), point `command` at the absolute path inside your virtualenv — e.g. `/path/to/.venv/bin/cs-mcp`.

## Prerequisites

`cs-mcp` runs the same operations as the CLI, so it needs the same setup: the GitHub CLI (`gh`) installed and authenticated, and an SSH key generated (`cs-proxy keygen`). Run the `diagnostics` tool first to confirm the environment is ready.
