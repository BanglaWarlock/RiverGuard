"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Every REST endpoint (read-only).
Adding an endpoint = one function here. main.py includes this router
BEFORE the static website mount, so these paths always win over files.

Plain 'def' (not 'async def'): these endpoints use the synchronous
pymongo driver, which blocks; FastAPI runs plain 'def' endpoints in
worker threads so blocking never freezes the event loop.

Interactive docs at /docs on the running API.
"""

from fastapi import APIRouter, HTTPException
import state
from datetime import datetime, timedelta

router = APIRouter()


def serialize(doc):
    """Make one Mongo document JSON-safe: _id becomes a string "id"."""
    if doc is None:
        return None
    result = dict(doc)
    result["id"] = str(result.pop("_id", ""))
    return result

def clamp_limit(limit, default=50, maximum=1000):
    """Keep list endpoints from being asked for a million rows."""
    if limit is None:
        return default
    return max(1, min(limit, maximum))


@router.get("/health")
def health():
    """Uptime check: service up, dependencies reachable. Never raises -
    a problem is reported, not hidden."""
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


@router.get("/stats")
def get_stats():
    """System at a glance - all values computed live from collections."""
    db = state.state["db"]
    nodes = list(db.mesh_nodes.find({}, {
        "sf": 1, "first_hop_rssi": 1, "tx_packets": 1, "rx_packets": 1,
        "last_seen": 1, "uptime_minute": 1}))
    now = datetime.utcnow()

    # liveness: seen in the last 15 minutes (matches the ~5 min
    # report cadence with margin)
    def is_recent(ts):
        return ts is not None and (now - ts).total_seconds() < 900

    rssis = [n["first_hop_rssi"] for n in nodes if n.get("first_hop_rssi") is not None]
    sfs = [n["sf"] for n in nodes if n.get("sf") is not None]

    return {
        "node_count": len(nodes),
        "nodes_recent": sum(1 for n in nodes if is_recent(n.get("last_seen"))),
        "nodes_stale": sum(1 for n in nodes if not is_recent(n.get("last_seen"))),
        "avg_rssi": round(sum(rssis) / len(rssis), 1) if rssis else None,
        "worst_rssi": min(rssis) if rssis else None,
        "avg_sf": round(sum(sfs) / len(sfs), 1) if sfs else None,
        "max_sf": max(sfs) if sfs else None,
        "blacklist_active_edges": len(
            (db.current_blacklist.find_one({"_id": "active"}) or {}).get("edges", [])),
        "reports_recent": db.route_reports.count_documents(
            {"timestamp": {"$gte": now - timedelta(minutes=15)}}),
    }


# mesh nodes

@router.get("/mesh/nodes")
def list_mesh_nodes():
    """All mesh nodes with their latest snapshot (telemetry values,
    route-derived fields, last seen). The network dashboard's list."""
    docs = state.state["db"].mesh_nodes.find().sort("node_id", 1)
    return [serialize(doc) for doc in docs]


@router.get("/mesh/nodes/{node_id}")
def get_mesh_node(node_id: str):
    """One mesh node's latest snapshot."""
    doc = state.state["db"].mesh_nodes.find_one({"node_id": node_id})
    if doc is None:
        raise HTTPException(status_code=404,
                            detail=f"Mesh node '{node_id}' not found")
    return serialize(doc)


@router.get("/mesh/nodes/{node_id}/telemetry")
def get_mesh_node_telemetry(node_id: str, limit: int = 100):
    """Telemetry history for one node, newest first. Payloads are raw
    firmware values - counters are cumulative; deltas between rows
    give rates (packet loss etc.), computed at read time."""
    n = clamp_limit(limit, default=100)
    docs = state.state["db"].telemetry.find(
        {"node_id": node_id}).sort("timestamp", -1).limit(n)
    return [serialize(doc) for doc in docs]


# mesh routes

@router.get("/mesh/routes")
def get_mesh_routes(node_id: str | None = None, since: str | None = None,
                    limit: int = 500):
    """Raw route reports, newest first - each doc is one node's complete
    routing table snapshot, stored verbatim. Filters: ?node_id= and
    ?since=<ISO timestamp>."""
    query = {}
    if node_id is not None:
        query["node_id"] = node_id
    if since is not None:
        try:
            query["timestamp"] = {"$gte": datetime.fromisoformat(since)}
        except ValueError:
            raise HTTPException(status_code=400,
                                detail="since must be an ISO timestamp")
    n = clamp_limit(limit, default=500, maximum=5000)
    docs = state.state["db"].route_reports.find(query).sort("timestamp", -1).limit(n)
    return [serialize(doc) for doc in docs]


# ---------------------------------------------------------------- blacklists

@router.get("/mesh/blacklists/current")
def get_current_blacklist():
    """The currently active link policy (the single current-state doc).
    Empty edges = nothing disabled. Returns null if none published."""
    return serialize(state.state["db"].current_blacklist.find_one(
        {"_id": "active"}))


@router.get("/mesh/blacklists")
def get_mesh_blacklists(limit: int = 50):
    """Policy version history, newest first. Each doc is one published
    version (flattened: v, sequence, edges). The active policy is
    served by /mesh/blacklists/current."""
    n = clamp_limit(limit)
    docs = state.state["db"].blacklists.find().sort("sequence", -1).limit(n)
    return [serialize(doc) for doc in docs]


@router.get("/mesh/blacklists/{sequence}")
def get_blacklist_by_sequence(sequence: int):
    """One specific policy version, by its sequence number."""
    doc = state.state["db"].blacklists.find_one({"sequence": sequence})
    if doc is None:
        raise HTTPException(status_code=404,
                            detail=f"Blacklist sequence {sequence} not found")
    return serialize(doc)