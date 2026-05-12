#!/usr/bin/env python3
"""Tests for single-account chain command surface and state."""


def test_chain_create_persists_two_hops(tmp_path):
    from csproxy.chains import cmd_chain
    from csproxy.github import GitHubManager
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    gh = GitHubManager(config_dir=tmp_path)

    result = cmd_chain(
        ["create", "eu-us", "--hop", "WestEurope", "--hop", "EastUs"],
        config,
        gh,
    )

    assert result == 0
    chain = config.get("chains")["eu-us"]
    assert [h["location"] for h in chain["hops"]] == ["WestEurope", "EastUs"]
    assert chain["hop1_port"] == 18080
    assert chain["hop2_port"] == 18081
    assert isinstance(chain["relay_secret"], str)
    assert len(chain["relay_secret"]) >= 32


def test_chain_create_requires_exactly_two_hops(tmp_path):
    import pytest
    from csproxy.chains import cmd_chain
    from csproxy.github import GitHubManager
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    gh = GitHubManager(config_dir=tmp_path)

    with pytest.raises(ValueError, match="Exactly two"):
        cmd_chain(["create", "bad", "--hop", "WestEurope"], config, gh)


def test_chain_start_dry_run_does_not_call_github(tmp_path):
    from unittest.mock import patch
    from csproxy.chains import cmd_chain
    from csproxy.github import GitHubManager
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    config.set(
        "chains",
        {
            "eu-us": {
                "name": "eu-us",
                "hops": [{"location": "WestEurope"}, {"location": "EastUs"}],
            }
        },
    )
    config._dry_run = True
    gh = GitHubManager(config_dir=tmp_path)

    with patch.object(gh, "check_auth") as check_auth:
        result = cmd_chain(["start", "eu-us"], config, gh)

    assert result == 0
    check_auth.assert_not_called()


def test_wait_local_forward_fails_if_process_exits():
    import pytest
    from csproxy.chains import _wait_local_forward

    class DeadProcess:
        def poll(self):
            return 1

    with pytest.raises(RuntimeError, match="exited before becoming ready"):
        _wait_local_forward(19080, DeadProcess(), "chain SOCKS", timeout=1)


def test_chain_scripts_require_and_send_relay_secret(tmp_path):
    import py_compile
    from csproxy.chains import EXIT_RELAY_SCRIPT, SOCKS_RELAY_SCRIPT

    exit_script = EXIT_RELAY_SCRIPT
    socks_script = SOCKS_RELAY_SCRIPT

    assert "CS_PROXY_RELAY_SECRET_FILE" in exit_script
    assert "X-CSProxy-Chain-Secret" in exit_script
    assert "send_response(403)" in exit_script
    assert "secret123" not in exit_script
    assert "CS_PROXY_RELAY_SECRET_FILE" in socks_script
    assert "X-CSProxy-Chain-Secret" in socks_script
    assert "CS_PROXY_EXIT_HOST" in socks_script
    assert "secret123" not in socks_script

    exit_path = tmp_path / "csproxy-test-exit.py"
    socks_path = tmp_path / "csproxy-test-socks.py"
    exit_path.write_text(exit_script)
    socks_path.write_text(socks_script)
    py_compile.compile(exit_path, doraise=True)
    py_compile.compile(socks_path, doraise=True)


def test_chain_secret_backfills_older_configs():
    from csproxy.chains import _chain_secret

    chain = {"name": "legacy"}

    secret = _chain_secret(chain)

    assert chain["relay_secret"] == secret
    assert len(secret) >= 32


