"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Every REST endpoint (read-only) - the only door into the database.

Adding an endpoint = one function here. main.py includes this router
BEFORE the static website mount, so these paths always win over files.

Note on plain 'def' (not 'async def'): these endpoints use the
synchronous pymongo driver, which BLOCKS while waiting for the
database. FastAPI automatically runs plain 'def' endpoints in a worker
thread, so blocking calls never freeze the event loop.

link at 
http://localhost:8000/docs, replace port with your API host/port if different.
replace docs with  all the other endpoints
ie http://localhost:8000/villages
"""

from fastapi import APIRouter, HTTPException
import state

router = APIRouter()

# helper ---------------
"""
Make one Mongo document safe to return as JSON.
Mongo's _id is an ObjectId object, which FastAPI cannot serialize,
so swap it for a plain string field "id".
"""
def serialize(doc):
    if doc is None:
        return None
    result = dict(doc)
    result["id"] = str(result.pop("_id", ""))
    return result

"""Keep list endpoints from being asked for a million rows."""
def clamp_limit(limit, default=50, maximum=1000):
    if limit is None:
        return default
    return max(1, min(limit, maximum))


"""Uptime check: is the service up, and are its dependencies reachable?
    Deliberately never raises - a problem is reported, not hidden."""
@router.get("/health")
def health():
    db_ok = False
    try:
        state.state["db"].command("ping")
        db_ok = True
    except Exception:
        pass
    return {
        "status": "ok" if db_ok else "degraded",
        "mongo": db_ok,
        "redis": state.state["redis"] is not None,
    }

"""Overall system counters: masters online, river nodes online, ..."""
@router.get("/stats")
def get_global_stats():
    doc = state.state["db"].global_stats.find_one({"_id": "global"})
    return serialize(doc) if doc else {}

# nodes ---------------
"""All villages: status, node counters, alerts, cached mesh topology."""
@router.get("/villages")
def list_villages():
    docs = state.state["db"].villages.find().sort("_id", 1)
    return [serialize(doc) for doc in docs]

"""One village: master info, online flag, node counts, topology."""
@router.get("/villages/{village_id}")
def get_village(village_id: str):
    doc = state.state["db"].villages.find_one({"_id": village_id})
    if doc is None:
        raise HTTPException(status_code=404,
                            detail=f"Village '{village_id}' not found")
    return serialize(doc)


"""All river nodes of a village with their latest values."""
@router.get("/villages/{village_id}/nodes")
def list_nodes(village_id: str):
    docs = state.state["db"].river_nodes.find(
        {"village_id": village_id}).sort("node_id", 1)
    return [serialize(doc) for doc in docs]

"""
One river node: parent, depth, status, latest telemetry, alert counts.
Node ids are unique per village (not globally), so both ids are needed.
"""
@router.get("/villages/{village_id}/nodes/{node_id}")
def get_node(village_id: str, node_id: str):
    doc = state.state["db"].river_nodes.find_one(
        {"node_id": node_id, "village_id": village_id})
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Node '{node_id}' not found in village '{village_id}'",
        )
    return serialize(doc)

"""
History of one node's telemetry, newest first.

Optional query parameters:
    param  - one kind only: battery, water, gps, signal (default: all)
    limit  - how many rows (default 100, capped at 1000)

Example: /villages/SUTS/nodes/SUTS-001/telemetry?param=water&limit=50
"""
@router.get("/villages/{village_id}/nodes/{node_id}/telemetry")
def get_node_telemetry(village_id: str, node_id: str,
                       param: str | None = None, limit: int = 100):

    query = {"node_id": node_id, "village_id": village_id}
    if param is not None:
        query["param"] = param

    n = clamp_limit(limit, default=100)
    docs = state.state["db"].telemetry.find(query).sort("timestamp", -1).limit(n)
    return [serialize(doc) for doc in docs]


#  alerts ---------------
"""
Recent alerts across the whole system, newest first.
Optional: ?village_id=SUTS filters to one village.
"""
@router.get("/alerts")
def list_alerts(village_id: str | None = None, limit: int = 50):

    query = {}
    if village_id is not None:
        query["village_id"] = village_id

    n = clamp_limit(limit)
    docs = state.state["db"].alerts.find(query).sort("timestamp", -1).limit(n)
    return [serialize(doc) for doc in docs]

"""Recent alerts for one village - same as /alerts?village_id=..."""

@router.get("/villages/{village_id}/alerts")
def list_village_alerts(village_id: str, limit: int = 50):
    return list_alerts(village_id=village_id, limit=limit)


# events ---------------
"""Recent lifecycle events, newest first: announces, node/master
online and offline transitions."""
@router.get("/events")
def list_events(village_id: str | None = None, limit: int = 50):

    query = {}
    if village_id is not None:
        query["village_id"] = village_id

    n = clamp_limit(limit)
    docs = state.state["db"].events.find(query).sort("timestamp", -1).limit(n)
    return [serialize(doc) for doc in docs]