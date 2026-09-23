"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

The SSE (Server-Sent Events) stream: how live updates reach the website.

How REST and SSE work together:
  REST, called on page load, display current info in db.
  SSE, pushed continuously, dynamically sends update.

The stream forwards everything the parser publishes to Redis:
  1. Every browser that opens /stream gets its OWN Redis subscription
     (PSUBSCRIBE riverguard:*).
  2. Each Redis message becomes one SSE event.
  
  linked at http://localhost:8000/stream, replace port with your API host/port if different.
"""

import json
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

import config
import state

router = APIRouter()

"""Live feed of everything the parser publishes to Redis."""
@router.get("/stream")
async def stream(request: Request):
    if state.state["redis"] is None:
        raise HTTPException(
            status_code=503,
            detail="Redis not connected - live stream unavailable",
        )

    return StreamingResponse(
        event_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",    # never cache a live stream
            "X-Accel-Buffering": "no",     # tell nginx not to buffer, if proxied
        },
    )

"""
Yields SSE events forever. One generator runs per connected browser.

When the browser disconnects, Starlette cancels this generator, which
lands in the finally-block below - so the Redis subscription is always
cleaned up and connections never leak.
"""
async def event_generator(request):
    pubsub = state.state["redis"].pubsub()
    await pubsub.psubscribe("riverguard:*")

    last_keepalive = time.monotonic()

    try:
        while True:
            # Wait up to 1 second for the next Redis message
            # (returns None if nothing arrived in that second).
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )

            if message is not None and message["type"] == "pmessage":
                # Redis delivers channel name and payload as bytes
                raw = message["data"]
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")

                try:
                    envelope = json.loads(raw)
                except json.JSONDecodeError:
                    continue   # not valid JSON - not ours, skip silently

                # Tag which channel this came from:
                # "riverguard:water" -> "water". The website switches on it.
                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()
                envelope["channel"] = channel.split(":", 1)[-1]

                # An SSE event: a "data:" line plus a blank line.
                yield f"data: {json.dumps(envelope)}\n\n"
                last_keepalive = time.monotonic()

            elif time.monotonic() - last_keepalive >= config.KEEPALIVE_SECONDS:
                # Nothing happened for a while: send an SSE comment line.
                # Browsers ignore it, but it keeps proxies from cutting the
                # connection for being idle.
                yield ": keepalive\n\n"
                last_keepalive = time.monotonic()
                
            if await request.is_disconnected():
                print("[stream] client disconnected - closing stream")
                return

    finally:
        await pubsub.aclose()