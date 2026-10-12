@echo off
REM RiverGuard - start the MQTT broker (Eclipse Mosquitto), standalone.
REM Joins the shared network (same one compose uses), so containerized
REM services reach it as 'riverguard-eclipse' whether started here or
REM by compose. Also publishes localhost:1883 for python-run services
REM and ESP32s. Not part of the compose stack - alternative mode.

REM --- the shared network (no-op if it exists; compose creates it too) ---
docker network create riverguard-docker-network 2>nul

docker start riverguard-eclipse >nul 2>&1
if not errorlevel 1 goto ok

echo [mqtt] Creating the container...
docker run -d --name riverguard-eclipse --restart unless-stopped ^
    --network riverguard-docker-network ^
    -p 1883:1883 ^
    -v "%~dp0conf:/mosquitto/config" ^
    -v "%~dp0data:/mosquitto/data" ^
    -v "%~dp0log:/mosquitto/log" ^
    eclipse-mosquitto:latest || (echo [mqtt] failed to create. & pause & exit /b 1)

:ok
echo [mqtt] running. localhost:1883 (host) / riverguard-eclipse:1883 (network)