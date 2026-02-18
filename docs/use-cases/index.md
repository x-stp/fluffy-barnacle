# Use Cases

cs-proxy is designed for authorized security testing scenarios where you need ephemeral, rotating network infrastructure.

## Scenarios

### [Proxy Rotation](proxy-rotation.md)

Rotate egress IPs for scanning and reconnaissance by cycling Codespaces. Each new Codespace gets a fresh IP from GitHub's Azure infrastructure.

### [File Hosting](file-hosting.md)

Host payloads, redirect servers, and custom HTTP responses on public HTTPS URLs for SSRF testing, phishing simulations, and exfiltration endpoints.

### [VPN Tunneling](vpn-tunneling.md)

Route all or specific traffic through a WireGuard VPN for tools that don't support SOCKS proxies or proxychains.

### [Burp Suite Integration](burp-integration.md)

Chain cs-proxy with Burp Suite for proxied web application testing with full interception capabilities.
