@echo off
REM RiverGuard - MongoDB containers (any mode: standalone
REM 'riverguard-mongo' or compose 'riverguard-mongo'), plus the
REM shared network state.

docker ps -a --filter "name=riverguard-mongo" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo.
docker network ls --filter "name=riverguard-docker-network" --format "network: {{.Name}}"
echo.
echo Not listed = not created. "Exited" = created but stopped.