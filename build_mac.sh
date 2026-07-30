#!/bin/bash
# Скрипт сборки macOS .app бандла
#
# Использование:
#   chmod +x build_mac.sh
#   ./build_mac.sh
#
# Требования:
#   - macOS
#   - Homebrew (https://brew.sh)
#   - Python 3.8+

set -e

echo "=== LUFS Meter - macOS Build Script ==="
echo ""

# 1. Проверка macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo "Ошибка: этот скрипт предназначен только для macOS"
    exit 1
fi

# 2. Установка зависимостей системы
echo "[1/5] Установка системных зависимостей..."
if ! command -v brew &> /dev/null; then
    echo "Homebrew не найден. Установите: https://brew.sh"
    exit 1
fi

brew install portaudio ffmpeg || true

# 3. Создание виртуального окружения
echo "[2/5] Настройка виртуального окружения..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 4. Установка Python зависимостей
echo "[3/5] Установка Python зависимостей..."
pip install --upgrade pip
pip install numpy PyQt5 scipy sounddevice py2app

# 5. Создание иконки
echo "[4/5] Создание иконки..."
python create_icon_mac.py

# 6. Сборка .app бандла
echo "[5/5] Сборка .app бандла..."
python setup.py py2app

echo ""
echo "=== Готово! ==="
echo "Приложение собрано: dist/LUFS Meter.app"
echo ""
echo "Для запуска: open dist/LUFS Meter.app"
echo ""
echo "Примечание:"
echo "- Для захвата системного аудио установите BlackHole:"
echo "    brew install blackhole-2ch"
echo "- Затем в Audio MIDI Setup создайте Multi-Output устройство"
