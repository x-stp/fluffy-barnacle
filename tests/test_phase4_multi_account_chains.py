#!/usr/bin/env python3
"""Tests for named accounts and multi-account chain definitions."""

import pytest


def test_account_add_persists_token_env(tmp_path):
    from csproxy.proxy import cmd_account
    from csproxy.github import GitHubManager
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    gh = GitHubManager(config_dir=tmp_path)

    result = cmd_account(["add", "eu", "--token-env", "GH_TOKEN_EU"], config, gh)

    assert result == 0
    assert config.get("accounts")["eu"]["token_env"] == "GH_TOKEN_EU"


def test_account_add_rejects_raw_pat(tmp_path):
    from csproxy.proxy import cmd_account
    from csproxy.github import GitHubManager
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    gh = GitHubManager(config_dir=tmp_path)

    with pytest.raises(ValueError, match="raw tokens"):
        cmd_account(["add", "bad", "--token-env", "ghp_secret"], config, gh)


def test_chain_create_accepts_account_hop_specs(tmp_path):
    from csproxy.chains import cmd_chain
    from csproxy.github import GitHubManager
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    gh = GitHubManager(config_dir=tmp_path)

    result = cmd_chain(
        ["create", "eu-us", "--hop", "eu:WestEurope", "--hop", "us:EastUs"],
        config,
        gh,
    )

    assert result == 0
    hops = config.get("chains")["eu-us"]["hops"]
    assert hops[0]["account"] == "eu"
    assert hops[0]["location"] == "WestEurope"
    assert hops[1]["account"] == "us"
    assert hops[1]["location"] == "EastUs"
