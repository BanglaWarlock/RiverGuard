@echo off
REM RiverGuard - MQTT broker container (any mode: standalone or compose,
REM both named 'riverguard-eclipse'), plus the shared network state.

docker ps -a --filter "name=riverguard-eclipse" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo.
docker network ls --filter "name=riverguard-docker-network" --format "network: {{.Name}}"
echo.
echo Not listed = not created. "Exited" = created but stopped.