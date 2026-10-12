@echo off
REM RiverGuard - update to the latest version and restart the stack.
REM Downloads the repository zip (no git needed), extracts over the
REM current files (local .env.docker files and data folders survive -
REM they are not in the zip), rebuilds images, restarts the stack.
REM The running stack is NOT stopped until the new code is fully
REM downloaded and verified - any earlier failure leaves the old
REM stack running untouched.
REM Change UPDATE_URL below when handing the project over.

set UPDATE_URL=https://github.com/BanglaWarlock/RiverGuard/archive/refs/heads/main.zip

cd /d "%~dp0"

echo [update] checking connection...
curl -s -o nul --max-time 10 -I "%UPDATE_URL%" || (
    echo [update] no internet connection - stack left running, nothing changed.
    pause
    exit /b 1
)

echo [update] downloading latest...
curl -L -o update.zip "%UPDATE_URL%" || (
    echo [update] download failed - stack left running, nothing changed.
    del update.zip 2>nul
    pause
    exit /b 1
)

echo [update] extracting... (verifies the download is intact)
tar -xf update.zip || (
    echo [update] extraction failed - download was corrupt or interrupted.
    echo [update] stack left running, nothing changed.
    del update.zip 2>nul
    rmdir "RiverGuard-main" 2>nul
    pause
    exit /b 1
)

echo [update] installing new files... (local configs and data are kept)
robocopy "RiverGuard-main" . /E /MOVE /NFL /NDL /NJH /NJS

del update.zip
rmdir "RiverGuard-main" 2>nul

echo [update] stopping the stack and rebuilding...
call z_stop_compose.bat

echo [update] restarting the stack with new code...
call z_start_compose.bat

echo [update] done. Website: http://localhost:8000