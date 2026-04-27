#!/usr/bin/env python3
"""Tests for operator-focused doctor and pool commands."""


def test_pool_rotate_prints_healthy_port(tmp_path, capsys):
    from csproxy.github import GitHubManager
    from csproxy.proxy import cmd_pool
    from csproxy.state import State
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    State(tmp_path).add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="cs-a",
        port=1080,
        pid=123,
        status="healthy",
    )

    result = cmd_pool(["rotate"], config, GitHubManager(config_dir=tmp_path))

    assert result == 0
    assert capsys.readouterr().out.strip() == "1080"


def test_pool_drain_marks_tunnel(tmp_path):
    from csproxy.github import GitHubManager
    from csproxy.proxy import cmd_pool
    from csproxy.state import State
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    state = State(tmp_path)
    state.add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="cs-a",
        port=1080,
        pid=123,
        status="healthy",
    )

    result = cmd_pool(["drain", "1080"], config, GitHubManager(config_dir=tmp_path))

    assert result == 0
    assert state.get_tunnel_by_port(1080)["status"] == "draining"


def test_doctor_fix_creates_config_artifacts(tmp_path):
    from unittest.mock import patch
    from csproxy.github import GitHubManager
    from csproxy.proxy import cmd_doctor
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    gh = GitHubManager(config_dir=tmp_path)

    with patch("csproxy.proxy.cmd_check", return_value=0) as check:
        result = cmd_doctor(["--fix"], config, gh)

    assert result == 0
    assert config.config_dir.exists()
    assert (config.config_dir / "proxychains.conf").exists()
    check.assert_called_once()
