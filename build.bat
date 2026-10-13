@echo off
setlocal
cd /d "%~dp0"

set "BUILD_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%BUILD_PYTHON%" (
    echo Virtual environment not found. Run: python -m venv .venv
    pause
    exit /b 1
)

"%BUILD_PYTHON%" -m nuitka --version >nul 2>&1
if errorlevel 1 (
    echo Nuitka is not installed. Run:
    echo "%BUILD_PYTHON%" -m pip install nuitka
    pause
    exit /b 1
)

"%BUILD_PYTHON%" -m nuitka ^
    --mode=standalone ^
    --enable-plugin=tk-inter ^
    --windows-console-mode=disable ^
    --output-dir=build ^
    --output-filename=KiLibSync.exe ^
    kilibsync.py

if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo Build completed: "%~dp0build\kilibsync.dist\KiLibSync.exe"
pause
exit /b 0
