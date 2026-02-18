# Burp Suite Integration

Chain cs-proxy with Burp Suite for proxied web application testing with full interception capabilities.

## Architecture

```
Browser --> Burp Suite (127.0.0.1:8080) --> HTTP Proxy (tinyproxy) --> SOCKS5 Tunnel --> Codespace --> Target
```

## Setup

### 1. Start the SOCKS5 Proxy

```bash
cs-proxy start
```

### 2. Start the HTTP Proxy

```bash
cs-proxy http
```

This starts tinyproxy on port 8080, configured to route upstream through the SOCKS5 tunnel.

### 3. Get Burp Configuration

```bash
cs-proxy burp
```

This prints the upstream proxy settings to paste into Burp.

### 4. Configure Burp Suite

1. Open **User options** (or **Settings** in newer versions)
2. Go to **Network** > **Connections** > **Upstream Proxy Servers**
3. Click **Add**
4. Set:
   - **Destination host:** `*`
   - **Proxy host:** `127.0.0.1`
   - **Proxy port:** `8080`
   - **Proxy type:** HTTP

### 5. Verify

Browse to `https://ifconfig.me` through Burp. The IP shown should be the Codespace IP, not your real IP.

```bash
# Cross-check with CLI
cs-tools ipcheck
```

## Using with Scope

You can route only specific targets through the proxy by configuring Burp's upstream proxy rules:

1. Add a rule with **Destination host:** `*.target.com`
2. Point it at the cs-proxy HTTP proxy
3. Leave other traffic direct

## Notes

- The HTTP proxy (tinyproxy) is required because Burp's upstream proxy doesn't support SOCKS5 directly
- `cs-proxy http` automatically configures tinyproxy with the correct SOCKS5 upstream
- Both `cs-proxy start` and `cs-proxy http` must be running for this to work
- Use `cs-proxy stop` to tear down both the SOCKS5 tunnel and HTTP proxy
