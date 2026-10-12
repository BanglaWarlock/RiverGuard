@echo off
REM RiverGuard - start MongoDB (official image, pinned).
REM Joins the shared network (same one compose uses). The data volume
REM is REQUIRED - without it, removing the container means losing the
REM database. Alternative mode - one mode at a time (ports conflict).
REM Labeled as part of the riverguard compose project (groups in UI).

REM --- the shared network (no-op if it exists; compose creates it too) ---
docker network create riverguard-docker-network 2>nul

docker start riverguard-mongo >nul 2>&1
if not errorlevel 1 goto ok

echo [mongo] Creating the container...
docker run -d --name riverguard-mongo --restart unless-stopped ^
    --network riverguard-docker-network ^
    --label com.docker.compose.project=riverguard ^
    --label com.docker.compose.service=mongo ^
    -p 27017:27017 ^
    -v "%~dp0data:/data/db" ^
    mongo:7.0 || (echo [mongo] failed to create. & pause & exit /b 1)

:ok
echo [mongo] running. mongodb://localhost:27017 (host) / mongodb://riverguard-mongo:27017 (network)
echo [mongo] browse the data: browse_mongo.bat