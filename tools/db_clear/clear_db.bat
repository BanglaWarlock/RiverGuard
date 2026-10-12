@echo off
REM RiverGuard - clear the database (drops all collections).
REM Stops the parser first, restarts it after. Dev tool - Python required.

cd /d "%~dp0"
python clear_db.py
pause