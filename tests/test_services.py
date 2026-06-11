"""Tests for the presentation-free service layer (csproxy.services)."""

from unittest.mock import patch

import pytest

from csproxy.github import GitHubManager
from csproxy.services import (
    Check,
    _pid_suffix_for_port,
    drain_tunnel,
    get_logs,
    list_chains,
    list_codespaces_safe,
    list_pool,
    rotate_pool,
    run_diagnostics,
    stop_all_tunnels,
    stop_tunnel,
)
from csproxy.state import State
from csproxy.utils import Config


def _config():
    config = Config()
    config.ensure_dirs()
    return config


def test_run_diagnostics_returns_checks():
    config = _config()
    gh = GitHubManager(config_dir=config.config_dir)
    checks = run_diagnostics(config, gh)

    assert checks, "diagnostics should never be empty"
    assert all(isinstance(c, Check) for c in checks)
    # Every check is either PASS or FAIL and the ok flag agrees with status.
    for c in checks:
        assert c.status in ("PASS", "FAIL")
        assert c.ok == (c.status == "PASS")
    # The gh dependency check is always present.
    assert any("gh CLI" in c.message for c in checks)


def test_list_pool_empty_for_fresh_config():
    config = _config()
    assert list_pool(config, reconcile=False) == []


def test_list_pool_returns_added_tunnels():
    config = _config()
    state = State(config.config_dir)
    state.add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="demo-cs",
        port=1080,
        pid=999999,
        status="healthy",
        failures=0,
    )
    pool = list_pool(config, reconcile=False)
    assert len(pool) == 1
    assert pool[0]["port"] == 1080
    assert pool[0]["codespace_name"] == "demo-cs"


def test_list_pool_reconcile_marks_dead_pid_crashed():
    config = _config()
    state = State(config.config_dir)
    state.add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="demo",
        port=1080,
        pid=999999,
        status="healthy",
        failures=0,
    )
    # PID 999999 is not alive -> reconcile should mark it crashed but keep it.
    pool = list_pool(config, reconcile=True)
    assert len(pool) == 1
    assert pool[0]["status"] == "crashed"


def test_list_codespaces_safe_degrades_without_gh():
    config = _config()
    gh = GitHubManager(config_dir=config.config_dir)
    # No gh binary / auth in the test environment -> [] instead of raising.
    assert list_codespaces_safe(gh) == []


def test_get_logs_empty_when_no_logfile():
    config = _config()
    assert get_logs(config) == []


def test_get_logs_returns_tail():
    config = _config()
    log_file = config.config_dir / "proxy.log"
    log_file.write_text("\n".join(f"line {i}" for i in range(100)))
    tail = get_logs(config, lines=10)
    assert len(tail) == 10
    assert tail[-1] == "line 99"


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _add_tunnel(config, port=1080, status="healthy"):
    State(config.config_dir).add_tunnel(
        id=f"ssh-{port}",
        kind="ssh",
        codespace_name="demo",
        port=port,
        pid=999999,
        status=status,
        failures=0,
    )


def test_pid_suffix_for_port():
    config = _config()  # default socks_port is 1080
    base = config.socks_port
    assert _pid_suffix_for_port(config, base) == ""
    assert _pid_suffix_for_port(config, base + 1) == "2"
    assert _pid_suffix_for_port(config, base + 2) == "3"


def test_drain_tunnel_marks_draining():
    config = _config()
    _add_tunnel(config, port=1080)
    drain_tunnel(config, 1080)
    assert State(config.config_dir).get_tunnel_by_port(1080)["status"] == "draining"


def test_drain_tunnel_missing_raises():
    config = _config()
    with pytest.raises(ValueError):
        drain_tunnel(config, 9999)


def test_rotate_pool_returns_healthy_port():
    config = _config()
    _add_tunnel(config, port=1080, status="healthy")
    assert rotate_pool(config) == 1080


def test_rotate_pool_no_healthy_raises():
    config = _config()
    _add_tunnel(config, port=1080, status="crashed")
    with pytest.raises(RuntimeError):
        rotate_pool(config)


def test_stop_tunnel_invokes_sshtunnel_stop():
    config = _config()
    with patch("csproxy.tunnel.SSHTunnel.stop") as mock_stop:
        stop_tunnel(config, config.socks_port)
    mock_stop.assert_called_once()


def test_stop_all_tunnels_stops_each_and_http():
    config = _config()
    config.set("codespace_names", ["a", "b"])
    with (
        patch("csproxy.tunnel.SSHTunnel.stop") as mock_stop,
        patch("csproxy.tunnel.HTTPProxyManager.stop") as mock_http,
    ):
        stop_all_tunnels(config)
    # primary tunnel + one extra pool tunnel (index 1)
    assert mock_stop.call_count == 2
    mock_http.assert_called_once()


# ---------------------------------------------------------------------------
# Chains
# ---------------------------------------------------------------------------


def test_list_chains_includes_account_per_hop():
    config = _config()
    config.set(
        "chains",
        {
            "eu-us": {
                "name": "eu-us",
                "hops": [
                    {"location": "WestEurope", "account": "work", "codespace_name": ""},
                    {"location": "EastUs", "codespace_name": ""},
                ],
            }
        },
    )
    rows = list_chains(config)
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "eu-us"
    assert row["status"] == "defined"
    assert row["running"] is False
    assert row["hops"][0] == {"location": "WestEurope", "account": "work"}
    assert row["hops"][1] == {"location": "EastUs", "account": ""}


def test_list_chains_overlays_running_status():
    config = _config()
    config.set("chains", {"eu-us": {"name": "eu-us", "hops": []}})
    State(config.config_dir).add_tunnel(
        id="chain-eu-us",
        kind="chain",
        name="eu-us",
        status="healthy",
        local_port=1090,
        hops=[],
    )
    row = next(r for r in list_chains(config) if r["name"] == "eu-us")
    assert row["running"] is True
    assert row["status"] == "healthy"
    assert row["local_port"] == 1090


def test_start_chain_invokes_command(monkeypatch):
    config = _config()
    gh = GitHubManager(config_dir=config.config_dir)
    calls = {}

    def fake_start(parsed, cfg, ghm):
        calls["name"] = parsed.name
        calls["port"] = parsed.port
        return 0

    monkeypatch.setattr("csproxy.chains._cmd_chain_start", fake_start)
    from csproxy.services import start_chain

    start_chain(config, gh, "eu-us", port=1091)
    assert calls == {"name": "eu-us", "port": 1091}


def test_start_chain_raises_on_failure(monkeypatch):
    config = _config()
    gh = GitHubManager(config_dir=config.config_dir)
    monkeypatch.setattr("csproxy.chains._cmd_chain_start", lambda parsed, cfg, ghm: 1)
    from csproxy.services import start_chain

    with pytest.raises(RuntimeError):
        start_chain(config, gh, "eu-us")


def test_delete_chain_removes_definition():
    config = _config()
    config.set("chains", {"eu-us": {"name": "eu-us", "hops": []}})
    from csproxy.services import delete_chain

    delete_chain(config, "eu-us")
    assert "eu-us" not in config.get("chains", {})


def test_delete_chain_missing_raises():
    config = _config()
    from csproxy.services import delete_chain

    with pytest.raises(ValueError):
        delete_chain(config, "nope")
