#!/usr/bin/env python3
"""
Textual app for csproxy — a live monitor with actions.

Renders the same structured data the CLI uses (via csproxy.services), refreshing
on a timer, and drives the same service layer for mutating actions (stop/drain/
rotate tunnels; create/start/stop/delete codespaces). All blocking work (gh/ssh/
curl subprocess calls) runs in threaded workers so the UI never freezes,
destructive actions are gated behind a confirmation modal, and create prompts
for its repo through an input modal.
"""

from __future__ import annotations

from typing import Callable, Optional

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Log,
    Static,
    TabbedContent,
    TabPane,
)

from ..github import GitHubManager
from ..services import (
    delete_chain,
    drain_tunnel,
    get_logs,
    list_chains,
    list_codespaces_safe,
    list_pool,
    rotate_pool,
    run_diagnostics,
    start_chain,
    stop_chain,
    stop_tunnel,
)
from ..utils import Config


class ConfirmScreen(ModalScreen[bool]):
    """A small yes/no modal used to gate destructive actions."""

    CSS = """
    ConfirmScreen { align: center middle; }
    #dialog {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: 1fr 3;
        padding: 1 2;
        width: 60;
        height: 11;
        border: thick $background 80%;
        background: $surface;
    }
    #question { column-span: 2; height: 1fr; content-align: center middle; }
    Button { width: 100%; }
    """

    BINDINGS = [("escape", "dismiss_no", "Cancel")]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        yield Grid(
            Label(self._question, id="question"),
            Button("Yes", variant="error", id="yes"),
            Button("No", variant="primary", id="no"),
            id="dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_dismiss_no(self) -> None:
        self.dismiss(False)


class InputScreen(ModalScreen[Optional[str]]):
    """A small text-input modal. Dismisses with the entered text, or None on
    cancel/empty. Used to collect e.g. the repo for a codespace create."""

    CSS = """
    InputScreen { align: center middle; }
    #idialog {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: 1fr 3 3;
        padding: 1 2;
        width: 70;
        height: 14;
        border: thick $background 80%;
        background: $surface;
    }
    #iprompt { column-span: 2; height: 1fr; content-align: center middle; }
    #ivalue { column-span: 2; }
    Button { width: 100%; }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, value: str = "", placeholder: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._value = value
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        yield Grid(
            Label(self._prompt, id="iprompt"),
            Input(value=self._value, placeholder=self._placeholder, id="ivalue"),
            Button("OK", variant="primary", id="ok"),
            Button("Cancel", variant="default", id="cancel"),
            id="idialog",
        )

    def on_mount(self) -> None:
        self.query_one("#ivalue", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        value: str = self.query_one("#ivalue", Input).value.strip()
        self.dismiss(value or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class CsProxyTUI(App):
    """Live monitor + actions for tunnels, codespaces, diagnostics, and logs."""

    TITLE = "cs-proxy"
    SUB_TITLE = "Codespaces proxy monitor"

    CSS = """
    DataTable { height: 1fr; }
    Log { height: 1fr; }
    #statusbar { dock: bottom; height: 1; color: $text-muted; padding: 0 1; }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("c", "create", "Create"),
        ("s", "start", "Start"),
        ("x", "stop", "Stop"),
        ("d", "drain", "Drain"),
        ("o", "rotate", "Rotate"),
        ("delete", "delete", "Delete"),
        ("q", "quit", "Quit"),
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
        self._tunnels: list[dict] = []
        self._codespaces: list[dict] = []
        self._chains: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="tab-tunnels"):
            with TabPane("Tunnels", id="tab-tunnels"):
                yield DataTable(id="tunnels_table", zebra_stripes=True, cursor_type="row")
            with TabPane("Codespaces", id="tab-codespaces"):
                yield DataTable(id="codespaces_table", zebra_stripes=True, cursor_type="row")
            with TabPane("Chains", id="tab-chains"):
                yield DataTable(id="chains_table", zebra_stripes=True, cursor_type="row")
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
        self.query_one("#chains_table", DataTable).add_columns(
            "Name", "Status", "Hop 1", "Hop 2", "Local"
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
            data["chains"] = list_chains(self._config)
            data["locked"] = False
        except TimeoutError:
            data["tunnels"] = []
            data["chains"] = []
            data["locked"] = True
        data["codespaces"] = list_codespaces_safe(self._gh)
        data["checks"] = run_diagnostics(self._config, self._gh)
        data["logs"] = get_logs(self._config, lines=200)
        self.call_from_thread(self._apply, data)

    def _apply(self, data: dict) -> None:
        if data["locked"]:
            self._set_status("State file locked by another process — retrying…")
        else:
            self._tunnels = data["tunnels"]
            self._fill_tunnels(data["tunnels"])
            self._chains = data.get("chains", [])
            self._fill_chains(self._chains)
        self._codespaces = data["codespaces"]
        self._fill_codespaces(data["codespaces"])
        self._fill_diagnostics(data["checks"])
        self._fill_logs(data["logs"])
        if not data["locked"]:
            failures = sum(1 for c in data["checks"] if not c.ok)
            self._set_status(
                f"{len(data['tunnels'])} tunnel(s) · "
                f"{len(data['codespaces'])} codespace(s) · "
                f"{len(self._chains)} chain(s) · "
                f"{failures} check failure(s)  —  c new, s/x/d/o/Del to act, r refresh, q quit"
            )

    # ------------------------------------------------------------------
    # Actions (key bindings). Each acts on the selected row of the active
    # tab; destructive ones go through a confirmation modal first.
    # ------------------------------------------------------------------

    def action_stop(self) -> None:
        tab = self._active_tab()
        if tab == "tab-tunnels":
            t = self._selected_tunnel()
            if not t:
                self.notify("No tunnel selected", severity="warning")
                return
            port = t["port"]
            self._confirm(
                f"Stop tunnel :{port}?",
                lambda: stop_tunnel(self._config, port),
                f"Stopped tunnel :{port}",
            )
        elif tab == "tab-codespaces":
            cs = self._selected_codespace()
            if not cs:
                self.notify("No codespace selected", severity="warning")
                return
            name = cs["name"]
            self._confirm(
                f"Stop codespace {name}?",
                lambda: self._gh.stop_codespace(name),
                f"Stopped codespace {name}",
            )
        elif tab == "tab-chains":
            ch = self._selected_chain()
            if not ch:
                self.notify("No chain selected", severity="warning")
                return
            name = ch["name"]
            self._confirm(
                f"Stop chain {name}?",
                lambda: stop_chain(self._config, self._gh, name),
                f"Stopped chain {name}",
            )

    def action_create(self) -> None:
        if self._active_tab() != "tab-codespaces":
            self.notify("Switch to the Codespaces tab to create one", severity="warning")
            return

        # Prefill from config if set, else a public template that always supports
        # Codespaces so the field is never empty.
        default_repo: str = str(self._config.get("codespace_repo", "") or "") or (
            "github/codespaces-blank"
        )

        def on_result(repo: Optional[str]) -> None:
            if not repo:
                return
            self.notify(f"Creating codespace from {repo}… this can take a minute")
            self._perform(
                lambda: self._gh.create_codespace(repo=repo),
                f"Created codespace from {repo}",
            )

        self.push_screen(
            InputScreen(
                "Create codespace from repository (owner/repo):",
                value=default_repo,
                placeholder="owner/repo",
            ),
            on_result,
        )

    def action_start(self) -> None:
        tab = self._active_tab()
        if tab == "tab-codespaces":
            cs = self._selected_codespace()
            if not cs:
                self.notify("No codespace selected", severity="warning")
                return
            name = cs["name"]
            self._perform(lambda: self._gh.start_codespace(name), f"Started codespace {name}")
        elif tab == "tab-chains":
            ch = self._selected_chain()
            if not ch:
                self.notify("No chain selected", severity="warning")
                return
            name = ch["name"]
            self.notify(f"Starting chain {name}… this can take a minute")
            self._perform(
                lambda: start_chain(self._config, self._gh, name), f"Started chain {name}"
            )
        else:
            self.notify("Select a codespace or chain to start", severity="warning")

    def action_drain(self) -> None:
        if self._active_tab() != "tab-tunnels":
            self.notify("Select a tunnel to drain", severity="warning")
            return
        t = self._selected_tunnel()
        if not t:
            self.notify("No tunnel selected", severity="warning")
            return
        port = t["port"]
        self._perform(lambda: drain_tunnel(self._config, port), f"Draining tunnel :{port}")

    def action_delete(self) -> None:
        tab = self._active_tab()
        if tab == "tab-codespaces":
            cs = self._selected_codespace()
            if not cs:
                self.notify("No codespace selected", severity="warning")
                return
            name = cs["name"]
            self._confirm(
                f"Delete codespace {name}? This cannot be undone.",
                lambda: self._gh.delete_codespace(name, force=True),
                f"Deleted codespace {name}",
            )
        elif tab == "tab-chains":
            ch = self._selected_chain()
            if not ch:
                self.notify("No chain selected", severity="warning")
                return
            name = ch["name"]
            self._confirm(
                f"Delete chain definition {name}?",
                lambda: delete_chain(self._config, name),
                f"Deleted chain {name}",
            )
        else:
            self.notify("Select a codespace or chain to delete", severity="warning")

    def action_rotate(self) -> None:
        self._rotate()

    @work(thread=True, group="action")
    def _rotate(self) -> None:
        try:
            port = rotate_pool(self._config)
            self.call_from_thread(self.notify, f"Healthy tunnel: :{port}")
        except Exception as e:  # surfaced to the user, not swallowed
            self.call_from_thread(self.notify, f"Rotate failed: {e}", severity="error")

    # ------------------------------------------------------------------
    # Action plumbing.
    # ------------------------------------------------------------------

    def _confirm(self, question: str, fn: Callable[[], object], success: str) -> None:
        def on_result(confirmed: Optional[bool]) -> None:
            if confirmed:
                self._perform(fn, success)

        self.push_screen(ConfirmScreen(question), on_result)

    def _perform(self, fn: Callable[[], object], success: str) -> None:
        self._run_action(fn, success)

    @work(thread=True, group="action")
    def _run_action(self, fn: Callable[[], object], success: str) -> None:
        try:
            fn()
            self.call_from_thread(self._action_done, success, None)
        except Exception as e:  # surfaced to the user, not swallowed
            self.call_from_thread(self._action_done, success, e)

    def _action_done(self, success: str, error: Optional[Exception]) -> None:
        if error is not None:
            self.notify(f"Failed: {error}", severity="error")
        else:
            self.notify(success)
        self.refresh_data()

    # ------------------------------------------------------------------
    # Selection helpers.
    # ------------------------------------------------------------------

    def _active_tab(self) -> str:
        # Annotated locals keep these precise even when textual is unavailable
        # to mypy (the lint job doesn't install the optional tui extra), where
        # the widget attributes would otherwise be typed as Any.
        active: str = self.query_one(TabbedContent).active
        return active

    def _selected_tunnel(self) -> Optional[dict]:
        return self._row_item("#tunnels_table", self._tunnels)

    def _selected_codespace(self) -> Optional[dict]:
        return self._row_item("#codespaces_table", self._codespaces)

    def _selected_chain(self) -> Optional[dict]:
        return self._row_item("#chains_table", self._chains)

    def _row_item(self, table_id: str, items: list[dict]) -> Optional[dict]:
        table = self.query_one(table_id, DataTable)
        row: int = table.cursor_row
        if items and 0 <= row < len(items):
            return items[row]
        return None

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

    @staticmethod
    def _format_hop(hop: dict) -> str:
        """Render a hop as 'Region · account', or just 'Region' for the default PAT."""
        location = hop.get("location") or "?"
        account = hop.get("account")
        return f"{location} · {account}" if account else location

    def _fill_chains(self, chains: list[dict]) -> None:
        table = self.query_one("#chains_table", DataTable)
        table.clear()
        for ch in chains:
            hops = ch.get("hops", [])
            hop1 = self._format_hop(hops[0]) if len(hops) > 0 else "—"
            hop2 = self._format_hop(hops[1]) if len(hops) > 1 else "—"
            local = f":{ch['local_port']}" if ch.get("local_port") else "—"
            table.add_row(str(ch.get("name", "")), str(ch.get("status", "")), hop1, hop2, local)

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
