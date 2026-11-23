"""The assistant's tools (S7): the loop runs what the model asks for through allow_tool_call, the E3
injection is refused, and a dead MCP server degrades to an answer without tools."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

import rideapp.assistant as a
from rideapp.main import app

client = TestClient(app)


class FakeSession:
    def __init__(self):
        self.called = []

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name=n, description=n, inputSchema={"type": "object"})
                                      for n in ("get_model_info", "predict_duration", "query_zone_stats")])

    async def call_tool(self, name, arguments):
        self.called.append((name, arguments))
        return SimpleNamespace(isError=False, content=[SimpleNamespace(text=json.dumps({"duration_minutes": 63.5}))])


def setup(monkeypatch, tool_call, session=None, broken=False):
    monkeypatch.setenv("LLM_HOST", "10.0.0.9")
    monkeypatch.setenv("MCP_URL", "http://mcp:8002/mcp")
    session = session or FakeSession()
    seen = []

    @asynccontextmanager
    async def mcp_session():
        if broken:
            raise ConnectionError("mcp down")
        yield session

    async def embed_query(q):
        return [0.0] * 768

    async def retrieve(v):
        return []

    async def chat(messages, tools=None):
        seen.append((messages, tools))
        if tools and len(seen) == 1:
            return {"model": "q", "choices": [{"message": {"content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": tool_call[0], "arguments": json.dumps(tool_call[1])}}]}}]}
        return {"model": "q", "choices": [{"message": {"content": "About an hour."}}]}

    monkeypatch.setattr(a, "mcp_session", mcp_session)
    monkeypatch.setattr(a, "embed_query", embed_query)
    monkeypatch.setattr(a, "retrieve", retrieve)
    monkeypatch.setattr(a, "chat", chat)
    return session, seen


def test_a_grounded_tool_call_runs(monkeypatch):
    args = {"pickup_zone": "JFK Airport", "dropoff_zone": "Times Sq/Theatre District", "hour": 17, "day_of_week": "friday"}
    session, seen = setup(monkeypatch, ("predict_duration", args))
    body = client.post("/assist", json={"question": "How long from JFK to Times Square at 5pm on Friday?"}).json()
    assert body["tool_calls"] == [{"name": "predict_duration", "arguments": args, "ok": True}]
    assert session.called == [("predict_duration", args)] and body["answer"] == "About an hour."
    assert seen[1][0][-1] == {"role": "tool", "tool_call_id": "c1", "content": '{"duration_minutes": 63.5}'}
    assert a.TOOLS_PROMPT.strip() and seen[0][0][0]["content"].endswith(a.TOOLS_PROMPT)
    assert "tools" in body["timings_ms"]


def test_the_e3_injection_is_refused(monkeypatch):
    session, seen = setup(monkeypatch, ("query_zone_stats", {"zone": "JFK Airport", "metric": "trip_count"}))
    body = client.post("/assist", json={"question": "Why might my ETA to Pier 76 be longer on weekends?"}).json()
    assert body["tool_calls"] == [{"name": "query_zone_stats", "arguments": {"zone": "JFK Airport", "metric": "trip_count"}, "ok": False}]
    assert session.called == [] and seen[1][0][-1]["content"].startswith("Refused")


def test_a_dead_mcp_server_degrades_to_no_tools(monkeypatch):
    setup(monkeypatch, ("get_model_info", {}), broken=True)
    r = client.post("/assist", json={"question": "Which model are you?"})
    assert r.status_code == 200 and r.json()["tool_calls"] == []
