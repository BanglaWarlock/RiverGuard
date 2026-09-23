@echo off
REM RiverGuard - stop Redis and Redis Insight containers.

echo [redis] Stopping Redis...
docker stop redis

echo [redis] Stopping Redis Insight...
docker stop redis-insight

echo.
echo [redis] Both stopped.
pause