@echo off

REM standalone stragglers (docker stop is a no-op on stopped containers)
docker stop riverguard-parser riverguard-api riverguard-redis riverguard-eclipse riverguard-mongo >nul 2>&1


REM RiverGuard - bring up the full stack (all services, one network).
REM First run builds the images; later runs are instant.

cd /d "%~dp0"
docker compose up -d