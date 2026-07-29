@echo off
chcp 65001 > nul
echo Создание ярлыка на рабочем столе...
echo.

set TARGET=%~dp0dist\LUFSAnalyzer.exe
set SHORTCUT=%USERPROFILE%\Desktop\LUFSAnalyzer.lnk
set ICON=%~dp0icon.ico

REM Создаем VBS скрипт для создания ярлыка
echo Set oWS = WScript.CreateObject("WScript.Shell") > create_shortcut.vbs
echo sLinkFile = "%SHORTCUT%" >> create_shortcut.vbs
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> create_shortcut.vbs
echo oLink.TargetPath = "%TARGET%" >> create_shortcut.vbs
echo oLink.WorkingDirectory = "%~dp0dist" >> create_shortcut.vbs
echo oLink.Description = "Анализатор громкости R128 EBU" >> create_shortcut.vbs
echo oLink.IconLocation = "%ICON%, 0" >> create_shortcut.vbs
echo oLink.Save >> create_shortcut.vbs

cscript //nologo create_shortcut.vbs
del create_shortcut.vbs

echo Ярлык создан на рабочем столе!
echo.
pause