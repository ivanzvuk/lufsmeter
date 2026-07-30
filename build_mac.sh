#!/bin/bash
# Сборка macOS .app бандла через PyInstaller (поддержка Apple Silicon)
#
# Использование:
#   chmod +x build_mac.sh
#   ./build_mac.sh
#
# Требования:
#   - macOS 11+
#   - Homebrew (https://brew.sh)
#   - Python 3.8+ (arm64 для нативной сборки на M1/M2/M3)

set -e

echo "=== LUFS Meter — macOS Build (PyInstaller) ==="
echo ""

if [[ "$(uname)" != "Darwin" ]]; then
    echo "Ошибка: этот скрипт предназначен только для macOS"
    exit 1
fi

ARCH=$(uname -m)
echo "Architecture: $ARCH"

# 1. Системные зависимости
echo "[1/5] Установка system dependencies..."
if ! command -v brew &> /dev/null; then
    echo "Homebrew не найден. Установите: https://brew.sh"
    exit 1
fi
brew install portaudio ffmpeg || true

# 2. Виртуальное окружение
echo "[2/5] Настройка virtualenv..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 3. Python зависимости
echo "[3/5] Установка Python-зависимостей..."
pip install --upgrade pip
pip install pyinstaller numpy scipy PyQt5 sounddevice zeroconf Pillow

# 4. Иконка (.icns)
echo "[4/5] Создание иконки..."
python create_icon_mac.py

# 5. Сборка PyInstaller
echo "[5/5] Сборка .app бандла через PyInstaller..."

# Удаляем старую сборку
rm -rf build dist __pycache__ *.spec

pyinstaller --windowed --onedir --clean \
    --name "LUFS Meter" \
    --icon icon.icns \
    --osx-bundle-identifier com.lufsmeter.app \
    --target-arch "$ARCH" \
    --collect-all PyQt5 \
    --collect-all scipy \
    --collect-all numpy \
    --collect-all sounddevice \
    --hidden-import scipy.signal \
    --hidden-import scipy.special \
    --hidden-import scipy.sparse \
    --hidden-import scipy.fft \
    --hidden-import scipy.linalg \
    --hidden-import scipy.optimize \
    --hidden-import scipy._lib \
    --hidden-import sounddevice \
    --hidden-import zeroconf \
    --exclude-module tkinter \
    --exclude-module matplotlib \
    --exclude-module PIL \
    --exclude-module pandas \
    --exclude-module cv2 \
    lufsmeter.py

# Создаём DMG
echo ""
echo "Создание DMG..."
hdiutil create -volname "LUFS Meter" \
    -srcfolder "dist/LUFS Meter.app" \
    -ov -format UDZO \
    "dist/LUFSMeter.dmg"

echo ""
echo "=== Готово! ==="
echo "  .app: dist/LUFS Meter.app"
echo "  .dmg: dist/LUFSMeter.dmg"
echo ""
echo "Для захвата системного аудио установите BlackHole:"
echo "  brew install blackhole-2ch"
