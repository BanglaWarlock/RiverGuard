@echo off
REM RiverGuard - bring up the full compose stack.
REM Sweeps standalone-run containers first (port conflicts), then
REM builds/starts everything. First run builds images; later runs fast.

cd /d "%~dp0"

REM standalone stragglers (docker stop is a no-op on stopped containers)
docker stop ^
    riverguard-parser ^
    riverguard-api ^
    riverguard-redis ^
    riverguard-eclipse ^
    riverguard-mongo ^
    >nul 2>&1

docker compose up -d

echo [stack] running. Website: http://localhost:8000