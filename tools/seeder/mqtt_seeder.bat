@echo off
REM RiverGuard - seed demo data through MQTT (full pipeline test).
cd /d "%~dp0"
python seed_mqtt.py
pause