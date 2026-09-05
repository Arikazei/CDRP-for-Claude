# Entfernt die Autostart-Eintraege und beendet Dienst und Waechter.
#
# Danach sendet wieder die Extension in Claude Desktop -- sie versucht
# die Uebernahme im Minutentakt und merkt von selbst, dass der Dienst
# weg ist. Es geht also nichts verloren.

$ErrorActionPreference = "Continue"
$start = [Environment]::GetFolderPath("Startup")

foreach ($name in @("DiscordPresence-Dienst.vbs", "DiscordRP-Codex.vbs",
                    "DiscordRP-Antigravity.vbs")) {
    $vbs = Join-Path $start $name
    if (Test-Path $vbs) {
        Remove-Item $vbs -Force
        Write-Host "Autostart entfernt:" $vbs
    }
}

# Nach der Befehlszeile suchen, nicht nach dem Prozessnamen. Der Name
# ist nicht verlaesslich: die Store-Fassung von Python meldet sich als
# "pythonw3.12.exe", eine Verknuepfung im Autostart kann anders heissen.
# Genau daran ist am 22.08.2026 eine alte Instanz uebersehen worden --
# sie hielt den Mutex, und die Presence blieb stumm, waehrend im
# Protokoll nur "laeuft bereits" stand.
$muster = "run_presence\.py|connectors[\\/](codex|antigravity)[\\/]watcher\.py"
$laeuft = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -like "python*" -and $_.ProcessId -ne $PID -and
    $_.CommandLine -match $muster
})
foreach ($p in $laeuft) {
    Stop-Process -Id $p.ProcessId -Force
    $letztes = ($p.CommandLine.TrimEnd('"') -split "\\")[-1]
    Write-Host ("beendet {0,6} {1}" -f $p.ProcessId, $letztes)
}
if (-not $laeuft) { Write-Host "Es lief nichts." }

Write-Host "Die Extension uebernimmt binnen einer Minute wieder."
Write-Host "Die Codex-Hooks bleiben registriert und schreiben weiter Beacons;"
Write-Host "ohne Waechter verfallen die nach 15 Minuten. Abschalten: in Codex"
Write-Host "das Plugin codex-discord-presence deaktivieren."
