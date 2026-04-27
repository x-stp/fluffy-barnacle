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
