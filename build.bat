@echo off
setlocal enabledelayedexpansion
REM Build a self-contained Encore with PyInstaller. See PACKAGING.md.

echo ====================================
echo  Encore - Karaoke Studio - Build
echo ====================================
echo.

if not exist ".venv" (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

echo Cleaning previous builds...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo Building...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean encore.spec

if !ERRORLEVEL! NEQ 0 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo ====================================
echo  Done: dist\Encore\Encore.exe
echo ====================================
echo.
echo Note: ffmpeg is NOT bundled - it must be on the PATH of whoever runs it.
echo       The separation model downloads once, on first use.
echo.
pause
