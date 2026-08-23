# Dienst und Connector-Waechter sauber durchstarten.
#
# Als Datei und nicht als Einzeiler: sucht man Prozesse nach ihrer
# Befehlszeile und tippt das Muster in dieselbe Shell, steht das Muster
# auch in DEREN Befehlszeile -- die Shell beendet sich selbst mitten im
# Skript. Genau das ist am 22.08.2026 zweimal passiert.
$ErrorActionPreference = "Continue"
$ich = $PID
# Zusammengesetzt, damit das Muster nirgends als ganzes Wort in einer
# Befehlszeile steht, die selbst durchsucht wird.
$regex = ("run" + "_presence") + "|" + ("watcher" + "\.py")
$start = [Environment]::GetFolderPath("Startup")

function Finde {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -like "python*" -and $_.ProcessId -ne $ich -and
        $_.CommandLine -match $regex
    }
}

foreach ($p in Finde) {
    Write-Host ("beende {0,6} {1}" -f $p.ProcessId, $p.Name)
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

# Auch die Extension beenden. Claude Desktop startet sie von selbst neu,
# dann mit den aktuellen Dateien.
#
# Ohne das bleibt beim Entwickeln eine Instanz mit altem Code im
# Speicher liegen: Python liest die Datei einmal beim Start. Am
# 23.08.2026 hat genau so ein Prozess vom Vorabend den Mutex gehalten
# und weitergesendet, waehrend der frisch gestartete Dienst danebenstand
# und wartete. Sichtbar war das nur daran, dass in der Presence
# Formulierungen standen, die es im aktuellen Stand nicht mehr gab.
foreach ($p in Get-Process ClaudeDiscordPresence -ErrorAction SilentlyContinue) {
    Write-Host ("beende {0,6} {1} (Extension)" -f $p.Id, $p.ProcessName)
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 4
foreach ($v in @("DiscordPresence-Dienst.vbs", "DiscordRP-Antigravity.vbs",
                 "DiscordRP-Codex.vbs")) {
    $pfad = Join-Path $start $v
    if (Test-Path $pfad) {
        Start-Process wscript.exe -ArgumentList "`"$pfad`""
        Write-Host ("gestartet {0}" -f $v)
    }
}
Start-Sleep -Seconds 12

Write-Host ""
foreach ($p in Finde) {
    $letztes = ($p.CommandLine.TrimEnd('"') -split "\\")[-1]
    Write-Host ("laeuft {0,6} {1,-18} {2}" -f $p.ProcessId, $p.Name, $letztes)
}
