"""Smoke tests for the Textual TUI (skipped when the 'tui' extra is absent)."""

import asyncio

import pytest

pytest.importorskip("textual")

from csproxy.github import GitHubManager  # noqa: E402
from csproxy.services import Check  # noqa: E402
from csproxy.tui.app import CsProxyTUI  # noqa: E402
from csproxy.utils import Config  # noqa: E402


def _app():
    config = Config()
    config.ensure_dirs()
    gh = GitHubManager(config_dir=config.config_dir)
    # Large interval so the auto-refresh timer doesn't fire during the test.
    return CsProxyTUI(config, gh, interval=3600)


def test_tui_mounts_with_expected_columns():
    async def scenario():
        app = _app()
        async with app.run_test() as pilot:
            await pilot.pause()
            from textual.widgets import DataTable

            assert len(app.query_one("#tunnels_table", DataTable).columns) == 5
            assert len(app.query_one("#codespaces_table", DataTable).columns) == 4
            assert len(app.query_one("#diag_table", DataTable).columns) == 2

    asyncio.run(scenario())


def test_tui_apply_populates_tables():
    async def scenario():
        app = _app()
        async with app.run_test() as pilot:
            await pilot.pause()
            from textual.widgets import DataTable

            data = {
                "locked": False,
                "tunnels": [
                    {
                        "port": 1080,
                        "status": "healthy",
                        "codespace_name": "demo",
                        "pid": 4242,
                        "failures": 0,
                    }
                ],
                "codespaces": [],
                "checks": [Check("PASS", "gh CLI is installed")],
                "logs": ["hello"],
            }
            app._apply(data)
            await pilot.pause()

            assert app.query_one("#tunnels_table", DataTable).row_count == 1
            assert app.query_one("#diag_table", DataTable).row_count == 1

    asyncio.run(scenario())


def test_tui_handles_locked_state():
    async def scenario():
        app = _app()
        async with app.run_test() as pilot:
            await pilot.pause()
            # Locked state must not raise and must leave the status bar informative.
            app._apply(
                {
                    "locked": True,
                    "tunnels": [],
                    "codespaces": [],
                    "checks": [],
                    "logs": [],
                }
            )
            await pilot.pause()
            assert "locked" in app._status_text.lower()

    asyncio.run(scenario())
