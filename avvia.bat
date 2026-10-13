@echo off
cd /d "%~dp0"
title Copiatore segnali Telegram - MT5  (NON CHIUDERE)
set "PY=python"
if exist "%ProgramFiles%\Python312\python.exe" set "PY=%ProgramFiles%\Python312\python.exe"
:loop
"%PY%" bot.py
echo.
echo Il programma si e chiuso. Riavvio tra 15 secondi (chiudi questa finestra per fermarlo)...
timeout /t 15
goto loop
