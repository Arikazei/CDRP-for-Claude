# Entfernt den Autostart-Eintrag und beendet den laufenden Dienst.
#
# Danach sendet wieder die Extension in Claude Desktop -- sie versucht
# die Uebernahme im Minutentakt und merkt von selbst, dass der Dienst
# weg ist. Es geht also nichts verloren.

$ErrorActionPreference = "Continue"
$start = [Environment]::GetFolderPath("Startup")
$vbs = Join-Path $start "DiscordPresence-Dienst.vbs"

if (Test-Path $vbs) {
    Remove-Item $vbs -Force
    Write-Host "Autostart entfernt:" $vbs
} else {
    Write-Host "Kein Autostart-Eintrag gefunden."
}

$laeuft = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*run_presence.py*" }
foreach ($p in $laeuft) {
    Stop-Process -Id $p.ProcessId -Force
    Write-Host "Dienst beendet, PID" $p.ProcessId
}
if (-not $laeuft) { Write-Host "Es lief kein Dienst." }

Write-Host "Die Extension uebernimmt binnen einer Minute wieder."
