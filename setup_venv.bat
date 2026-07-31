@echo off
REM Baut die virtuelle Umgebung fuer claude_rpc.
REM Wichtig: NICHT das Microsoft-Store-Python verwenden - dort ist %APPDATA%
REM umgeleitet und die Reader fuer %APPDATA%\Claude sehen nichts.
setlocal
set BASE=%~dp0
set PY=%APPDATA%\uv\python\cpython-3.13.14-windows-x86_64-none\python.exe
if not exist "%PY%" (
  echo Kein geeignetes Python gefunden: %PY%
  exit /b 1
)
if not exist "%BASE%config.json" (
  echo config.json fehlt - erstelle sie aus config.example.json
  copy /y "%BASE%config.example.json" "%BASE%config.json" >nul
)
"%PY%" -m venv "%BASE%.venv" || exit /b 1
"%BASE%.venv\Scripts\python.exe" -m pip install --upgrade pip
"%BASE%.venv\Scripts\python.exe" -m pip install -r "%BASE%requirements.txt"
REM Umbenannte Kopie, damit der Dienst im Task-Manager erkennbar ist.
copy /y "%BASE%.venv\Scripts\pythonw.exe" "%BASE%.venv\Scripts\ClaudeDiscordPresence.exe" >nul
"%BASE%.venv\Scripts\python.exe" "%BASE%_check_env.py"
endlocal
