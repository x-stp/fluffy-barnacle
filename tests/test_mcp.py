"""Tests for the MCP server front-end (csproxy.mcp.server).

These assert the server registers the expected tools/resources and that each
tool delegates to the service layer / GitHubManager rather than reimplementing
logic. Heavy work (gh, ssh) is mocked at the csproxy.mcp.server seam.

Skipped entirely if the optional `mcp` extra is not installed.
"""

import asyncio

import pytest

pytest.importorskip("mcp", reason="requires the optional 'mcp' extra")

from csproxy.mcp.server import build_server  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _result_json(call_tool_return):
    """Pull the payload out of a FastMCP low-level call_tool() return.

    The SDK returns either a bare content list or a (content, structured) tuple
    depending on the tool's return type, so parse the always-present TextContent
    JSON rather than depending on the structured half's shape.
    """
    import json

    if isinstance(call_tool_return, tuple):
        structured = call_tool_return[1]
        # FastMCP wraps non-object returns (lists, scalars) under "result".
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured
    return json.loads(call_tool_return[0].text)


EXPECTED_TOOLS = {
    "diagnostics",
    "list_pool",
    "list_codespaces",
    "get_codespace",
    "get_logs",
    "list_chains",
    "stop_tunnel",
    "drain_tunnel",
    "rotate_pool",
    "stop_all_tunnels",
    "start_chain",
    "stop_chain",
    "delete_chain",
    "create_codespace",
    "delete_codespace",
    "start_codespace",
    "stop_codespace",
}


def test_all_tools_registered():
    server = build_server()
    names = {t.name for t in _run(server.list_tools())}
    assert EXPECTED_TOOLS <= names


def test_resources_registered():
    server = build_server()
    uris = {str(r.uri) for r in _run(server.list_resources())}
    assert {"cs://pool", "cs://codespaces"} <= uris


def test_destructive_tools_flagged_in_description():
    """delete/stop-all tools must carry a DESTRUCTIVE marker so MCP clients
    surface a warning before calling them."""
    server = build_server()
    by_name = {t.name: t for t in _run(server.list_tools())}
    for name in ("delete_codespace", "stop_all_tunnels", "stop_chain", "delete_chain"):
        assert "DESTRUCTIVE" in (by_name[name].description or "")


def test_diagnostics_delegates_to_service(monkeypatch):
    import csproxy.mcp.server as srv
    from csproxy.services import Check

    sentinel = [Check("PASS", "looks good")]
    monkeypatch.setattr(srv.services, "run_diagnostics", lambda config, gh: sentinel)

    server = build_server()
    payload = _result_json(_run(server.call_tool("diagnostics", {})))
    assert payload == [{"status": "PASS", "message": "looks good"}]


def test_create_codespace_delegates_to_gh(monkeypatch):
    import csproxy.mcp.server as srv

    class FakeGH:
        def create_codespace(self, repo=None, machine="basicLinux32gb"):
            return {"name": f"cs-{machine}"}

    monkeypatch.setattr(srv, "_context", lambda: (object(), FakeGH()))

    server = build_server()
    payload = _result_json(
        _run(server.call_tool("create_codespace", {"machine": "basicLinux32gb"}))
    )
    assert payload == {"name": "cs-basicLinux32gb"}


def test_stop_tunnel_delegates_to_service(monkeypatch):
    import csproxy.mcp.server as srv

    calls = {}
    monkeypatch.setattr(
        srv.services, "stop_tunnel", lambda config, port: calls.setdefault("port", port)
    )

    server = build_server()
    _run(server.call_tool("stop_tunnel", {"port": 1080}))
    assert calls["port"] == 1080
