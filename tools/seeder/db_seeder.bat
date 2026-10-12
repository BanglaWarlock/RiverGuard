@echo off
REM RiverGuard - seed demo data DIRECTLY into the database (fast,
REM no broker/parser needed). Use clear_db.bat first for clean state.
cd /d "%~dp0"
python seed_db.py --days 5
pause