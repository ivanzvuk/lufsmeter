@echo off
chcp 65001 > nul
title Build LUFS Meter
echo.
echo ===== Building LUFS Meter (Windows) =====
echo.

REM Check Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    pause
    exit /b 1
)
python --version

REM Check pip
pip --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip not found!
    pause
    exit /b 1
)

REM Install deps
echo.
echo [1/3] Installing dependencies...
pip install --upgrade pyinstaller numpy scipy PyQt5 pyaudio pythonnet sounddevice zeroconf
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo [OK] Dependencies installed

REM Clean old builds
if exist "build" rmdir /S /Q "build"
if exist "dist" rmdir /S /Q "dist"

REM Build
echo.
echo [2/3] Building executable...
pyinstaller --name=LUFSMeter --windowed --onefile --icon=icon.ico --clean ^
    --add-binary="NAudio.dll;." ^
    --collect-all PyQt5 ^
    --collect-all scipy ^
    --collect-all sounddevice ^
    --hidden-import=scipy.signal --hidden-import=scipy.special --hidden-import=scipy.sparse ^
    --hidden-import=pyaudio --hidden-import=PyQt5 --hidden-import=clr --collect-all=clr ^
    --exclude-module=torch --exclude-module=transformers --exclude-module=tensorboard ^
    --exclude-module=pandas --exclude-module=matplotlib --exclude-module=PIL ^
    --exclude-module=torchvision --exclude-module=onnxruntime --exclude-module=sklearn ^
    --exclude-module=joblib --exclude-module=numba --exclude-module=rich ^
    lufsmeter.py

if errorlevel 1 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   DONE! File: dist\LUFSMeter.exe
echo   Copy to any Windows PC to run
echo   Requires .NET Framework (included in Windows)
echo ==========================================
echo.
pause
