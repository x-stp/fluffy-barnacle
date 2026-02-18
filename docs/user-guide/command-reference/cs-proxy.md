# cs-proxy

SOCKS5 and HTTP proxy management via SSH tunnel to a GitHub Codespace.

## Usage

```
cs-proxy <command> [options]
```

## Commands

### Tunnel Management

#### `start`

Start a SOCKS5 proxy tunnel to a Codespace.

```bash
cs-proxy start
cs-proxy start -c my-codespace-name
cs-proxy start -p 9050
cs-proxy -n 2 start                  # create 2 codespaces, proxy through first
```

Starts an SSH tunnel with SOCKS5 dynamic port forwarding. The tunnel runs in the background with automatic reconnection using exponential backoff.

When `-n` is greater than 1, creates multiple codespaces and uses the first one as the active proxy. The extra codespace is available as a spare for manual rotation via `cs-proxy set`.

#### `stop`

Stop the proxy tunnel and HTTP proxy.

```bash
cs-proxy stop
```

#### `restart`

Restart the proxy tunnel.

```bash
cs-proxy restart
```

#### `status`

Show tunnel status, Codespace state, and exit IP.

```bash
cs-proxy status
```

### HTTP Proxy

#### `http`

Start an HTTP proxy (tinyproxy) that connects upstream to the SOCKS5 tunnel.

```bash
cs-proxy http
```

This is useful for tools that support HTTP proxies but not SOCKS5. The HTTP proxy listens on port 8080 by default.

### Configuration

#### `env`

Print environment export statements for shell integration.

```bash
eval $(cs-proxy env)
```

Exports `http_proxy`, `https_proxy`, `ALL_PROXY`, and `SOCKS_PROXY`.

#### `burp`

Print Burp Suite upstream proxy configuration.

```bash
cs-proxy burp
```

#### `proxychains`

Generate a proxychains4 configuration file.

```bash
cs-proxy proxychains
```

#### `set`

Set a configuration value.

```bash
cs-proxy set socks_port 9050
cs-proxy set codespace_name my-codespace
```

#### `config`

Manage configuration files.

```bash
cs-proxy config
```

### Codespace Management

#### `list`

List available Codespaces.

```bash
cs-proxy list
```

#### `create`

Create a new Codespace interactively.

```bash
cs-proxy create
```

#### `teardown` / `down`

Delete the current Codespace.

```bash
cs-proxy teardown
```

#### `name`

Get or set the current Codespace name.

```bash
cs-proxy name                    # show current
cs-proxy name my-codespace       # set
```

### Utilities

#### `ssh`

Open an SSH session to the Codespace.

```bash
cs-proxy ssh
```

#### `run`

Run a command through the proxy.

```bash
cs-proxy run curl https://ifconfig.me
```

#### `keygen`

Generate an SSH keypair for Codespace authentication.

```bash
cs-proxy keygen
```

#### `split`

Set up split tunneling routes.

```bash
cs-proxy split
```

#### `logs`

Show tunnel logs.

```bash
cs-proxy logs
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-p`, `--port` | SOCKS5 proxy port | `1080` |
| `-n`, `--num-proxies` | Number of codespaces to create (max 2) | `1` |
| `-c`, `--codespace` | Codespace name | auto-select |
| `-v`, `--verbose` | Verbose output | off |
