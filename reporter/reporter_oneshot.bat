@echo off
REM RiverGuard - daily report task, run by Task Scheduler.
REM Program: cmd.exe  Arguments: /c "C:\...\RiverGuard\reporter\reporter_oneshot.bat"
REM Config: reporter/.env.docker (gitignored). Rebuilds the image so
REM code changes are picked up, then runs one-shot (--rm self-cleans).
REM
REM Exit codes (Task Scheduler "Last Run Result"):
REM   0 = ran clean (report sent, or no full window yet - nothing to do)
REM   1 = could not run (database down, or image build failed)
REM   2 = ran but could not deliver (SMTP/internet down - state held,
REM       retried automatically next scheduled run)
REM
REM Task Scheduler runs headless: all output appends to
REM reporter/reporter_task.log - check there when a run misbehaves.

cd /d "%~dp0"

set LOG=%~dp0reporter_task.log
echo ===== %date% %time% ===== >> "%LOG%"

docker ps --filter "name=riverguard-mongo" --filter "status=running" --format "{{.Names}}" | find "riverguard-mongo" >nul
if errorlevel 1 (
    echo [reporter] riverguard-mongo is not running - compose stack down? >> "%LOG%"
    exit /b 1
)

docker build -t riverguard-reporter . >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [reporter] image build FAILED - stale image not run, nothing sent. >> "%LOG%"
    exit /b 1
)

docker run --rm ^
    --env-file "%~dp0.env.docker" ^
    -v "%~dp0state:/app/state" ^
    riverguard-reporter >> "%LOG%" 2>&1

exit /b %errorlevel%