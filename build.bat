@echo off
chcp 65001 > nul
title Build lufsmeter_v11
echo.
echo ===== Building Анализатор громкости R128 EBU v11 =====
echo.
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
pip install --upgrade pyinstaller numpy scipy PyQt5 pyaudio pythonnet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo [OK] Dependencies installed

REM Clean old builds
if exist "lufsmeter_v11.spec" del "lufsmeter_v11.spec"
if exist "dist\lufsmeter_v11.exe" del "dist\lufsmeter_v11.exe"

REM Build
echo.
echo [2/3] Building executable...
echo.

pyinstaller --name=lufsmeter_v11 --windowed --onefile --icon=icon.ico --clean --add-binary="NAudio.dll;." --hidden-import=scipy.signal --hidden-import=scipy.special --hidden-import=scipy.sparse --hidden-import=pyaudio --hidden-import=PyQt5 --hidden-import=clr --collect-all=clr --exclude-module=torch --exclude-module=transformers --exclude-module=tensorboard --exclude-module=pandas --exclude-module=matplotlib --exclude-module=PIL --exclude-module=torchvision --exclude-module=torchaudio --exclude-module=onnxruntime --exclude-module=sklearn --exclude-module=joblib --exclude-module=openpyxl --exclude-module=pygame --exclude-module=numba --exclude-module=llvmlite --exclude-module=rich --exclude-module=tokenizers --exclude-module=anyio --exclude-module=pydantic --exclude-module=regex --exclude-module=safetensors --exclude-module=fsspec --exclude-module=urllib3 --exclude-module=charset_normalizer --exclude-module=certifi lufsmeter.py

if errorlevel 1 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo [3/3] Copying NAudio.dll to dist...
if exist "dist\lufsmeter_v11.exe" (
    copy /Y "NAudio.dll" "dist\NAudio.dll" > nul
    echo [OK] NAudio.dll copied to dist\
)

echo.
echo ==========================================
echo   DONE! File: dist\lufsmeter_v11.exe
echo   Copy dist folder to any Windows PC
echo   Requires .NET Framework (included in Windows)
echo ==========================================
echo.
pause
