# cs-wg

WireGuard VPN tunnel through a GitHub Codespace.

Sets up a full WireGuard interface on your local machine with the Codespace as the remote peer. Traffic routes at the kernel level rather than through a SOCKS proxy, which works with tools that don't support proxychains.

!!! warning "Root Required"
    Most cs-wg commands require root privileges for WireGuard interface and route management.

## Usage

```
sudo cs-wg <command> [options]
```

## Commands

### Tunnel Management

#### `up`

Start the WireGuard tunnel.

```bash
sudo cs-wg up
sudo cs-wg up -c my-codespace
```

This will:

1. Generate WireGuard keypairs (local and remote)
2. Select and start a Codespace
3. Upload and run the WireGuard setup script on the Codespace
4. Set up an SSH tunnel for UDP relay (WireGuard over TCP)
5. Create the local WireGuard interface
6. Test connectivity with a ping

#### `down`

Stop the WireGuard tunnel and clean up all state.

```bash
sudo cs-wg down
```

Removes the WireGuard interface, stops socat relays, kills SSH tunnels, restores routing and DNS, and cleans up the remote Codespace.

#### `status`

Show tunnel status, connectivity, and exit IP.

```bash
sudo cs-wg status
```

### Route Management

#### `route add`

Route a specific IP or subnet through the tunnel.

```bash
sudo cs-wg route add 93.184.216.34
sudo cs-wg route add 10.0.0.0/8
sudo cs-wg route add example.com       # resolves to IP automatically
```

#### `route del`

Remove a route.

```bash
sudo cs-wg route del 10.0.0.0/8
```

#### `route all`

Route all traffic through the tunnel.

```bash
sudo cs-wg route all
```

Uses the `0.0.0.0/1` + `128.0.0.0/1` split route technique. Automatically adds bypass routes for GitHub and Azure IPs so the tunnel itself doesn't break.

#### `route restore`

Restore normal routing (remove all tunnel routes).

```bash
sudo cs-wg route restore
```

### Traffic Monitoring

#### `monitor`

Monitor traffic on the WireGuard interface using tcpdump.

```bash
sudo cs-wg monitor           # default: HTTP traffic
sudo cs-wg monitor http      # HTTP requests
sudo cs-wg monitor dns       # DNS queries
sudo cs-wg monitor hosts     # unique destination hosts
sudo cs-wg monitor conns     # connection summary
sudo cs-wg monitor all       # all traffic
sudo cs-wg monitor leak      # detect traffic NOT going through tunnel
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-c`, `--codespace` | Codespace name | auto-select |

## Network Configuration

Default values (override via environment variables):

| Setting | Default | Environment Variable |
|---------|---------|---------------------|
| Interface | `cswg0` | `WG_INTERFACE` |
| Listen port | `51820` | `WG_PORT` |
| Local IP | `10.99.99.2/24` | `WG_LOCAL_IP` |
| Remote IP | `10.99.99.1/24` | `WG_REMOTE_IP` |
| Network | `10.99.99.0/24` | `WG_NETWORK` |

## Architecture

```
Local Machine                    Codespace
+------------------+            +------------------+
| WireGuard (cswg0)|            | WireGuard (wg0)  |
| 10.99.99.2       |            | 10.99.99.1       |
+--------+---------+            +--------+---------+
         |                               |
    UDP :51820                      UDP :51820
         |                               |
+--------+---------+            +--------+---------+
| socat UDP->TCP   |            | socat TCP->UDP   |
+--------+---------+            +--------+---------+
         |                               |
    TCP :51821  ---- SSH Tunnel ----  TCP :51821
```

WireGuard uses UDP, but GitHub Codespace SSH tunnels only support TCP. socat bridges the gap on both ends.

## Files

| Path | Description |
|------|-------------|
| `~/.config/cs-proxy/wireguard/` | Keys and configuration |
| `~/.config/cs-proxy/wireguard/local_private.key` | Local WireGuard private key |
| `~/.config/cs-proxy/wireguard/local_public.key` | Local WireGuard public key |
| `~/.config/cs-proxy/wireguard/remote_private.key` | Remote WireGuard private key |
| `~/.config/cs-proxy/wireguard/remote_public.key` | Remote WireGuard public key |
| `~/.config/cs-proxy/wireguard/cswg0.conf` | Generated WireGuard config |
