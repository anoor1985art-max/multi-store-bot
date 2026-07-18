@echo off
chcp 65001 > nul
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File "start_bot.ps1"
exit
