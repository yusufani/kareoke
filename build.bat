@echo off
REM Build script for Karaoke Separation Studio (Windows)

echo ====================================
echo Karaoke Separation Studio - Build
echo ====================================
echo.

REM Check if virtual environment exists
if not exist ".venv" (
    echo Virtual environment not found!
    echo Please run setup.bat first.
    pause
    exit /b 1
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Clean previous builds
echo Cleaning previous builds...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

REM Run PyInstaller
echo.
echo Building executable...
echo This may take several minutes...
echo.

pyinstaller karaoke_app.spec

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Build failed!
    pause
    exit /b 1
)

echo.
echo ====================================
echo Build completed successfully!
echo ====================================
echo.
echo Executable location: dist\KaraokeSeparationStudio\
echo To run: dist\KaraokeSeparationStudio\KaraokeSeparationStudio.exe
echo.
pause
