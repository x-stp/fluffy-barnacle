#!/usr/bin/env python3
"""
cs-proxy - SOCKS5/HTTP proxy management via GitHub Codespaces.

Converts GitHub Codespaces into SOCKS5 and HTTP proxies by establishing
SSH tunnels. Provides automatic Codespace selection, reconnect logic, and
integration with common security tools.
"""

import os
import time
from pathlib import Path

from .github import GitHubManager
from .runner import CommandRunner
from .state import State
from .chains import cmd_chain
from .utils import (
    Config,
    GitHubAuthError,
    check_dependencies,
    eprint,
    get_logger,
    prompt,
)

# Re-export classes from extracted modules for backward compatibility
from .tunnel import SSHTunnel, HTTPProxyManager  # noqa: F401
from .codespace import CodespaceSelector  # noqa: F401
from .display import (  # noqa: F401
    print_env_exports,
    print_usage_examples,
    print_burp_config,
    print_diagnostics,
    show_status,
    show_logs,
    show_help,
)

VERSION = "1.0.0"


# =============================================================================
# Configuration Utilities
# =============================================================================


class ProxychainsConfig:
    """Generate proxychains configuration files."""

    @staticmethod
    def generate(config: Config) -> None:
        """Generate proxychains.conf file."""
        logger = get_logger()
        conf_file = config.config_dir / "proxychains.conf"

        content = f"""# Proxychains configuration for cs-proxy
# Generated on {time.strftime('%Y-%m-%d %H:%M:%S')}

# Quiet mode (no output)
quiet_mode

# Proxy DNS requests through the proxy
proxy_dns

# Timeouts
tcp_read_time_out 15000
tcp_connect_time_out 8000

# ProxyList
[ProxyList]
socks5 127.0.0.1 {config.socks_port}
"""
        conf_file.write_text(content)
        conf_file.chmod(0o600)
        logger.info(f"Proxychains config generated: {conf_file}")

        print("\nUsage:")
        print(f"  proxychains4 -f {conf_file} <command>")
        print("  # or add alias:")
        print(f"  alias pcs='proxychains4 -f {conf_file}'")


# =============================================================================
# SSH Key Management
# =============================================================================


