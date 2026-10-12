@echo off
REM RiverGuard - Redis containers (any mode: standalone 'redis' or
REM compose 'riverguard-redis'), plus the shared network state.

docker ps -a --filter "name=redis" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo.
docker network ls --filter "name=riverguard-docker-network" --format "network: {{.Name}}"
echo.
echo Not listed = not created. "Exited" = created but stopped.