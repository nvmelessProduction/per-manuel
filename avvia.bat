@echo off
cd /d "%~dp0"
title Copiatore segnali Telegram - MT5  (NON CHIUDERE)
set "PY=%~dp0venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
:loop
"%PY%" "%~dp0bot.py"
echo.
echo Il programma si e chiuso. Riavvio tra 15 secondi (chiudi questa finestra per fermarlo)...
timeout /t 15
goto loop
