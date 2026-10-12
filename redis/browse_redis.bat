@echo off
REM RiverGuard - temporary web UI for watching Redis pub/sub activity.
REM A TRANSIENT inspection tool: run, browse, close - the container
REM removes itself. NOT part of the compose stack. Works with whichever
REM Redis is running (standalone bat or compose) - both publish 6379.

REM --- pre-flight: some Redis must be running ---
docker ps --filter "name=redis" --filter "status=running" --format "{{.Names}}" | find "redis" >nul
if errorlevel 1 (
    echo [redis-ui] No Redis is running - start one first ^(start_redis.bat, or docker compose^).
    pause
    exit /b 1
)

REM --- remove any stale UI container from a previous run ---
docker rm -f redis-insight 2>nul

echo [redis-ui] Starting temporary Redis Insight container...

docker run -d --name redis-insight -p 5540:5540 redis/redisinsight:latest
if errorlevel 1 (
    echo [redis-ui] Failed to start the container - see docker error above.
    pause
    exit /b 1
)

REM --- wait until the UI web server answers, then open the browser ---
echo [redis-ui] Waiting for the UI to be ready...
set /a tries=0
:waitloop
timeout /t 2 /nobreak >nul
curl -s -o nul http://localhost:5540
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% lss 30 goto waitloop

echo [redis-ui] UI did not become ready - showing logs:
docker logs redis-insight
pause
exit /b 1

:ready
start http://localhost:5540

echo.
echo [redis-ui] Browser opened at http://localhost:5540
echo [redis-ui] First time: "Add Redis Database" - Host: host.docker.internal  Port: 6379
echo [redis-ui] Press any key HERE when done - the UI container will be removed.
echo.
pause >nul

echo [redis-ui] Cleaning up...
docker rm -f redis-insight
echo [redis-ui] Done - UI removed. Redis server still running.