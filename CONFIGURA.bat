@echo off
rem Rifa la configurazione (token, canale, conto MT5, rischio) e riavvia il programma.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Reconfigure
