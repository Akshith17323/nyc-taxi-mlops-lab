"""predict_duration and query_zone_stats with serving and the warehouse faked: the right ids and
encodings go to serving, nothing from a tool call is formatted into SQL, and errors say what to fix."""

import json

import pytest
from mcp.server.fastmcp.exceptions import ToolError

import labmcp.server as s


async def call(name, args):
    return json.loads((await s.mcp.call_tool(name, args))[0].text)


async def test_predict_duration_maps_names_and_days_for_serving(monkeypatch):
    sent = []

    async def champion(method, path, body=None):
        sent.append(body)
        return {"duration_minutes": 63.5, "model": {"name": "trip-duration", "version": "3", "alias": "champion"}}

    monkeypatch.setattr(s, "champion", champion)
    out = await call("predict_duration", {"pickup_zone": "JFK Airport", "dropoff_zone": "Times Sq/Theatre District", "hour": 17, "day_of_week": "friday"})
    assert sent == [{"pickup_zone_id": 132, "dropoff_zone_id": 230, "pickup_hour": 17, "pickup_dow": 5}]
    assert out["duration_minutes"] == 63.5 and out["model_version"] == "3"
    with pytest.raises(ToolError, match="did you mean"):
        await s.mcp.call_tool("predict_duration", {"pickup_zone": "JFK Airprot", "dropoff_zone": "Midtown Center", "hour": 9, "day_of_week": "monday"})


class FakeWarehouse:
    calls: list = []

    def __init__(self, db_user=None):
        pass

    def query(self, sql, params=None, timeout_s=30):
        FakeWarehouse.calls.append((sql, params))
        return [{"pickup_hour": 17, "value": 41.2, "first_month": "2024-01", "last_month": "2024-04"}]


async def test_query_zone_stats_is_parameterised(monkeypatch):
    monkeypatch.setattr(s, "Warehouse", FakeWarehouse)
    out = await call("query_zone_stats", {"zone": "JFK Airport", "metric": "median_duration_min", "hour": 17})
    sql, params = FakeWarehouse.calls[-1]
    assert params == {"zone": "JFK Airport", "hour": 17} and "JFK" not in sql and ":zone" in sql
    assert out == {"zone": "JFK Airport", "metric": "median_duration_min", "months": "2024-01..2024-04", "by_hour": {"17": 41.2}}
    with pytest.raises(ToolError):
        await s.mcp.call_tool("query_zone_stats", {"zone": "JFK Airport", "metric": "fare_amount"})  # not in the contract's enum
