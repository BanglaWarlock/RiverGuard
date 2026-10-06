@echo off
REM RiverGuard - start the local MQTT broker (Eclipse Mosquitto in Docker).
REM Idempotent: already-running containers are skipped; missing ones
REM are created (pulling the image if needed).

REM echo [mqtt] Starting Eclipse broker...

docker start riverguard-eclipse 2>nul
if errorlevel 1 (
    @REM  echo [mqtt] Container not found - creating it...
    docker run -d --name riverguard-eclipse ^
        -p 1883:1883 ^
        -v "%~dp0conf:/mosquitto/config" ^
        -v "%~dp0data:/mosquitto/data" ^
        -v "%~dp0log:/mosquitto/log" ^
        eclipse-mosquitto:latest
)

REM echo.
REM echo [mqtt] MQTT broker   : localhost:1883
REM echo.
REM pause