def test_chain_start_rolls_back_on_forward_timeout(tmp_path):
    import pytest
    from types import SimpleNamespace
    from unittest.mock import MagicMock, call, patch

    from csproxy.chains import _cmd_chain_start
    from csproxy.utils.config import Config

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid
            self.terminated = False
            self.killed = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.killed = True

    config = Config(config_dir=tmp_path)
    config.set(
        "chains",
        {
            "eu-us": {
                "name": "eu-us",
                "hops": [
                    {"location": "WestEurope", "codespace_name": "hop-one"},
                    {"location": "EastUs", "codespace_name": "hop-two"},
                ],
                "hop1_port": 18080,
                "hop2_port": 18081,
                "relay_secret": "secret",
            }
        },
    )
    parsed = SimpleNamespace(name="eu-us", port=19080)
    gh = MagicMock()
    exit_forward = FakeProcess(101)
    socks_forward = FakeProcess(102)

    with patch("csproxy.chains._ensure_chain_hops", return_value=config.get("chains")["eu-us"]["hops"]), \
         patch("csproxy.chains._upload"), \
         patch("csproxy.chains._upload_secret_file"), \
         patch("csproxy.chains._start_remote_script"), \
         patch("csproxy.chains._cleanup_remote_script") as cleanup_script, \
         patch("csproxy.chains._cleanup_remote_file") as cleanup_file, \
         patch("csproxy.chains._set_port_private") as set_port_private, \
         patch("csproxy.chains.subprocess.Popen", side_effect=[exit_forward, socks_forward]), \
         patch("csproxy.chains._wait_local_forward", side_effect=[None, RuntimeError("Timed out waiting")]):
        with pytest.raises(RuntimeError, match="Timed out waiting"):
            _cmd_chain_start(parsed, config, gh)

    assert exit_forward.terminated is True
    assert socks_forward.terminated is True
    cleanup_script.assert_has_calls(
        [
            call(gh, "hop-one", "/tmp/csproxy_chain_socks_18080.py"),
            call(gh, "hop-two", "/tmp/csproxy_chain_exit_18081.py"),
        ],
        any_order=False,
    )
    cleanup_file.assert_has_calls(
        [
            call(gh, "hop-one", "/tmp/csproxy_chain_socks_18080.secret"),
            call(gh, "hop-two", "/tmp/csproxy_chain_exit_18081.secret"),
        ],
        any_order=False,
    )
    set_port_private.assert_has_calls(
        [
            call(gh, "hop-one", 18080),
            call(gh, "hop-two", 18081),
        ],
        any_order=False,
    )


def test_start_remote_script_places_env_before_nohup():
    from unittest.mock import MagicMock, patch

    from csproxy.chains import _start_remote_script

    gh = MagicMock()

    with patch("csproxy.chains._ssh", return_value=MagicMock(returncode=0)) as ssh, \
         patch("csproxy.chains.time.sleep"):
        _start_remote_script(
            gh,
            "fake-cs",
            "/tmp/relay.py",
            "relay",
            env={"CS_PROXY_RELAY_PORT": "18080", "CS_PROXY_EXIT_HOST": "host.test"},
        )

    cmd = ssh.call_args.args[2]
    assert cmd.startswith("CS_PROXY_RELAY_PORT=18080 CS_PROXY_EXIT_HOST=host.test nohup python3")
    assert "nohup CS_PROXY_RELAY_PORT" not in cmd


def test_cleanup_remote_script_uses_safe_process_pattern():
    from unittest.mock import MagicMock, patch

    from csproxy.chains import _cleanup_remote_script

    gh = MagicMock()

    with patch("csproxy.chains._ssh") as ssh:
        _cleanup_remote_script(gh, "fake-cs", "/tmp/csproxy_chain_exit_18081.py")

    cmd = ssh.call_args.args[2]
    assert "pgrep -f '[p]ython3 .*[/]tmp/csproxy_chain_exit_18081.py'" in cmd
    assert "pkill -f" not in cmd
    assert "rm -f /tmp/csproxy_chain_exit_18081.py /tmp/csproxy_chain_exit_18081.py.log" in cmd


def test_chain_stop_sets_ports_private_and_removes_artifacts(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import MagicMock, call, patch

    from csproxy.chains import _cmd_chain_stop
    from csproxy.state import State
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    State(tmp_path).add_tunnel(
        id="chain-livews",
        kind="chain",
        name="livews",
        status="healthy",
        local_port=19083,
        pid=0,
        exit_forward_pid=0,
        hop1_port=18080,
        hop2_port=18081,
        hops=[
            {"location": "EastUs", "codespace_name": "same-cs"},
            {"location": "EastUs", "codespace_name": "same-cs"},
        ],
    )

    gh = MagicMock()

    with patch("csproxy.chains._ssh") as ssh, \
         patch("csproxy.chains._set_port_private") as set_port_private:
        result = _cmd_chain_stop(SimpleNamespace(name="livews"), config, gh)

    assert result == 0
    assert "rm -f /tmp/csproxy_chain_*" in ssh.call_args_list[0].args[2]
    set_port_private.assert_has_calls(
        [
            call(gh, "same-cs", 18080),
            call(gh, "same-cs", 18081),
        ],
        any_order=False,
    )
