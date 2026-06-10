#!/usr/bin/env python3
"""
Textual app for csproxy — Phase 0: a read-only live monitor.

Renders the same structured data the CLI uses (via csproxy.services), refreshing
on a timer. All blocking work (gh/ssh/curl subprocess calls inside the service
functions) runs in a threaded worker so the UI never freezes. Actions
(start/stop/rotate) are intentionally out of scope for this phase.
"""

from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Log,
    Static,
    TabbedContent,
    TabPane,
)

from ..github import GitHubManager
from ..services import get_logs, list_codespaces_safe, list_pool, run_diagnostics
from ..utils import Config


class CsProxyTUI(App):
    """Read-only monitor for tunnels, codespaces, diagnostics, and logs."""

    TITLE = "cs-proxy"
    SUB_TITLE = "Codespaces proxy monitor"

    CSS = """
    DataTable { height: 1fr; }
    Log { height: 1fr; }
    #statusbar { dock: bottom; height: 1; color: $text-muted; padding: 0 1; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh now"),
    ]

    def __init__(
        self,
        config: Config,
        gh: GitHubManager,
        interval: float = 3.0,
    ) -> None:
        super().__init__()
        self._config = config
        self._gh = gh
        self._interval = interval
        self._status_text = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="tab-tunnels"):
            with TabPane("Tunnels", id="tab-tunnels"):
                yield DataTable(id="tunnels_table", zebra_stripes=True)
            with TabPane("Codespaces", id="tab-codespaces"):
                yield DataTable(id="codespaces_table", zebra_stripes=True)
            with TabPane("Diagnostics", id="tab-diagnostics"):
                yield DataTable(id="diag_table", zebra_stripes=True)
            with TabPane("Logs", id="tab-logs"):
                yield Log(id="logs_view", highlight=False)
        yield Static("Loading…", id="statusbar")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#tunnels_table", DataTable).add_columns(
            "Port", "Status", "Codespace", "PID", "Failures"
        )
        self.query_one("#codespaces_table", DataTable).add_columns(
            "Name", "State", "Repository", "Created"
        )
        self.query_one("#diag_table", DataTable).add_columns("Result", "Check")
        self.refresh_data()
        self.set_interval(self._interval, self.refresh_data)

    # ------------------------------------------------------------------
    # Refresh pipeline: collect off-thread, apply on the UI thread.
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        self._collect()

    @work(thread=True, exclusive=True, group="refresh")
    def _collect(self) -> None:
        """Gather all view data off the UI thread (blocking subprocess calls)."""
        data: dict = {}
        try:
            data["tunnels"] = list_pool(self._config)
            data["locked"] = False
        except TimeoutError:
            data["tunnels"] = []
            data["locked"] = True
        data["codespaces"] = list_codespaces_safe(self._gh)
        data["checks"] = run_diagnostics(self._config, self._gh)
        data["logs"] = get_logs(self._config, lines=200)
        self.call_from_thread(self._apply, data)

    def _apply(self, data: dict) -> None:
        if data["locked"]:
            self._set_status("State file locked by another process — retrying…")
        else:
            self._fill_tunnels(data["tunnels"])
        self._fill_codespaces(data["codespaces"])
        self._fill_diagnostics(data["checks"])
        self._fill_logs(data["logs"])
        if not data["locked"]:
            failures = sum(1 for c in data["checks"] if not c.ok)
            self._set_status(
                f"{len(data['tunnels'])} tunnel(s) · "
                f"{len(data['codespaces'])} codespace(s) · "
                f"{failures} check failure(s)  —  press r to refresh, q to quit"
            )

    # ------------------------------------------------------------------
    # Table/log fillers (UI thread only).
    # ------------------------------------------------------------------

    def _fill_tunnels(self, tunnels: list[dict]) -> None:
        table = self.query_one("#tunnels_table", DataTable)
        table.clear()
        for t in tunnels:
            table.add_row(
                str(t.get("port", "?")),
                str(t.get("status", "unknown")),
                str(t.get("codespace_name") or "—"),
                str(t.get("pid", "—")),
                str(t.get("failures", 0)),
            )

    def _fill_codespaces(self, codespaces: list[dict]) -> None:
        table = self.query_one("#codespaces_table", DataTable)
        table.clear()
        for cs in codespaces:
            table.add_row(
                str(cs.get("name", "")),
                str(cs.get("state", "")),
                str(cs.get("repository", "")),
                str(cs.get("createdAt", ""))[:10],
            )

    def _fill_diagnostics(self, checks) -> None:
        table = self.query_one("#diag_table", DataTable)
        table.clear()
        for c in checks:
            table.add_row("✓ PASS" if c.ok else "✗ FAIL", c.message)

    def _fill_logs(self, lines: list[str]) -> None:
        log = self.query_one("#logs_view", Log)
        log.clear()
        if lines:
            log.write_lines(lines)
        else:
            log.write_line("(no proxy.log yet)")

    def _set_status(self, text: str) -> None:
        self._status_text = text
        self.query_one("#statusbar", Static).update(text)


def run_app(argv=None) -> int:
    """Build and run the TUI. Returns a process exit code."""
    config = Config()
    config.ensure_dirs()
    gh = GitHubManager(config_dir=config.config_dir)
    CsProxyTUI(config, gh).run()
    return 0
