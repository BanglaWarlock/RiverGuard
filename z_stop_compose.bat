@echo off
REM RiverGuard - stop the stack. Stops compose-managed services, then
REM any standalone-run service containers (bat-launched parser/api/
REM infra are not compose-managed and would otherwise keep running).

cd /d "%~dp0"
docker compose stop

REM standalone stragglers (docker stop is a no-op on stopped containers)
docker stop riverguard-parser riverguard-api riverguard-redis riverguard-eclipse riverguard-mongo >nul 2>&1

echo [stack] stopped.