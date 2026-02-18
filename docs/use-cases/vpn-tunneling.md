# VPN Tunneling

Route traffic through a full WireGuard VPN tunnel for tools that don't support SOCKS proxies or proxychains.

Unlike the SOCKS5 proxy, WireGuard operates at the kernel level -- all traffic from the interface is transparently tunneled without application-level proxy support.

## Start the Tunnel

```bash
sudo cs-wg up
```

This generates keys, configures the Codespace, sets up the SSH relay, and creates the local WireGuard interface.

## Route Specific Targets

```bash
# Route a single IP
sudo cs-wg route add 93.184.216.34

# Route a subnet
sudo cs-wg route add 10.0.0.0/8

# Route a hostname (resolved to IP)
sudo cs-wg route add target.example.com
```

## Route All Traffic

```bash
sudo cs-wg route all
```

This uses the `0.0.0.0/1` + `128.0.0.0/1` split route technique. Bypass routes for GitHub and Azure IPs are added automatically so the tunnel itself stays connected.

### Restore Normal Routing

```bash
sudo cs-wg route restore
```

## Test the Tunnel

```bash
# Ping the remote end
ping 10.99.99.1

# Check exit IP through the tunnel interface
curl --interface cswg0 https://ifconfig.me

# Check status
sudo cs-wg status
```

## Monitor Traffic

```bash
sudo cs-wg monitor http      # HTTP requests
sudo cs-wg monitor dns       # DNS queries
sudo cs-wg monitor hosts     # unique destination hosts
sudo cs-wg monitor leak      # detect traffic bypassing the tunnel
```

## When to Use VPN vs SOCKS5

| Feature | SOCKS5 (`cs-proxy`) | WireGuard (`cs-wg`) |
|---------|-------------------|-------------------|
| Setup complexity | Low | Medium (needs root) |
| Application support | Needs SOCKS/proxychains support | Transparent, works with everything |
| Performance | Good | Better (kernel-level) |
| Protocol support | TCP only | TCP, UDP, ICMP |
| DNS routing | Optional | Automatic |
| Route specificity | Per-application | Per-subnet |

## Tear Down

```bash
sudo cs-wg down
```

This removes the interface, restores routing and DNS, kills relay processes, and cleans up the Codespace.
