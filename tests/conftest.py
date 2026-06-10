import pytest


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path, monkeypatch):
    """Keep tests from reading or writing the user's real cs-proxy config."""
    monkeypatch.setenv("CS_PROXY_CONFIG_DIR", str(tmp_path / "cs-proxy"))


@pytest.fixture(autouse=True)
def clear_check_cache():
    """Clear the proxy health-check cache so tests don't pollute each other."""
    from csproxy.tools import _CHECK_CACHE

    _CHECK_CACHE.clear()
