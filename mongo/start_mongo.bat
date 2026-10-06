@echo off
REM RiverGuard - start the local MongoDB (official image, pinned).
REM The data volume is REQUIRED - without it, removing the container
REM means losing the database.

echo [mongo] Starting MongoDB...

docker start riverguard-mongo 2>nul
if errorlevel 1 (
    echo [mongo] Container not found - creating it...
    docker run -d --name riverguard-mongo ^
        -p 27017:27017 ^
        -v "%~dp0data:/data/db" ^
        mongo:7.0
)

echo.
echo [mongo] MongoDB      : mongodb://localhost:27017
echo [mongo] (optional UI): docker run -d --name mongo-express -p 8081:8081 -e ME_CONFIG_MONGODB_SERVER=host.docker.internal mongo-express
echo.
pause