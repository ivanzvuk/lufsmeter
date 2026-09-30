@echo off
chcp 65001 > nul
echo Запуск LUFSAnalyzer...
echo.

REM Проверяем существует ли EXE файл
if exist "dist\LUFSAnalyzer.exe" (
    dist\LUFSAnalyzer.exe
) else (
    echo EXE файл не найден. Запускаем Python скрипт...
    python lufsmeter.py
)

pause