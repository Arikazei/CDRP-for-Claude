# Baut das .mcpb-Paket.
#
# Es wird bewusst nichts kompiliert: die Runtime ist Pythons offizielles
# Embeddable Package (python.exe von der PSF signiert), die Abhaengigkeiten
# sind reines Python. Dadurch enthaelt das Paket keine unsignierte
# Binaerdatei, die Virenscanner oder SmartScreen anmeckern koennten.
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$PyVersion = "3.12.10"
$EmbedUrl = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip"
$Build = Join-Path $Root "build"
$Dist = Join-Path $Root "dist"
$Cache = Join-Path $Root ".cache"
$Venv = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Venv)) { throw "Kein venv - zuerst setup_venv.bat ausfuehren." }

Remove-Item -Recurse -Force $Build -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Build, $Dist, $Cache | Out-Null

Write-Host "1/6  Runtime holen ($PyVersion)"
$Zip = Join-Path $Cache "python-embed.zip"
if (-not (Test-Path $Zip)) { Invoke-WebRequest -Uri $EmbedUrl -OutFile $Zip }
Expand-Archive -Path $Zip -DestinationPath (Join-Path $Build "runtime") -Force

# Interpreter umbenennen, damit der Dienst im Task-Manager als
# "ClaudeDiscordPresence" erscheint und nicht als weiteres "python.exe".
# Der Name muss mit dem command im Manifest uebereinstimmen.
Rename-Item (Join-Path $Build "runtime\python.exe") "ClaudeDiscordPresence.exe"

Write-Host "2/6  Abhaengigkeiten buendeln"
& $Venv -m pip install --quiet --target (Join-Path $Build "server\lib") `
    --no-compile -r (Join-Path $Root "requirements.txt")

# uiautomation liefert vorkompilierte Typelib-DLLs als Rueckfallebene mit.
# Getestet: comtypes erzeugt die Bindung genauso gut aus der systemeigenen
# UIAutomationCore.dll, damit bleibt das Paket frei von fremden Binaerdateien.
$UiaBin = Join-Path $Build "server\lib\uiautomation\bin"
if (Test-Path $UiaBin) { Remove-Item -Recurse -Force $UiaBin }

Write-Host "3/6  Standardkonfiguration erzeugen"
& $Venv (Join-Path $Root "mcpb\make_default_config.py")

Write-Host "4/6  Dateien kopieren"
Copy-Item (Join-Path $Root "claude_rpc.py") (Join-Path $Build "server\claude_rpc.py")
Copy-Item (Join-Path $Root "hostplatform.py") (Join-Path $Build "server\hostplatform.py")
Copy-Item (Join-Path $Root "beacons.py") (Join-Path $Build "server\beacons.py")
Copy-Item (Join-Path $Root "linuxdesktop.py") (Join-Path $Build "server\linuxdesktop.py")
Copy-Item (Join-Path $Root "mcpb\server\main.py") (Join-Path $Build "server\main.py")
Copy-Item (Join-Path $Root "mcpb\server\config.default.json") `
    (Join-Path $Build "server\config.default.json")
Copy-Item (Join-Path $Root "mcpb\manifest.json") (Join-Path $Build "manifest.json")
foreach ($extra in @("README.md", "LICENSE", "icon.png")) {
    $src = Join-Path $Root $extra
    if (Test-Path $src) { Copy-Item $src (Join-Path $Build $extra) }
}

Write-Host "5/6  Auf fremde Binaerdateien pruefen"
$Foreign = Get-ChildItem -Path (Join-Path $Build "server") -Recurse -Include *.pyd, *.dll
if ($Foreign) {
    $Foreign | ForEach-Object { Write-Warning "Binaerdatei im Bundle: $($_.FullName)" }
    throw "Abhaengigkeiten enthalten kompilierten Code - bitte ersetzen."
}

Write-Host "6/6  Paket schnueren"
$Manifest = Get-Content (Join-Path $Build "manifest.json") -Raw | ConvertFrom-Json
$Out = Join-Path $Dist "claude-discord-presence-$($Manifest.version).mcpb"
Remove-Item $Out -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $Build "*") -DestinationPath "$Out.zip" -Force
Move-Item "$Out.zip" $Out -Force

$SizeMb = [math]::Round((Get-Item $Out).Length / 1MB, 1)
Write-Host "Fertig: $Out ($SizeMb MB)"
