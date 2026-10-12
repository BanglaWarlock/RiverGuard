@echo off
REM RiverGuard - daily report task, run by Task Scheduler.
REM Program: cmd.exe  Arguments: /c "%~dp0reporter_oneshot.bat"
REM Config: reporter/.env.docker (gitignored). Rebuilds the image so
REM code changes are picked up, then runs one-shot (--rm self-cleans).

docker ps --filter "name=riverguard-mongo" --filter "status=running" --format "{{.Names}}" | find "riverguard-mongo" >nul
if errorlevel 1 (
    echo [reporter] riverguard-mongo is not running - compose stack down?
    exit /b 1
)

docker build -t riverguard-reporter "%~dp0."
docker run --rm ^
    --env-file "%~dp0.env.docker" ^
    -v "%~dp0state:/app/state" ^
    riverguard-reporter