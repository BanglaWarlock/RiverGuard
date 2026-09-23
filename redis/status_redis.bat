@echo off
REM RiverGuard - are the Redis containers running?

docker ps --filter "name=redis" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo.
echo (only 'redis' and 'redis-insight' matter here - if they are not listed, they are stopped)
pause