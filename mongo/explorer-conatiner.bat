@echo off
REM RiverGuard - temporary web UI for the local database (mongo-express).
REM A TRANSIENT inspection tool: run, browse, close - the container
REM removes itself. NOT part of the compose stack (which is for the
REM always-on services). Connects through the host port mapping, so
REM it works no matter how the database container is networked.

REM --- pre-flight: the database must be running ---
docker ps --filter "name=riverguard-mongo" --filter "status=running" --format "{{.Names}}" | find "riverguard-mongo" >nul
if errorlevel 1 (
    echo [mongo-ui] riverguard-mongo is not running - start it first.
    pause
    exit /b 1
)

REM --- remove any stale UI container from a previous run ---
docker rm -f mongo-ui 2>nul

echo [mongo-ui] Starting temporary mongo-express container...

docker run -d --name mongo-ui -p 8081:8081 ^
    -e ME_CONFIG_MONGODB_SERVER=host.docker.internal ^
    mongo-express

REM --- wait until the UI says it is listening, then open the browser ---
echo [mongo-ui] Waiting for the UI to be ready...
set /a tries=0
:waitloop
timeout /t 2 /nobreak >nul
docker logs mongo-ui 2>&1 | find "listening at" >nul
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% lss 30 goto waitloop
echo [mongo-ui] UI did not become ready - showing logs, then giving up:
docker logs mongo-ui
pause
exit /b 1

:ready
start http://localhost:8081

echo.
echo [mongo-ui] Browser opened at http://localhost:8081
echo [mongo-ui] Browse the database, then press any key HERE when done -
echo [mongo-ui] the UI container will be stopped and removed.
echo.
pause >nul

echo [mongo-ui] Cleaning up...
docker rm -f mongo-ui
echo [mongo-ui] Done - UI removed. Database still running.
pause