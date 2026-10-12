@echo off
REM RiverGuard - start the Redis server (Docker container), standalone.
REM Joins the shared network (same one compose uses), so containerized
REM services can reach it by service name whether it was started here
REM or by compose. Also publishes localhost:6379 for python-run services.
REM Not part of the compose stack - alternative mode, one at a time.

REM --- the shared network (no-op if it exists; compose creates it too) ---
docker network create riverguard-docker-network 2>nul

docker start riverguard-redis >nul 2>&1
if not errorlevel 1 goto ok

echo [redis] Creating the container...
docker run -d --name riverguard-redis --restart unless-stopped ^
    --network riverguard-docker-network ^
    -p 6379:6379 ^
    redis:alpine || (echo [redis] failed to create. & pause & exit /b 1)

:ok
echo [redis] running. localhost:6379 (host) / redis:6379 (network)