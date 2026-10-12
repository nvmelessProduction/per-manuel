@echo off
cd /d "%~dp0"
title Copier Telegram - MT5
:loop
python bot.py
echo.
echo Il programma si e chiuso. Riavvio tra 15 secondi (chiudi questa finestra per fermarlo)...
timeout /t 15
goto loop
