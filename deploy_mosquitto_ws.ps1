# Deploy clean Mosquitto config and restart
$src = "d:\Fanjet\repo_temp\mosquitto_fanjet.conf"
$dst = "C:\Program Files\mosquitto\mosquitto.conf"

# Copy config (ASCII encoding to avoid unicode issues)
[System.IO.File]::WriteAllText($dst, [System.IO.File]::ReadAllText($src, [System.Text.Encoding]::UTF8), [System.Text.Encoding]::ASCII)
Write-Host "Config written to $dst"

# Show what was written
Get-Content $dst
Write-Host ""

# Restart service
Write-Host "Starting Mosquitto..."
net start mosquitto
Start-Sleep 3

# Verify
$svc = Get-Service mosquitto
Write-Host "Status: $($svc.Status)"

netstat -an | Select-String "LISTENING" | Select-String "1883|9001" | ForEach-Object { Write-Host $_.Line }

Write-Host ""
Write-Host "Press any key to close..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
