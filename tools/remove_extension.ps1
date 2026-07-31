# Entfernt die Erweiterung von Hand, wenn die Oberflaeche es nicht anbietet.
# Muss bei GESCHLOSSENEM Claude Desktop laufen: die App schreibt die
# Registrierungsdatei beim Beenden neu und wuerde die Aenderung ueberschreiben.
$ErrorActionPreference = 'Stop'
$Muster = 'claude-discord-presence'

$reg      = "$env:APPDATA\Claude\extensions-installations.json"
$ordner   = "$env:APPDATA\Claude\Claude Extensions"
$settings = "$env:APPDATA\Claude\Claude Extensions Settings"

Write-Host "Warte, bis Claude Desktop beendet ist..." -ForegroundColor Cyan
$wartezeit = 0
while (Get-Process claude -ErrorAction SilentlyContinue) {
    if ($wartezeit -ge 90) {
        Write-Host "Claude laeuft immer noch - bitte beenden und Skript neu starten." -ForegroundColor Red
        Read-Host "Enter"; exit 1
    }
    Start-Sleep -Seconds 2; $wartezeit += 2
}
Write-Host "Claude ist beendet." -ForegroundColor Green

Get-Process ClaudeDiscordPresence -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Beende uebrig gebliebenen Dienst (PID $($_.Id))"
    Stop-Process -Id $_.Id -Force
}
Start-Sleep -Seconds 1

if (Test-Path $reg) {
    Copy-Item $reg "$reg.bak" -Force
    Write-Host "Sicherung angelegt: $reg.bak"
    $data = Get-Content $reg -Raw | ConvertFrom-Json
    $treffer = $data.extensions.PSObject.Properties.Name | Where-Object { $_ -like "*$Muster*" }
    foreach ($id in $treffer) {
        $data.extensions.PSObject.Properties.Remove($id)
        Write-Host "Registrierung entfernt: $id" -ForegroundColor Yellow
    }
    $json = $data | ConvertTo-Json -Depth 100
    [System.IO.File]::WriteAllText($reg, $json, (New-Object System.Text.UTF8Encoding $false))
}

Get-ChildItem $ordner -Directory -ErrorAction SilentlyContinue |
    Where-Object Name -like "*$Muster*" | ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force
        Write-Host "Ordner geloescht: $($_.Name)" -ForegroundColor Yellow
    }

Get-ChildItem $settings -File -ErrorAction SilentlyContinue |
    Where-Object Name -like "*$Muster*" | ForEach-Object {
        Remove-Item $_.FullName -Force
        Write-Host "Einstellungen geloescht: $($_.Name)" -ForegroundColor Yellow
    }

Write-Host ""
Write-Host "Verbleibende Erweiterungen:" -ForegroundColor Cyan
(Get-Content $reg -Raw | ConvertFrom-Json).extensions.PSObject.Properties.Name |
    ForEach-Object { "  $_" }
Write-Host ""
Write-Host "Fertig. Claude Desktop starten und 1.1.2 installieren." -ForegroundColor Green
Read-Host "Enter zum Schliessen"
