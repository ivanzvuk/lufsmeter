@echo off
chcp 65001 > nul
echo Установка зависимостей для LUFSAnalyzer...
echo.

REM Установка основных зависимостей
pip install numpy scipy PyQt5 pyaudio pythonnet sounddevice zeroconf

echo.
echo Зависимости установлены успешно!
echo.
pause