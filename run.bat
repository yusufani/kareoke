@echo off
REM Run script for Karaoke Separation Studio (Windows)

REM Check if virtual environment exists
if not exist ".venv" (
    echo Virtual environment not found!
    echo Please run setup.bat first.
    pause
    exit /b 1
)

REM Activate virtual environment and run
call .venv\Scripts\activate.bat
python karaoke_app/main.py

pause
