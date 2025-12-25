@echo off
setlocal enabledelayedexpansion

echo ====================================
echo Karaoke Separation Studio - Setup
echo ====================================
echo.

REM Check if UV is installed
uv --version >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo UV is not installed!
    echo Installing UV automatically...
    echo.
    powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

    if !ERRORLEVEL! NEQ 0 (
        echo Failed to install UV!
        echo Please install manually: https://github.com/astral-sh/uv
        pause
        exit /b 1
    )

    echo UV installed! Please close this terminal and run setup.bat again.
    pause
    exit /b 0
)

echo UV found:
uv --version
echo.

REM Ask GPU support
echo Do you have an NVIDIA GPU?
echo GPU makes separation 5-10x faster
echo.
choice /C YN /M "Use GPU version with CUDA 12.8"

set USE_GPU=0
if !ERRORLEVEL! EQU 1 set USE_GPU=1

echo.

REM Create virtual environment
if not exist ".venv" (
    echo Creating virtual environment...
    uv venv
) else (
    echo Virtual environment exists.
)

echo.
echo Installing dependencies...
echo.

REM Install dependencies
if !USE_GPU! EQU 1 (
    echo Installing GPU version with CUDA 12.8...
    uv pip install -r requirements-gpu.txt
) else (
    echo Installing CPU-only version...
    uv pip install -r requirements.txt
)

if !ERRORLEVEL! NEQ 0 (
    echo.
    echo Installation failed!
    pause
    exit /b 1
)

echo.
echo ====================================
echo Setup completed!
echo ====================================
echo.
echo To run: run.bat
echo To build EXE: build.bat
echo.
pause
