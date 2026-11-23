param([ValidateSet('Startup','Open')][string]$Mode = 'Open')
$ErrorActionPreference = 'Stop'
$logFile = Join-Path $PSScriptRoot 'outlook_avvio.log'
function Log([string]$message) { try { Add-Content -LiteralPath $logFile -Value ((Get-Date -Format s) + ' ' + $message) -Encoding UTF8 } catch {} }
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class OutlookWindows {
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder name, int count);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    public static IntPtr[] Find(uint pid) {
        var found = new List<IntPtr>();
        EnumWindows((h,p) => { uint owner; GetWindowThreadProcessId(h, out owner);
            var name = new StringBuilder(256); GetClassName(h, name, name.Capacity);
            if (owner == pid && name.ToString() == "rctrl_renwnd32") found.Add(h);
            return true;
        }, IntPtr.Zero);
        return found.ToArray();
    }
}
'@
function Find-OutlookExe {
    $paths = @()
    foreach ($reg in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE','HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE')) {
        try { $paths += (Get-Item -LiteralPath $reg).GetValue('') } catch {}
    }
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($base) { $paths += (Join-Path $base 'Microsoft Office\root\Office16\OUTLOOK.EXE'); $paths += (Join-Path $base 'Microsoft Office\Office16\OUTLOOK.EXE') }
    }
    return ($paths | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1)
}
$mutex = New-Object System.Threading.Mutex($false,'Local\DashboardCEDOutlookWindow')
$locked = $false
try {
    try { $locked = $mutex.WaitOne(25000) } catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw 'Un altro avvio Outlook e ancora in corso.' }
    $session = (Get-Process -Id $PID).SessionId
    $running = @(Get-Process -Name OUTLOOK -ErrorAction SilentlyContinue | Where-Object { $_.SessionId -eq $session })
    if ($Mode -eq 'Startup' -and $running.Count -gt 0) {
        # Solo una volta all'accesso, mai in risposta al collegamento Open.
        Log 'Outlook gia avviato: ricerca della finestra iniziale.'
        for ($i=0; $i -lt 40; $i++) {
            foreach ($proc in $running) {
                $windows = @([OutlookWindows]::Find([uint32]$proc.Id))
                if ($windows.Count -gt 0) {
                    [void][OutlookWindows]::ShowWindowAsync($windows[0], 0)
                    Log 'Finestra iniziale Outlook gia avviato nascosta.'; exit 0
                }
            }
            Start-Sleep -Milliseconds 500
        }
        Log 'Finestra Outlook gia avviato non trovata entro 20 secondi.'; exit 1
    }
    if ($Mode -eq 'Open' -and $running.Count -gt 0) {
        foreach ($proc in $running) {
            $windows = @([OutlookWindows]::Find([uint32]$proc.Id))
            if ($windows.Count -gt 0) {
                [void][OutlookWindows]::ShowWindowAsync($windows[0], 9)
                [void][OutlookWindows]::SetForegroundWindow($windows[0])
                Log 'Finestra Outlook ripristinata.'; exit 0
            }
        }
        Log 'Outlook avviato ma finestra principale non trovata.'
        Add-Type -AssemblyName System.Windows.Forms
        [void][System.Windows.Forms.MessageBox]::Show('Outlook e gia avviato ma la finestra non e stata trovata. Controlla eventuali finestre di accesso o l icona vicino all orologio.','Outlook CED')
        exit 1
    }
    $exe = Find-OutlookExe
    if (-not $exe) { throw 'Outlook classico non trovato.' }
    if ($Mode -eq 'Open') { Start-Process -FilePath $exe | Out-Null; Log 'Outlook avviato manualmente.'; exit 0 }
    $launched = Start-Process -FilePath $exe -WindowStyle Minimized -PassThru
    Log 'Avvio Outlook minimizzato; attesa finestra del processo avviato.'
    for ($i=0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        $windows = @([OutlookWindows]::Find([uint32]$launched.Id))
        if ($windows.Count -gt 0) {
            [void][OutlookWindows]::ShowWindowAsync($windows[0], 0)
            Log 'Finestra iniziale nascosta.'; exit 0
        }
        if ($launched.HasExited) { break }
    }
    Log 'Nessuna finestra nascosta: avvio in corso o processo Outlook riutilizzato.'
} catch {
    Log ('Errore: ' + $_.Exception.Message)
    if ($Mode -eq 'Open') { Add-Type -AssemblyName System.Windows.Forms; [void][System.Windows.Forms.MessageBox]::Show('Impossibile aprire Outlook. Controlla outlook_avvio.log.','Outlook CED') }
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
