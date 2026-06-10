#!/usr/bin/env python3
"""
Phase 3 hardening tests — circuit breaker, jitter, dry-run, check, deprecation.

Covers production-readiness fixes:
- Circuit breaker integration in health_check()
- Worker reconnect jitter
- Worker crash stderr surfacing
- Config deprecation warnings
- --dry-run flag for start/stop
- cs-proxy check (diagnostics) command
"""

from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# Circuit breaker
# =============================================================================


def test_health_check_resets_failures_on_success(tmp_path):
    from csproxy.state import State
    from csproxy.tunnel import SSHTunnel
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    state = State(tmp_path)
    state.add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="test-cs",
        port=1080,
        pid=12345,
        status="healthy",
        created=0,
        failures=2,
        last_failure=0,
    )

    tunnel = SSHTunnel(config, "test-cs", port=1080)
    # Mock successful curl
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("subprocess.run", return_value=mock_result):
        tunnel.health_check()

    t = state.get_tunnel_by_port(1080)
    assert t["failures"] == 0
    assert t["last_failure"] == 0


def test_health_check_records_failure_on_bad_check(tmp_path):
    from csproxy.state import State
    from csproxy.tunnel import SSHTunnel
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    state = State(tmp_path)
    state.add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="test-cs",
        port=1080,
        pid=12345,
        status="healthy",
        created=0,
        failures=0,
        last_failure=0,
    )

    tunnel = SSHTunnel(config, "test-cs", port=1080)
    mock_result = MagicMock()
    mock_result.returncode = 1

    with patch("subprocess.run", return_value=mock_result):
        result = tunnel.health_check()

    assert result is False
    t = state.get_tunnel_by_port(1080)
    assert t["failures"] == 1


def test_health_check_uses_configured_url(tmp_path):
    from csproxy.state import State
    from csproxy.tunnel import SSHTunnel
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    config.set("health_check_url", "https://example.test/health")
    State(tmp_path).add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="test-cs",
        port=1080,
        pid=12345,
        status="healthy",
        created=0,
        failures=0,
        last_failure=0,
    )
    tunnel = SSHTunnel(config, "test-cs", port=1080)
    mock_result = MagicMock(returncode=0)

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        tunnel.health_check()

    assert "https://example.test/health" in mock_run.call_args.args[0]


def test_health_check_trips_circuit_breaker(tmp_path):
    from csproxy.state import State
    from csproxy.tunnel import SSHTunnel
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    state = State(tmp_path)
    state.add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="test-cs",
        port=1080,
        pid=12345,
        status="healthy",
        created=0,
        failures=0,
        last_failure=0,
    )

    tunnel = SSHTunnel(config, "test-cs", port=1080)
    mock_result = MagicMock()
    mock_result.returncode = 1

    with patch("subprocess.run", return_value=mock_result):
        # Default max_failures=3, so 3 failures should trip
        tunnel.health_check()
        tunnel.health_check()
        tunnel.health_check()

    t = state.get_tunnel_by_port(1080)
    assert t["status"] == "dead"
    assert t["failures"] == 3


# =============================================================================
# Config deprecation warnings
# =============================================================================


def test_config_load_warns_on_deprecated_key(tmp_path):
    import yaml
    from unittest.mock import patch
    from csproxy.utils.config import Config

    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({"chain": "some-value", "socks_port": 1080}))

    mock_logger = MagicMock()
    with patch("csproxy.utils.config.get_logger", return_value=mock_logger):
        Config(config_dir=tmp_path, config_file=config_file)

    warning_calls = [c for c in mock_logger.warning.call_args_list if "chain" in str(c)]
    assert len(warning_calls) >= 1
    assert "Deprecated config key 'chain'" in str(warning_calls[0])


def test_config_rejects_non_http_health_url(tmp_path):
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)

    config.set("health_check_url", "file:///tmp/nope")

    assert config.health_check_url == "https://ifconfig.me"


# =============================================================================
# --dry-run flag
# =============================================================================


def test_cmd_stop_dry_run_does_not_call_stop(tmp_path):
    from csproxy.proxy import cmd_stop
    from csproxy.utils.config import Config
    from csproxy.github import GitHubManager
    from unittest.mock import patch

    config = Config(config_dir=tmp_path)
    config._dry_run = True
    gh = GitHubManager()

    with patch("csproxy.tunnel.SSHTunnel.stop") as mock_stop:
        result = cmd_stop([], config, gh)

    assert result == 0
    mock_stop.assert_not_called()


def test_cmd_start_dry_run_does_not_start_tunnels(tmp_path):
    from csproxy.proxy import cmd_start
    from csproxy.utils.config import Config
    from csproxy.github import GitHubManager
    from unittest.mock import patch

    config = Config(config_dir=tmp_path)
    config.set("codespace_names", ["test-cs"])
    config._dry_run = True
    gh = GitHubManager()

    with patch("csproxy.tunnel.SSHTunnel.is_running", return_value=False):
        with patch("csproxy.tunnel.SSHTunnel.start") as mock_start:
            with patch("csproxy.codespace.CodespaceSelector.ensure_running"):
                result = cmd_start([], config, gh)

    assert result == 0
    mock_start.assert_not_called()


# =============================================================================
# check command
# =============================================================================


def test_check_command_exists():
    from csproxy.proxy import COMMANDS

    assert "check" in COMMANDS
    assert callable(COMMANDS["check"])


