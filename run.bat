@echo off
REM Encore - Karaoke Studio - Windows launcher
cd /d "%~dp0"

if not exist ".venv" (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)

.venv\Scripts\python.exe -m karaoke_app.main %*
