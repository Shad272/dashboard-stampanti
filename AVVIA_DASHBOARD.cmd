@echo off
cd /d "%~dp0"
where pyw >nul 2>&1
if not errorlevel 1 (
    start "" pyw -3 "%~dp0launcher.pyw"
    exit /b
)
where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" pythonw "%~dp0launcher.pyw"
    exit /b
)
echo Avvio della dashboard. La finestra si chiudera dopo l avvio.
py -3 "%~dp0launcher.pyw"
if errorlevel 1 pause
