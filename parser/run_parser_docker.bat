@echo off
REM RiverGuard - parser container standalone (debugging; compose is the
REM normal mode). Values from .env.docker (compose service names), so the
REM compose stack must be running and the container joins its network.

docker network create riverguard-docker-network 2>nul

REM --- pre-flight: mongo must be running (parser requires it) ---
docker ps --filter "name=riverguard-mongo" --filter "status=running" --format "{{.Names}}" | find "riverguard-mongo" >nul
if errorlevel 1 (
    echo [parser] riverguard-mongo is not running - start the compose stack first.
    pause
    exit /b 1
)

REM --- already running? warn and exit ---
docker ps --filter "name=riverguard-parser" --filter "status=running" --format "{{.Names}}" | find "riverguard-parser" >nul
if not errorlevel 1 (
    echo [parser] riverguard-parser is already running. Stop it first.
    pause
    exit /b 1
)

docker build -t riverguard-parser "%~dp0." || (echo [parser] build failed. & pause & exit /b 1)
docker rm -f riverguard-parser >nul 2>&1

docker run -d --name riverguard-parser --restart unless-stopped --network riverguard-docker-network ^
    --label com.docker.compose.project=riverguard ^
    --label com.docker.compose.service=parser ^
    --env-file "%~dp0.env.docker" ^
    -v "%~dp0logs:/app/logs" ^
    riverguard-parser || (echo [parser] run failed. & pause & exit /b 1)

echo [parser] running. Logs: docker logs -f riverguard-parser