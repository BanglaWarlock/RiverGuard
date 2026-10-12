@echo off
REM RiverGuard - API container standalone (debugging; compose is the
REM normal mode). Values from api/.env.docker (network service names),
REM so the compose stack must be running.

REM --- pre-flight: mongo must be running (API requires it) ---
docker ps --filter "name=riverguard-mongo" --filter "status=running" --format "{{.Names}}" | find "riverguard-mongo" >nul
if errorlevel 1 (
    echo [api] riverguard-mongo is not running - start the compose stack first.
    pause
    exit /b 1
)

REM --- already running? warn and exit ---
docker ps --filter "name=riverguard-api" --filter "status=running" --format "{{.Names}}" | find "riverguard-api" >nul
if not errorlevel 1 (
    echo [api] riverguard-api is already running. Stop it first.
    pause
    exit /b 1
)

docker build -t riverguard-api "%~dp0." || (echo [api] build failed. & pause & exit /b 1)
docker rm -f riverguard-api >nul 2>&1

docker run -d --name riverguard-api --restart unless-stopped --network riverguard-docker-network ^
    --label com.docker.compose.project=riverguard ^
    --label com.docker.compose.service=api ^
    --env-file "%~dp0.env.docker" ^
    -p 8000:8000 ^
    -v "%~dp0logs:/app/logs" ^
    riverguard-api || (echo [api] run failed. & pause & exit /b 1)

echo [api] running. http://localhost:8000