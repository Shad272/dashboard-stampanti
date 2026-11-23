@echo off
cd /d "%~dp0"
echo Arresto della dashboard stampanti sulla porta 8767...
where py >nul 2>&1
if not errorlevel 1 (
    py -3 "%~dp0arresta.py"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python non trovato. Controlla l installazione di Python.
        pause
        exit /b 1
    )
    python "%~dp0arresta.py"
)
echo.
pause
