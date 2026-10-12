@echo off
REM RiverGuard - temporary web UI for the database (mongo-express).
REM A TRANSIENT inspection tool: run, browse, close - the container
REM removes itself. NOT part of the compose stack.
REM The --add-host line maps the name "mongo" (hardcoded by
REM mongo-express's startup pre-check) to the host machine, so the
REM pre-check connects on attempt 1 instead of retrying ~60 seconds.

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
    --add-host "mongo:host-gateway" ^
    -e ME_CONFIG_MONGODB_SERVER=host.docker.internal ^
    -e ME_CONFIG_BASICAUTH_USERNAME=admin ^
    -e ME_CONFIG_BASICAUTH_PASSWORD=pass ^
    mongo-express
if errorlevel 1 (
    echo [mongo-ui] Failed to start the container - see docker error above.
    pause
    exit /b 1
)

echo [mongo-ui] Waiting for the UI to be ready...
set /a tries=0
:waitloop
timeout /t 2 /nobreak >nul
docker logs mongo-ui 2>&1 | find "listening at" >nul
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% lss 45 goto waitloop

echo [mongo-ui] UI did not become ready - showing logs:
docker logs mongo-ui
pause
exit /b 1

:ready
start http://localhost:8081

echo.
echo [mongo-ui] Browser opened at http://localhost:8080
echo [mongo-ui] Login: admin / pass
echo [mongo-ui] Browse the database, then press any key HERE when done -
echo [mongo-ui] the UI container will be removed.
echo.
pause >nul

echo [mongo-ui] Cleaning up...
docker rm -f mongo-ui
echo [mongo-ui] Done - UI removed. Database still running.