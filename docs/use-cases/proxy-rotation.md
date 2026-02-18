# Proxy Rotation

Rotate your egress IP by cycling GitHub Codespaces. Each Codespace gets a fresh IP from GitHub's Azure infrastructure.

## Pre-Create Multiple Codespaces

Create 2 codespaces upfront so you have a spare ready for quick switching:

```bash
cs-proxy -n 2 start
```

This creates 2 codespaces and proxies through the first one. To switch to the other:

```bash
cs-proxy list                 # see available codespaces
cs-proxy set <other-name>     # switch active codespace
cs-proxy restart              # reconnect through the new one
cs-tools ipcheck              # verify different exit IP
```

## Manual Rotation

For full IP rotation (new IP each cycle), tear down and recreate:

```bash
# Start with first IP
cs-proxy start
cs-tools ipcheck          # note the exit IP

# Rotate: tear down and recreate
cs-proxy teardown          # deletes the Codespace
cs-proxy start             # creates a new one with a fresh IP
cs-tools ipcheck          # new exit IP
```

## Scripted Rotation

```python
from csproxy import SSHTunnel, Config, GitHubManager, CodespaceSelector
import time

config = Config()
gh = GitHubManager()

for i in range(5):
    # Create a new codespace
    selector = CodespaceSelector(gh, config)
    cs_name = selector.select()

    # Start tunnel
    tunnel = SSHTunnel(config, cs_name)
    tunnel.start()
    time.sleep(3)

    # Do your work here
    print(f"Rotation {i+1}: proxied through {cs_name}")

    # Tear down
    tunnel.stop()
    gh.run_gh_command(['codespace', 'delete', '--codespace', cs_name, '-f'])
    time.sleep(5)
```

## Tips

- Codespace creation takes 30-60 seconds. Factor this into your rotation timing.
- GitHub's free tier includes 120 core-hours/month. A 2-core Codespace gives you 60 hours.
- The free tier allows a maximum of 2 codespaces. Use `-n 2` to pre-create both.
- Codespaces that sit idle are automatically stopped after 30 minutes, saving billing.
- Use `cs-proxy teardown` (not just `stop`) to fully delete and free resources.
