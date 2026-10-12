"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Start the program by running this file.
Creates the FastAPI app, connects to MongoDB (required) and Redis
(optional), serves the REST endpoints, the SSE stream, and the website.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

import config
import connections
import logger
import endpoints
import sse

@asynccontextmanager
async def lifespan(app):
    """Startup runs before any request; yield runs the service;
    shutdown closes connections cleanly."""
    # MongoDB is required - setup raises if it can't connect.
    # MongoDB is required - setup raises if it can't connect.
    try:
        connections.setup_database()
    except Exception as e:
        logger.log_error("lifespan", e)
        raise
    # Redis is optional - /stream returns 503 without it.
    await connections.setup_redis()

    yield

    await connections.cleanup_redis()
    connections.cleanup_database()

app = FastAPI(title="RiverGuard API", lifespan=lifespan)

# CORS: the website may be served from a different origin.
# Wide open for development - restrict via CORS_ORIGINS before production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET"],   # this service is read-only
    allow_headers=["*"],
)

# Routers FIRST (order matters): endpoints must be registered before the
# static website mount below, or "/" would swallow them.
app.include_router(endpoints.router)
app.include_router(sse.router)

# Website LAST: GET / serves web/index.html. Mounted only if the
# folder exists - a missing website must not stop the API.
if os.path.isdir(config.WEB_DIR):
    app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")

if __name__ == "__main__":
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)