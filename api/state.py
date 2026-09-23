"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Shared runtime state - variables that are shared between files.

  "db":     pymongo database handle (REST endpoints)
  "redis":  async redis client (SSE endpoint only; None = /stream 503s)
  "mongo":  the MongoClient (kept so cleanup can close it)
"""

state = {
    "db": None,
    "redis": None,
    "mongo": None,
}