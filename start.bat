@echo off
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" kilibsync.py
) else (
    python kilibsync.py
)
if errorlevel 1 pause
