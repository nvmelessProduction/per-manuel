@echo off
rem Scarica l ultima versione da GitHub e la installa (la configurazione viene mantenuta).
curl -L -o "%TEMP%\seers.zip" https://github.com/nvmelessproduction/per-manuel/archive/refs/heads/telegram-mt5-copier.zip && tar -xf "%TEMP%\seers.zip" -C "%TEMP%" && "%TEMP%\per-manuel-telegram-mt5-copier\INSTALLA.bat"
