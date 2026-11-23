param([switch]$Rimuovi)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$startupLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'Dashboard Stampanti.lnk'
$desktopLink = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Dashboard Stampanti.lnk'
$stopLink = Join-Path $projectRoot 'Arresta Dashboard.lnk'
$openLink = Join-Path $projectRoot 'Apri Dashboard.lnk'
$outlookDesktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Apri Outlook CED.lnk'
$outlookLocal = Join-Path $projectRoot 'Apri Outlook CED.lnk'
$taskName = 'Dashboard Stampanti CED'
$protocolKey = 'HKCU:\Software\Classes\stampanti-locali'
if ($Rimuovi) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    foreach ($linkPath in @($startupLink,$desktopLink,$stopLink,$openLink,$outlookDesktop,$outlookLocal)) {
        if (Test-Path $linkPath) { Remove-Item -LiteralPath $linkPath -Force }
    }
    if (Test-Path $protocolKey) { Remove-Item $protocolKey -Recurse -Force }
    try { Invoke-WebRequest -Uri 'http://127.0.0.1:8767/api/stop' -Method POST -Headers @{Origin='http://127.0.0.1:8767'} -UseBasicParsing -TimeoutSec 2 | Out-Null } catch {}
    Write-Host 'Avvio automatico e collegamenti rimossi. I file restano nella cartella.'
    exit 0
}
$pythonPath = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonPath = (& py -3 -c 'import sys; print(sys.executable)' 2>$null | Select-Object -Last 1)
}
if (-not $pythonPath -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $pythonPath = (& python -c 'import sys; print(sys.executable)' 2>$null | Select-Object -Last 1)
}
if (-not $pythonPath) { throw 'Python non trovato. Installa Python 3.10 o successivo e riprova.' }
$pythonPath = $pythonPath.Trim()
$pythonwPath = Join-Path (Split-Path $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwPath)) { throw 'pythonw.exe non trovato accanto a Python. Ripara l installazione di Python.' }
& $pythonPath -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Versione Python non supportata.' }
$launcherPath = Join-Path $projectRoot 'launcher.pyw'
$shell = New-Object -ComObject WScript.Shell
foreach ($item in @(@($desktopLink,''),@($openLink,''),@($stopLink,' --stop'))) {
    $shortcut = $shell.CreateShortcut($item[0])
    $shortcut.TargetPath = $pythonwPath
    $shortcut.Arguments = '"' + $launcherPath + '"' + $item[1]
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = 'Dashboard stampanti locale'
    $shortcut.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',16'
    $shortcut.Save()
}
$outlookManager = Join-Path $projectRoot 'Outlook_CED.ps1'
$powerShellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
foreach ($linkPath in @($outlookDesktop,$outlookLocal)) {
    $shortcut = $shell.CreateShortcut($linkPath)
    $shortcut.TargetPath = $powerShellExe
    $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $outlookManager + '" -Mode Open'
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = 'Mostra Outlook CED se gia aperto'
    $shortcut.Save()
}
# Attivita per il solo utente corrente, senza elevazione e in sessione interattiva.
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonwPath -Argument ('"' + $launcherPath + '" --background') -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
# Solo dopo che l'attivita e registrata rimuoviamo il vecchio collegamento duplicato.
if (Test-Path -LiteralPath $startupLink) { Remove-Item -LiteralPath $startupLink -Force }
New-Item -Path $protocolKey -Force | Out-Null
Set-Item -Path $protocolKey -Value 'URL:Dashboard stampanti locale'
New-ItemProperty -Path $protocolKey -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
New-Item -Path "$protocolKey\shell\open\command" -Force | Out-Null
$command = '"' + $pythonwPath + '" "' + $launcherPath + '" --url "%1"'
Set-Item -Path "$protocolKey\shell\open\command" -Value $command
Start-Process -FilePath $pythonwPath -ArgumentList ('"'+$launcherPath+'" --background --no-outlook') -WorkingDirectory $projectRoot
Write-Host 'Installazione completata per il tuo utente, senza privilegi amministratore.'
Write-Host 'Avvio silenzioso al prossimo accesso a Windows tramite Utilita di pianificazione. Browser non aperto al login.'
Write-Host 'Scorciatoia desktop pronta. Per un preferito del browser usa: stampanti-locali://apri'
Write-Host 'Mantieni questa cartella nella stessa posizione.'