def test_check_command_runs_without_crash(tmp_path):
    from csproxy.proxy import cmd_check
    from csproxy.utils.config import Config
    from csproxy.github import GitHubManager

    config = Config(config_dir=tmp_path)
    gh = GitHubManager()
    result = cmd_check([], config, gh)
    # Should return non-zero because keys/dependencies are missing,
    # but must not raise.
    assert isinstance(result, int)


# =============================================================================
# Worker jitter (indirect test via code inspection)
# =============================================================================


def test_worker_imports_random():
    """Ensure _worker.py imports random for jitter."""
    import csproxy._worker as worker_mod

    assert "random" in dir(worker_mod)


# =============================================================================
# CLI --dry-run parsing
# =============================================================================


def test_cli_parses_dry_run_flag():
    from csproxy.cli import main_proxy
    from unittest.mock import patch

    with patch("csproxy.proxy.COMMANDS", {"help": lambda a, c, g: 0}):
        with patch("csproxy.proxy.show_help"):
            result = main_proxy(["--dry-run", "help"])
    assert result == 0


def test_set_github_token_accepts_fine_grained_pat(tmp_path):
    from csproxy.github import GitHubManager
    from csproxy.proxy import set_github_token
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    gh = GitHubManager(config_dir=tmp_path)
    token = "github_pat_" + "a" * 40

    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        set_github_token(token, config, gh)

    assert (tmp_path / "gh_token").read_text() == token


def test_worker_trims_oversized_log(tmp_path):
    from csproxy._worker import _trim_log_file

    log_file = tmp_path / "proxy.log"
    log_file.write_bytes(b"a" * 100 + b"recent")

    _trim_log_file(log_file, 20)

    data = log_file.read_bytes()
    assert data.startswith(b"[csproxy] log truncated")
    assert data.endswith(b"recent")


def test_worker_status_file_records_status(tmp_path):
    import json
    from csproxy._worker import _write_status

    status_file = tmp_path / "worker.status.json"

    _write_status(status_file, "running", attempt=2)

    data = json.loads(status_file.read_text())
    assert data["status"] == "running"
    assert data["attempt"] == 2
    assert data["pid"] > 0


def test_tunnel_worker_ready_timeout_cleans_spec(tmp_path):
    from csproxy.tunnel import SSHTunnel
    from csproxy.utils.config import Config
    from csproxy.utils.errors import SSHTunnelError

    config = Config(config_dir=tmp_path)
    tunnel = SSHTunnel(config, "test-cs", port=1080)
    tunnel.spec_file.parent.mkdir(parents=True, exist_ok=True)
    tunnel.spec_file.write_text("{}")

    class RunningProcess:
        returncode = None

        def poll(self):
            return None

    with pytest.raises(SSHTunnelError, match="did not signal readiness"):
        tunnel._wait_for_worker_ready(
            RunningProcess(), tunnel.spec_file.with_suffix(".stderr"), timeout=0.01
        )

    assert not tunnel.spec_file.exists()


def test_tunnel_stop_kills_port_holders_and_stop_file(tmp_path):
    from csproxy.tunnel import SSHTunnel
    from csproxy.utils.config import Config

    tunnel = SSHTunnel(Config(config_dir=tmp_path), "test-cs", port=1080)
    tunnel.stop_file.touch()

    with patch.object(tunnel, "_kill_port_holders") as kill_port_holders:
        tunnel.stop()

    kill_port_holders.assert_called_once()
    assert not tunnel.stop_file.exists()


def test_wireguard_setup_script_is_wiped_on_remote_run_failure(tmp_path):
    from csproxy.github import GitHubManager
    from csproxy.utils.config import Config
    from csproxy import wireguard

    config = Config(config_dir=tmp_path)
    gh = GitHubManager(config_dir=tmp_path)

    run_results = [
        MagicMock(returncode=0, stdout="", stderr=b""),  # upload setup script
        MagicMock(returncode=1, stdout="", stderr=b"boom"),  # run setup script
        MagicMock(returncode=0, stdout="", stderr=b""),  # wipe setup script
    ]

    with (
        patch("csproxy.wireguard._check_root"),
        patch("csproxy.wireguard._ensure_dirs"),
        patch("csproxy.wireguard.generate_keys"),
        patch("csproxy.wireguard._select_codespace", return_value="codespace-a"),
        patch("csproxy.wireguard._ensure_codespace_running"),
        patch("csproxy.wireguard._run_gh", return_value=MagicMock(stdout="SSH OK")),
        patch("csproxy.wireguard.generate_local_config"),
        patch("csproxy.wireguard._build_remote_setup_script", return_value="#!/bin/sh\nsecret"),
        patch("csproxy.wireguard._remote_setup_secret_payload", return_value=b"secret\npub\n"),
        patch("subprocess.run", side_effect=run_results) as mock_run,
    ):
        with pytest.raises(RuntimeError, match="Failed to run WireGuard setup"):
            wireguard.start_tunnel(config, gh)

    wipe_cmd = mock_run.call_args_list[2].args[0]
    assert "shred -u /tmp/setup_wg.sh" in wipe_cmd[-1]


def test_wireguard_remote_setup_script_does_not_embed_keys(tmp_path):
    from csproxy.wg_setup import build_remote_setup_script, remote_setup_secret_payload

    wg_dir = tmp_path / "wireguard"
    wg_dir.mkdir()
    (wg_dir / "remote_private.key").write_text("priv-value-123")
    (wg_dir / "local_public.key").write_text("pub-value-456")

    script = build_remote_setup_script(wg_dir)
    payload = remote_setup_secret_payload(wg_dir)

    assert "priv-value-123" not in script
    assert "pub-value-456" not in script
    assert b"priv-value-123\npub-value-456\n" == payload
