@echo off
setlocal enabledelayedexpansion

echo ====================================
echo  Encore - Karaoke Studio - Setup
echo ====================================
echo.

REM --- uv ---------------------------------------------------------------
uv --version >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo uv is not installed. Installing it now...
    powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    if !ERRORLEVEL! NEQ 0 (
        echo Failed to install uv. Install it manually:
        echo   https://github.com/astral-sh/uv
        pause
        exit /b 1
    )
    echo.
    echo uv installed. Close this window, open a new one, and run setup.bat again.
    pause
    exit /b 0
)

echo uv found:
uv --version
echo.

REM --- ffmpeg -----------------------------------------------------------
ffmpeg -version >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo WARNING: ffmpeg was not found on your PATH.
    echo          Downloads cannot be decoded without it.
    echo          Install it with:  winget install Gyan.FFmpeg
    echo.
)

REM --- GPU ---------------------------------------------------------------
echo Do you have an NVIDIA GPU? It makes separation several times faster.
choice /C YN /M "Install the CUDA build"
set USE_GPU=0
if !ERRORLEVEL! EQU 1 set USE_GPU=1
echo.

REM --- environment -------------------------------------------------------
echo Creating virtual environment (Python 3.11)...
uv python install 3.11
if not exist ".venv" (
    uv venv --python 3.11
) else (
    echo Virtual environment already exists.
)

echo.
echo Installing dependencies...
if !USE_GPU! EQU 1 (
    uv pip install -r requirements-gpu.txt
) else (
    uv pip install -r requirements.txt
)

if !ERRORLEVEL! NEQ 0 (
    echo.
    echo Installation failed.
    pause
    exit /b 1
)

echo.
echo ====================================
echo  Done.
echo ====================================
echo.
echo   Start Encore with:  run.bat
echo   Build an exe with:  build.bat
echo.
pause
