"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Start the program by running this file.

Creates the FastAPI app, connects to MongoDB (required) and Redis
(optional) at startup, serves the REST endpoints, the SSE stream.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

import config
import connections
import endpoints
import sse

"""
Runs once on startup (before any request is served), pauses at 'yield'
while the service runs, then runs the shutdown part.
"""
@asynccontextmanager
async def lifespan(app):

    try:
        # MongoDB is required - setup raises if it can't connect.
        await connections.setup_database()
        # Redis is optional - the API runs, /stream returns 503.
        await connections.setup_redis()
    except Exception as e:
        raise RuntimeError(f"Cannot start API without MongoDB: {e}")

    yield  # <-- the service runs while paused here

    # --- shutdown: close both connections cleanly ---
    await connections.cleanup_redis()
    connections.cleanup_database()
    print("[API] Shut down cleanly")


app = FastAPI(title="RiverGuard API", lifespan=lifespan)

# CORS: the website may be served from a different origin (e.g. Vercel),
# and browsers block cross-origin requests unless allowed here.
# Wide open for development - restrict to the real site's origin before
# production (CORS_ORIGINS in .env).
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET"],   # this service is read-only
    allow_headers=["*"],
)

# Routers FIRST (order matters): the endpoints must be registered
# before the static website mount below, or "/" would swallow them.
app.include_router(endpoints.router)
app.include_router(sse.router)

# Website LAST: GET / serves web/index.html (plus /app.js, /style.css).
# Mounted only if the folder exists - a missing website must not stop
# the REST API from running.
if os.path.isdir(config.WEB_DIR):
    app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
else:
    print(f"[web] {config.WEB_DIR} not found - API running without the website")


if __name__ == "__main__":
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)