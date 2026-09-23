@echo off
REM RiverGuard - start Redis and Redis Insight.
REM Pattern: start the container if it exists; create it (pulling the
REM image if needed) only when it doesn't. Works on a fresh machine AND
REM on a machine where the containers already exist - same command.

echo [redis] Starting Redis...

docker start redis 2>nul
if errorlevel 1 (
    echo [redis] Container not found - creating it (pulls image if needed)...
    docker run -d --name redis -p 6379:6379 redis:alpine
)

echo [redis] Starting Redis Insight...

docker start redis-insight 2>nul
if errorlevel 1 (
    echo [redis-insight] Container not found - creating it (pulls image if needed)...
    docker run -d --name redis-insight -p 5540:5540 redis/redisinsight:latest
)

echo.
echo [redis] Redis         : localhost:6379
echo [redis] Redis Insight : http://localhost:5540
echo.
pause