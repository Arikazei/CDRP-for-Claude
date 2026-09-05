@echo off
REM Baut die virtuelle Umgebung fuer claude_rpc.
REM
REM Wichtig: NICHT das Microsoft-Store-Python verwenden. Dort sind %APPDATA%
REM und %LOCALAPPDATA% umgeleitet: die Leser fuer %APPDATA%\Claude sehen
REM nichts, und der Datenordner laege an einer Stelle, die sonst niemand
REM liest. Gesucht wird deshalb in dieser Reihenfolge, die Store-Fassung
REM wird uebersprungen:
REM
REM   1. der Pfad aus dem Aufruf:  setup_venv.bat C:\Pfad\zu\python.exe
REM   2. der py-Launcher von python.org
REM   3. ein python.exe im PATH
REM   4. von uv verwaltete Fassungen
setlocal enabledelayedexpansion
set BASE=%~dp0
set PY=

if not "%~1"=="" call :pruefe "%~1"
if "!PY!"=="" for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do if "!PY!"=="" call :pruefe "%%i"
if "!PY!"=="" for /f "delims=" %%i in ('where python.exe 2^>nul') do if "!PY!"=="" call :pruefe "%%i"
if "!PY!"=="" for /d %%d in ("%APPDATA%\uv\python\cpython-3*") do if "!PY!"=="" call :pruefe "%%d\python.exe"

if "!PY!"=="" (
  echo Kein geeignetes Python gefunden. Python von python.org installieren
  echo oder den Pfad angeben:  setup_venv.bat C:\Pfad\zu\python.exe
  exit /b 1
)
echo Python: !PY!

if not exist "%BASE%config.json" (
  echo config.json fehlt - erstelle sie aus config.example.json
  copy /y "%BASE%config.example.json" "%BASE%config.json" >nul
)
"!PY!" -m venv "%BASE%.venv" || exit /b 1
"%BASE%.venv\Scripts\python.exe" -m pip install --upgrade pip
"%BASE%.venv\Scripts\python.exe" -m pip install -r "%BASE%requirements.txt"
REM Umbenannte Kopie, damit der Dienst im Task-Manager erkennbar ist.
copy /y "%BASE%.venv\Scripts\pythonw.exe" "%BASE%.venv\Scripts\ClaudeDiscordPresence.exe" >nul
"%BASE%.venv\Scripts\python.exe" "%BASE%_check_env.py"
endlocal
exit /b 0

:pruefe
REM Store-Fassung ueberspringen, die erste andere nehmen. Der Vergleich
REM laeuft ueber Stringersetzung statt ueber find.exe: in einer Shell mit
REM Unix-Werkzeugen im PATH ist "find" ein anderes Programm.
if not exist "%~1" exit /b 0
set "KANDIDAT=%~1"
if /i not "!KANDIDAT:\WindowsApps\=!"=="!KANDIDAT!" exit /b 0
set "PY=!KANDIDAT!"
exit /b 0
