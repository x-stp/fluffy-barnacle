"""Smoke tests for the Textual TUI (skipped when the 'tui' extra is absent)."""

import asyncio
from unittest.mock import patch

import pytest

pytest.importorskip("textual")

from csproxy.github import GitHubManager  # noqa: E402
from csproxy.services import Check  # noqa: E402
from csproxy.state import State  # noqa: E402
from csproxy.tui.app import ConfirmScreen, CsProxyTUI  # noqa: E402
from csproxy.utils import Config  # noqa: E402
from textual.worker import WorkerCancelled  # noqa: E402


async def _settle(app):
    """Wait for queued workers to finish, tolerating the benign cancellation
    of the exclusive 'refresh' worker that an action supersedes when it kicks
    off its own post-action refresh. wait_for_complete() re-raises that
    cancellation as WorkerCancelled even though the action itself completed."""
    try:
        await app.workers.wait_for_complete()
    except WorkerCancelled:
        pass


def _tunnel_row(port=1080, status="healthy"):
    return {
        "port": port,
        "status": status,
        "codespace_name": "demo",
        "pid": 4242,
        "failures": 0,
    }


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
            assert len(app.query_one("#chains_table", DataTable).columns) == 5
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


def test_tui_drain_action_updates_state():
    async def scenario():
        import os

        config = Config()
        config.ensure_dirs()
        # Use a live PID so the periodic reconcile doesn't flip the tunnel to
        # "crashed" before/after the drain action.
        State(config.config_dir).add_tunnel(
            id="ssh-1080",
            kind="ssh",
            codespace_name="demo",
            port=1080,
            pid=os.getpid(),
            status="healthy",
            failures=0,
        )
        gh = GitHubManager(config_dir=config.config_dir)
        app = CsProxyTUI(config, gh, interval=3600)
        async with app.run_test() as pilot:
            await _settle(app)
            await pilot.pause()
            assert app._tunnels and app._tunnels[0]["port"] == 1080

            await pilot.press("d")  # drain selected tunnel (no confirmation)
            await _settle(app)
            await pilot.pause()

            assert State(config.config_dir).get_tunnel_by_port(1080)["status"] == "draining"

    asyncio.run(scenario())


def test_tui_stop_shows_then_cancels_confirm():
    async def scenario():
        app = _app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app._apply(
                {
                    "locked": False,
                    "tunnels": [_tunnel_row()],
                    "codespaces": [],
                    "checks": [],
                    "logs": [],
                }
            )
            await pilot.pause()

            await pilot.press("x")  # stop selected tunnel -> confirmation modal
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)

            await pilot.press("escape")  # cancel
            await pilot.pause()
            assert not isinstance(app.screen, ConfirmScreen)

    asyncio.run(scenario())


def test_tui_stop_confirm_invokes_service():
    async def scenario():
        app = _app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app._apply(
                {
                    "locked": False,
                    "tunnels": [_tunnel_row()],
                    "codespaces": [],
                    "checks": [],
                    "logs": [],
                }
            )
            await pilot.pause()

            with patch("csproxy.tui.app.stop_tunnel") as mock_stop:
                await pilot.press("x")
                await pilot.pause()
                app.screen.dismiss(True)  # confirm "yes"
                await _settle(app)
                await pilot.pause()
            mock_stop.assert_called_once()

    asyncio.run(scenario())


def _chain_row(name="eu-us", status="defined", local_port=None):
    return {
        "name": name,
        "status": status,
        "local_port": local_port,
        "running": local_port is not None,
        "hops": [
            {"location": "WestEurope", "account": "work"},
            {"location": "EastUs", "account": ""},
        ],
    }


def test_tui_chains_tab_renders_account_per_hop():
    async def scenario():
        from textual.widgets import DataTable

        app = _app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app._apply(
                {
                    "locked": False,
                    "tunnels": [],
                    "chains": [_chain_row()],
                    "codespaces": [],
                    "checks": [],
                    "logs": [],
                }
            )
            await pilot.pause()
            table = app.query_one("#chains_table", DataTable)
            assert table.row_count == 1
            # Hop 1 carries the account; Hop 2 (default PAT) shows region only.
            row = table.get_row_at(0)
            assert row[2] == "WestEurope · work"
            assert row[3] == "EastUs"

    asyncio.run(scenario())


def test_tui_chain_delete_confirm_invokes_service():
    async def scenario():
        from textual.widgets import TabbedContent

        app = _app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app._apply(
                {
                    "locked": False,
                    "tunnels": [],
                    "chains": [_chain_row()],
                    "codespaces": [],
                    "checks": [],
                    "logs": [],
                }
            )
            app.query_one(TabbedContent).active = "tab-chains"
            await pilot.pause()

            with patch("csproxy.tui.app.delete_chain") as mock_delete:
                await pilot.press("delete")  # delete chain definition -> confirm
                await pilot.pause()
                assert isinstance(app.screen, ConfirmScreen)
                app.screen.dismiss(True)
                await _settle(app)
                await pilot.pause()
            mock_delete.assert_called_once()

    asyncio.run(scenario())