def generate_ssh_key(config: Config) -> None:
    """Generate SSH keypair for Codespace access."""
    logger = get_logger()
    key_file = config.config_dir / "codespace_key"

    if key_file.exists():
        logger.warning(f"SSH key already exists at {key_file}")
        answer = prompt("Regenerate? [y/N] ").strip().lower()
        if answer != "y":
            return

    logger.info("Generating SSH key for Codespace access...")
    runner = CommandRunner()

    datestamp = time.strftime("%Y%m%d")
    result = runner.run(
        [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-f",
            str(key_file),
            "-N",
            "",
            "-C",
            f"cs-proxy-{datestamp}",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"ssh-keygen failed: {result.stderr}")

    key_file.chmod(0o600)
    pub_key_file = key_file.with_suffix(".pub")
    if pub_key_file.exists():
        pub_key_file.chmod(0o644)

    logger.info("SSH key generated successfully")
    print("\nAdd this public key to your GitHub account:")
    print("Settings -> SSH and GPG keys -> New SSH key\n")
    print(pub_key_file.read_text())


# =============================================================================
# GitHub Token Management
# =============================================================================


def set_github_token(token: str, config: Config, gh: GitHubManager) -> None:
    """Validate and save a GitHub Personal Access Token."""
    logger = get_logger()

    if not token:
        eprint("Enter your GitHub Personal Access Token:")
        eprint("(Create one at https://github.com/settings/tokens/new with 'codespace' scope)")
        token = prompt("> ").strip()

    if not token:
        raise ValueError("No token provided")

    if not (
        token.startswith("ghp_") or token.startswith("ghs_") or token.startswith("github_pat_")
    ):
        logger.warning("Token doesn't match expected format (ghp_*, ghs_*, or github_pat_*)")
        answer = prompt("Continue anyway? [y/N] ").strip().lower()
        if answer != "y":
            raise ValueError("Aborted")

    logger.info("Validating token...")
    os.environ["GH_TOKEN"] = token
    gh.runner.redacted_values = tuple([*gh.runner.redacted_values, token])

    result = gh.runner.run(["gh", "auth", "status"], capture_output=True, env={"GH_TOKEN": token})
    if result.returncode != 0:
        raise GitHubAuthError("Token validation failed. Check scopes: codespace, repo")

    gh.save_token(token)
    logger.info("Token validated and saved successfully")


# =============================================================================
# Split Tunneling
# =============================================================================


def setup_split_tunnel(config: Config) -> None:
    """Interactively set up split tunneling for specific targets."""
    logger = get_logger()
    target_file = config.config_dir / "targets.txt"

    eprint("Split tunneling routes specific targets through the proxy.")
    eprint("Enter target domains/IPs (one per line, empty line to finish):\n")

    targets = []
    while True:
        target = prompt("> ").strip()
        if not target:
            break
        targets.append(target)

    if not targets:
        logger.warning("No targets specified")
        return

    target_file.write_text("\n".join(targets) + "\n")
    logger.info(f"Targets saved to {target_file}")

    print(f"""
For iptables-based routing, you need to:

1. Install redsocks: sudo apt install redsocks
2. Configure redsocks to use the SOCKS proxy
3. Use iptables to redirect specific traffic to redsocks

Example redsocks config:
  base {{ log_debug = off; log_info = off; daemon = on; redirector = iptables; }}
  redsocks {{ local_ip = 127.0.0.1; local_port = 12345;
             ip = 127.0.0.1; port = {config.socks_port}; type = socks5; }}

Example iptables rule (for a specific destination):
  iptables -t nat -A OUTPUT -p tcp -d <TARGET_IP> -j REDIRECT --to-ports 12345
""")


# =============================================================================
# Helper
# =============================================================================


def _get_codespace(config: Config, gh: GitHubManager) -> str:
    """Get current Codespace name, selecting if needed."""
    if config.codespace_name:
        return config.codespace_name

    selector = CodespaceSelector(gh, config)
    name = selector.select()
    config.set("codespace_name", name)
    return name


def _ensure_codespaces(config: Config, gh: GitHubManager, count: int) -> list:
    """Ensure at least `count` codespaces exist, creating if needed."""
    logger = get_logger()
    existing = gh.list_codespaces()
    names = [cs["name"] for cs in existing[:count]]

    for name in names:
        logger.info(f"Using existing codespace: {name}")

    locations = config.locations
    while len(names) < count:
        idx = len(names)
        location = locations[idx] if idx < len(locations) else (locations[0] if locations else "")
        logger.info(
            f"Creating codespace {idx+1}/{count}" + (f" in {location}" if location else "") + "..."
        )
        selector = CodespaceSelector(gh, config)
        name = selector._create_and_wait(CodespaceSelector.BLANK_REPO, location=location)
        names.append(name)

    return names


def cmd_start(args, config: Config, gh: GitHubManager) -> int:
    """Start SOCKS5 proxy tunnel."""
    logger = get_logger()
    check_dependencies(["gh", "ssh", "curl"])

    if getattr(config, "_dry_run", False):
        names = config.codespace_names or ([config.codespace_name] if config.codespace_name else [])
        if not names:
            print("[dry-run] No codespace configured. Would prompt for selection.")
            return 0
        for i, name in enumerate(names):
            port = config.socks_port + i
            print(f"[dry-run] Would start tunnel {name} on port {port}")
        print("[dry-run] Would generate proxychains config and save settings")
        return 0

    gh.check_auth()

    num_proxies = min(config.get("num_proxies", 1), 2)
    selector = CodespaceSelector(gh, config)

    if num_proxies > 1:
        names = _ensure_codespaces(config, gh, num_proxies)
        codespace = names[0]
        config.set("codespace_name", codespace)
        config.set("codespace_names", names)
        logger.info(f"Using {len(names)} codespace(s)")
        for i, name in enumerate(names):
            port = config.socks_port + i
            logger.info(f"  {name}  →  socks5://127.0.0.1:{port}")
    else:
        tracked = list(config.codespace_names)

        if not tracked:
            # First start: select or create a codespace
            codespace = _get_codespace(config, gh)
            tracked = [codespace]
            config.set("codespace_name", codespace)
            config.set("codespace_names", tracked)
        else:
            # Check if all tracked codespaces already have running tunnels
            all_running = all(
                SSHTunnel(
                    config, n, port=config.socks_port + i, pid_suffix=("" if i == 0 else str(i + 1))
                ).is_running()
                for i, n in enumerate(tracked)
            )
            if all_running:
                # All running: add another codespace and tunnel
                logger.info("All managed Codespaces already have tunnels. Adding a new one...")
                new_name = selector._create_interactively()
                tracked.append(new_name)
                config.set("codespace_names", tracked)
            config.set("codespace_name", tracked[0])

    # Start tunnels for any tracked codespace that isn't already running
    for i, name in enumerate(config.codespace_names):
        suffix = "" if i == 0 else str(i + 1)
        port = config.socks_port + i
        t = SSHTunnel(config, name, port=port, pid_suffix=suffix)
        if not t.is_running():
            if getattr(config, "_dry_run", False):
                print(f"[dry-run] Would start tunnel {name} on port {port}")
                continue
            selector.ensure_running(name)
            t.start(start_timeout=30 if i == 0 else 90)

    if getattr(config, "_dry_run", False):
        print("[dry-run] Would generate proxychains config and save settings")
        return 0

    ProxychainsConfig.generate(config)
    print_usage_examples(config)

    config.save()
    return 0


def cmd_stop(args, config: Config, gh: GitHubManager) -> int:
    """Stop proxy tunnel."""
    if getattr(config, "_dry_run", False):
        print(f"[dry-run] Would stop tunnel for {config.codespace_name or 'active codespace'}")
        for i in range(1, len(config.codespace_names)):
            print(f"[dry-run] Would stop tunnel on port {config.socks_port + i}")
        print("[dry-run] Would stop HTTP proxy")
        return 0

    from .services import stop_all_tunnels

    stop_all_tunnels(config)
    return 0


def cmd_restart(args, config: Config, gh: GitHubManager) -> int:
    """Restart proxy."""
    cmd_stop(args, config, gh)
    time.sleep(2)
    return cmd_start(args, config, gh)


def cmd_status(args, config: Config, gh: GitHubManager) -> int:
    """Show proxy status. Pass --watch or -w for auto-refresh."""
    if args and ("--watch" in args or "-w" in args):
        from .display import watch_status

        watch_status(config, gh)
        return 0
    show_status(config, gh)
    return 0


def cmd_list(args, config: Config, gh: GitHubManager) -> int:
    """List Codespaces."""
    check_dependencies(["gh"])
    gh.check_auth()

    get_logger().info("Fetching available Codespaces...")
    print()

    codespaces = gh.list_codespaces()
    if not codespaces:
        print("No Codespaces found.")
        return 0

    header = f"{'NAME':<40} {'STATE':<15} {'REPOSITORY':<35} {'CREATED'}"
    print(header)
    print("-" * len(header))
    for cs in codespaces:
        name = cs.get("name", "")[:38]
        state = cs.get("state", "")[:13]
        repo = cs.get("repository", "")[:33]
        created = cs.get("createdAt", "")[:10]
        print(f"{name:<40} {state:<15} {repo:<35} {created}")
    print()
    return 0


def cmd_create(args, config: Config, gh: GitHubManager) -> int:
    """Create a new Codespace and add it to the tracked list."""
    check_dependencies(["gh"])
    gh.check_auth()

    selector = CodespaceSelector(gh, config)
    name = selector._create_interactively()

    names = list(config.codespace_names)
    if name not in names:
        names.append(name)
    config.set("codespace_names", names)
    config.set("codespace_name", name)
    config.save()
    return 0


def cmd_set(args, config: Config, gh: GitHubManager) -> int:
    """Set the active Codespace by name."""
    logger = get_logger()

    codespace_name = args[0] if args else None
    if not codespace_name:
        logger.error("Usage: cs-proxy set <codespace-name>")
        return 1

    config.set("codespace_name", codespace_name)
    config.save()
    logger.info(f"Codespace set to: {codespace_name}")
    return 0


def cmd_http(args, config: Config, gh: GitHubManager) -> int:
    """Start HTTP proxy."""
    http = HTTPProxyManager(config)
    http.start()
    return 0


def cmd_proxychains(args, config: Config, gh: GitHubManager) -> int:
    """Generate proxychains configuration."""
    ProxychainsConfig.generate(config)
    return 0


def cmd_env(args, config: Config, gh: GitHubManager) -> int:
    """Print environment variable exports."""
    print_env_exports(config)
    return 0


def cmd_burp(args, config: Config, gh: GitHubManager) -> int:
    """Print Burp Suite configuration."""
    print_burp_config(config)
    return 0


def cmd_keygen(args, config: Config, gh: GitHubManager) -> int:
    """Generate SSH key for Codespace access."""
    generate_ssh_key(config)
    return 0


def cmd_config(args, config: Config, gh: GitHubManager) -> int:
    """Open config file in editor."""
    editor = os.environ.get("EDITOR", "nano")
    os.execvp(editor, [editor, str(config.config_file)])
    return 0


def cmd_logs(args, config: Config, gh: GitHubManager) -> int:
    """Show proxy logs."""
    lines = int(args[0]) if args else 50
    show_logs(config, lines)
    return 0


def cmd_split(args, config: Config, gh: GitHubManager) -> int:
    """Set up split tunneling."""
    setup_split_tunnel(config)
    return 0


def _pick_codespace(args, config: Config, gh: GitHubManager) -> str:
    """
    Resolve which codespace to target from args or interactive menu.

    Resolution order:
      1. args[0] is a digit  → index into codespace_names
      2. args[0] is a string → use directly as codespace name
      3. Multiple managed codespaces → show numbered menu
      4. Fallback                    → _get_codespace (active / selector)
    """
    names: list[str] = config.codespace_names

    if args:
        arg: str = args[0]
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(names):
                return names[idx]
            raise ValueError(
                f"No codespace at index {arg}. " f"Tracked: {len(names)} ({', '.join(names)})"
            )
        return arg  # treat as explicit name

    if len(names) > 1:
        eprint("\nSelect Codespace:")
        for i, name in enumerate(names, 1):
            idx = names.index(name)
            role = f" [:{config.socks_port + idx}]"
            eprint(f"  {i}) {name}{role}")
        choice = prompt("> ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                return names[idx]
        print("Invalid selection, using active codespace")

    return _get_codespace(config, gh)


def cmd_ssh(args, config: Config, gh: GitHubManager) -> int:
    """Open interactive SSH session in Codespace."""
    check_dependencies(["gh", "ssh"])
    gh.check_auth()

    codespace = _pick_codespace(args, config, gh)
    selector = CodespaceSelector(gh, config)
    selector.ensure_running(codespace)

    get_logger().info(f"Connecting to {codespace}...")
    os.execvp("gh", ["gh", "codespace", "ssh", "--codespace", codespace])
    return 0


def cmd_run(args, config: Config, gh: GitHubManager) -> int:
    """Run a command in the Codespace."""
    check_dependencies(["gh", "ssh"])
    gh.check_auth()

    if not args:
        get_logger().error("Usage: cs-proxy run <command>")
        return 1

    codespace = _get_codespace(config, gh)
    selector = CodespaceSelector(gh, config)
    selector.ensure_running(codespace)

    result = gh.runner.run(
        ["gh", "codespace", "ssh", "--codespace", codespace, "--"] + args,
        capture_output=False,
        timeout=None,
    )
    return result.returncode


def cmd_name(args, config: Config, gh: GitHubManager) -> int:
    """Print current Codespace name."""
    check_dependencies(["gh"])
    gh.check_auth()

    codespace = _get_codespace(config, gh)
    print(codespace)
    return 0


def cmd_teardown(args, config: Config, gh: GitHubManager) -> int:
    """Stop proxy and all managed Codespaces (saves compute, keeps storage)."""
    logger = get_logger()
    check_dependencies(["gh"])
    gh.check_auth()

    # Clean up every tunnel in state, not just config-tracked ones
    state = State(config.config_dir)
    tunnels = state.get_tunnels(kind="ssh")
    for t in tunnels:
        port = t.get("port", config.socks_port)
        cs_name = t.get("codespace_name", "")
        tunnel = SSHTunnel(config, cs_name, port=port)
        tunnel.cleanup()
        logger.info(f"Stopped tunnel :{port}")

    # Also clean up any orphaned artifacts in workers/ directory
    workers_dir = config.config_dir / "workers"
    if workers_dir.exists():
        for f in workers_dir.iterdir():
            f.unlink(missing_ok=True)

    all_names = config.codespace_names or ([config.codespace_name] if config.codespace_name else [])
    if all_names:
        for name in all_names:
            logger.info(f"Stopping Codespace: {name}")
            gh.run_gh_command(["codespace", "stop", "--codespace", name], check=False)
        logger.info(f"Stopped {len(all_names)} codespace(s) (still exist, no compute billing)")
    else:
        logger.warning("No Codespace configured. Use: gh codespace stop -c <name>")

    return 0


def cmd_down(args, config: Config, gh: GitHubManager) -> int:
    """Stop proxy and permanently delete all managed Codespaces."""
    logger = get_logger()
    check_dependencies(["gh"])
    gh.check_auth()

    # Step 1: aggressive cleanup of every tunnel in state
    state = State(config.config_dir)
    tunnels = state.get_tunnels(kind="ssh")
    for t in tunnels:
        port = t.get("port", config.socks_port)
        cs_name = t.get("codespace_name", "")
        tunnel = SSHTunnel(config, cs_name, port=port)
        tunnel.cleanup()
        logger.info(f"Cleaned up tunnel :{port}")

    # Also clean up any orphaned artifacts in workers/ directory
    workers_dir = config.config_dir / "workers"
    if workers_dir.exists():
        for f in workers_dir.iterdir():
            f.unlink(missing_ok=True)

    all_names = list(config.codespace_names) or (
        [config.codespace_name] if config.codespace_name else []
    )
    if not all_names:
        logger.warning("No Codespace configured.")
        return 0

    # Step 2: stop codespaces first (clean shutdown before delete)
    for name in all_names:
        logger.info(f"Stopping Codespace: {name}")
        gh.run_gh_command(["codespace", "stop", "--codespace", name], check=False)

    # Step 3: confirm deletion
    if len(all_names) > 1:
        eprint(f"\nThis will PERMANENTLY delete {len(all_names)} managed codespaces:")
        for name in all_names:
            eprint(f"  - {name}")
    else:
        eprint(f"\nThis will PERMANENTLY delete: {all_names[0]}")
    confirm = prompt("Are you sure? [y/N] ").strip().lower()
    if confirm != "y":
        logger.info("Cancelled — codespaces were stopped but not deleted.")
        return 0

    # Step 4: delete
    for name in all_names:
        logger.info(f"Deleting Codespace: {name}")
        gh.delete_codespace(name, force=True)

    # Step 5: wipe local state and config tracking
    state.clear_all()
    config.set("codespace_name", "")
    config.set("codespace_names", [])
    config.save()
    logger.info(f"Deleted {len(all_names)} codespace(s)")
    return 0


def cmd_delete(args, config: Config, gh: GitHubManager) -> int:
    """Delete Codespace(s) permanently."""
    logger = get_logger()
    check_dependencies(["gh"])
    gh.check_auth()

    # List all codespaces to let user choose
    codespaces = gh.list_codespaces()
    if not codespaces:
        logger.info("No codespaces found")
        return 0

    names = [cs["name"] for cs in codespaces]

    if len(names) > 1:
        eprint(f"\nYou have {len(names)} codespaces:")
        for i, name in enumerate(names, 1):
            eprint(f"  {i}) {name}")
        eprint()
        eprint("Options:")
        eprint("  a) Delete ALL")
        for i, name in enumerate(names, 1):
            eprint(f"  {i}) Delete only {name}")
        eprint("  n) Cancel")
        eprint()
        choice = prompt("Choice: ").strip().lower()

        if choice == "a":
            to_delete = names
        elif choice.isdigit() and 1 <= int(choice) <= len(names):
            to_delete = [names[int(choice) - 1]]
        else:
            logger.info("Cancelled")
            return 0
    else:
        to_delete = names
        eprint(f"\nThis will PERMANENTLY delete: {to_delete[0]}")
        confirm = prompt("Are you sure? [y/N] ").strip().lower()
        if confirm != "y":
            logger.info("Cancelled")
            return 0

    # Stop tunnel if active codespace is being deleted
    for name in to_delete:
        SSHTunnel(config, name).stop()

    # Delete codespaces
    for name in to_delete:
        gh.delete_codespace(name, force=True)

    remaining = [n for n in config.codespace_names if n not in to_delete]
    config.set("codespace_name", remaining[0] if remaining else "")
    config.set("codespace_names", remaining)
    config.save()
    return 0


def cmd_token(args, config: Config, gh: GitHubManager) -> int:
    """Set GitHub token."""
    config.ensure_dirs()
    token = args[0] if args else ""
    set_github_token(token, config, gh)
    return 0


def cmd_aliases(args, config: Config, gh: GitHubManager) -> int:
    """Write shell aliases to ~/.bashrc and/or ~/.zshrc."""
    logger = get_logger()
    home = Path.home()

    proxychains_conf = "${CS_PROXY_CONFIG_DIR:-$HOME/.config/cs-proxy}/proxychains.conf"
    alias_block = f"""\n# cs-proxy aliases
alias proxy-start='cs-proxy start'
alias proxy-stop='cs-proxy stop'
alias proxy-status='cs-proxy status'
alias pcs='proxychains4 -f {proxychains_conf}'
alias cs-wg='sudo env "PATH=$PATH" cs-wg'
"""

    rc_files = [f for f in [home / ".bashrc", home / ".zshrc"] if f.exists()]
    if not rc_files:
        rc_files = [home / ".bashrc"]

    wrote = []
    for rc in rc_files:
        existing = rc.read_text() if rc.exists() else ""
        if "cs-proxy aliases" in existing:
            logger.info(f"Aliases already present in {rc}")
            continue
        with rc.open("a") as f:
            f.write(alias_block)
        wrote.append(rc)
        logger.info(f"Added aliases to {rc}")

    if wrote:
        print("\nSource your shell to activate:")
        for rc in wrote:
            print(f"  source {rc}")
    return 0


def cmd_pac(args, config: Config, gh: GitHubManager) -> int:
    """Generate Proxy Auto-Config (PAC) file contents."""
    pac = f"""function FindProxyForURL(url, host) {{
    if (isPlainHostName(host) ||
        shExpMatch(host, "*.local") ||
        isInNet(host, "127.0.0.0", "255.0.0.0") ||
        isInNet(host, "10.0.0.0", "255.0.0.0") ||
        isInNet(host, "172.16.0.0", "255.240.0.0") ||
        isInNet(host, "192.168.0.0", "255.255.0.0")) {{
        return "DIRECT";
    }}
    return "SOCKS5 127.0.0.1:{config.socks_port}; DIRECT";
}}"""
    print(pac)
    return 0


def cmd_completion(args, config: Config, gh: GitHubManager) -> int:
    """Generate shell completion script."""
    shell = args[0] if args else "bash"
    from .completion import generate_completion

    script = generate_completion(shell)
    if "Unsupported shell" in script:
        get_logger().error(f"Unsupported shell: {shell}. Supported: bash, zsh")
        return 1
    print(script)
    return 0


def cmd_account(args, config: Config, gh: GitHubManager) -> int:
    """Manage named GitHub accounts for account-aware workflows."""
    import argparse

    parser = argparse.ArgumentParser(prog="cs-proxy account")
    sub = parser.add_subparsers(dest="action", required=True)

    p_add = sub.add_parser("add", help="Add or update an account")
    p_add.add_argument("name")
    p_add.add_argument("--token-env", required=True, help="Environment variable that holds the PAT")
    p_add.add_argument("--gh-host", default="github.com")

    p_list = sub.add_parser("list", help="List configured accounts")
    p_list.set_defaults(_list=True)

    p_rm = sub.add_parser("remove", aliases=["rm"], help="Remove an account")
    p_rm.add_argument("name")

    parsed = parser.parse_args(args)
    accounts = config.get("accounts", {})
    if not isinstance(accounts, dict):
        accounts = {}

    if parsed.action == "add":
        if parsed.token_env.startswith("ghp_") or parsed.token_env.startswith("github_pat_"):
            raise ValueError("Do not pass raw tokens. Use --token-env NAME instead.")
        accounts[parsed.name] = {
            "token_env": parsed.token_env,
            "gh_host": parsed.gh_host,
        }
        config.set("accounts", accounts)
        config.save()
        get_logger().info(f"Saved account '{parsed.name}' using ${parsed.token_env}")
        return 0

    if parsed.action == "list":
        if not accounts:
            print("No named accounts configured.")
            return 0
        for name, account in accounts.items():
            token_env = account.get("token_env", "")
            gh_host = account.get("gh_host", "github.com")
            print(f"{name:<20} token_env={token_env:<20} host={gh_host}")
        return 0

    if parsed.action in ("remove", "rm"):
        accounts.pop(parsed.name, None)
        config.set("accounts", accounts)
        config.save()
        get_logger().info(f"Removed account '{parsed.name}'")
        return 0

    return 1


def cmd_check(args, config: Config, gh: GitHubManager) -> int:
    """Run diagnostics and report configuration/dependency health."""
    from .services import run_diagnostics

    checks = run_diagnostics(config, gh)
    issues = print_diagnostics(checks)
    return 1 if issues else 0


def cmd_doctor(args, config: Config, gh: GitHubManager) -> int:
    """Run diagnostics, optionally repairing local state/config artifacts."""
    import argparse

    parser = argparse.ArgumentParser(prog="cs-proxy doctor")
    parser.add_argument("--fix", action="store_true", help="Repair safe local issues")
    parsed = parser.parse_args(args)

    logger = get_logger()
    if parsed.fix:
        config.ensure_dirs()
        state = State(config.config_dir)
        crashed = state.reconcile()
        if crashed:
            logger.info(f"Reconciled {len(crashed)} crashed tunnel(s)")
        ProxychainsConfig.generate(config)
        if not config.config_file.exists():
            config.save()
        logger.info("Safe local repairs complete")

    return cmd_check([], config, gh)


def cmd_pool(args, config: Config, gh: GitHubManager) -> int:
    """Inspect and manage the local tunnel pool."""
    import argparse

    parser = argparse.ArgumentParser(prog="cs-proxy pool")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="List managed SSH tunnels")
    sub.add_parser("rotate", help="Print a healthy tunnel port")
    p_drain = sub.add_parser("drain", help="Mark a tunnel as draining")
    p_drain.add_argument("port", type=int)

    parsed = parser.parse_args(args)
    state = State(config.config_dir)

    if parsed.action == "list":
        tunnels = state.get_tunnels(kind="ssh")
        if not tunnels:
            print("No SSH tunnels in the pool.")
            return 0
        for t in tunnels:
            print(
                f":{t.get('port')} {t.get('status', 'unknown'):<10} "
                f"{t.get('codespace_name', '')}"
            )
        return 0

    from .services import drain_tunnel, rotate_pool

    if parsed.action == "rotate":
        try:
            print(rotate_pool(config))
            return 0
        except RuntimeError as e:
            get_logger().error(str(e))
            return 1

    if parsed.action == "drain":
        try:
            drain_tunnel(config, parsed.port)
            get_logger().info(f"Marked tunnel :{parsed.port} as draining")
            return 0
        except ValueError as e:
            get_logger().error(str(e))
            return 1

    return 1


def cmd_help(args, config: Config, gh: GitHubManager) -> int:
    """Show help."""
    show_help()
    return 0


def cmd_tui(args, config: Config, gh: GitHubManager) -> int:
    """Launch the interactive terminal UI (requires the 'tui' extra)."""
    from .tui import main_tui

    return main_tui(args)


# =============================================================================
# Command Dispatch Table
# =============================================================================


COMMANDS = {
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
    "list": cmd_list,
    "create": cmd_create,
    "set": cmd_set,
    "http": cmd_http,
    "proxychains": cmd_proxychains,
    "env": cmd_env,
    "burp": cmd_burp,
    "keygen": cmd_keygen,
    "config": cmd_config,
    "logs": cmd_logs,
    "split": cmd_split,
    "ssh": cmd_ssh,
    "run": cmd_run,
    "name": cmd_name,
    "teardown": cmd_teardown,
    "down": cmd_down,
    "delete": cmd_delete,
    "rm": cmd_delete,  # Alias
    "token": cmd_token,
    "aliases": cmd_aliases,
    "pac": cmd_pac,
    "completion": cmd_completion,
    "account": cmd_account,
    "check": cmd_check,
    "doctor": cmd_doctor,
    "pool": cmd_pool,
    "chain": cmd_chain,
    "tui": cmd_tui,
    "help": cmd_help,
}
