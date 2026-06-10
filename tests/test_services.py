"""Tests for the presentation-free service layer (csproxy.services)."""

from csproxy.github import GitHubManager
from csproxy.services import (
    Check,
    get_logs,
    list_codespaces_safe,
    list_pool,
    run_diagnostics,
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
