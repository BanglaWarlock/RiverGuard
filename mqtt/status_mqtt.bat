@echo off
REM RiverGuard - is the broker container running?

docker ps --filter "name=eclipse" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo.
echo (if 'eclipse' is not listed above, it is stopped)
pause