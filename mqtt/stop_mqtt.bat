@echo off
REM RiverGuard - stop the Eclipse Mosquitto broker container.

echo [mqtt] Stopping broker...
docker stop eclipse
echo.
echo [mqtt] Stopped.
pause