@echo off
REM Doppelklick-Starter. Beende vorher Claude Desktop komplett,
REM auch das Symbol im Infobereich neben der Uhr.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0remove_extension.ps1"
