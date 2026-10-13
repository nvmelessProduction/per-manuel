@echo off
rem Scarica l ultima versione da GitHub e la installa (la configurazione viene mantenuta).
powershell -NoProfile -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/nvmelessproduction/per-manuel/telegram-mt5-copier/get.ps1 | iex"
