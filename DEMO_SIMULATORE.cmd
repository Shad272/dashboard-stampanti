@echo off
cd /d "%~dp0"
echo DASHBOARD STAMPANTI - VERSIONE DIMOSTRATIVA
echo Stampanti simulate su questo PC: nessuna lettura in rete, nessuna email.
echo Si apre http://127.0.0.1:8767 - per terminare chiudi questa finestra.
echo.
where py >nul 2>&1
if %errorlevel%==0 (py -3 demo_simulatore.py) else (python demo_simulatore.py)
if errorlevel 1 (
    echo.
    echo Avvio non riuscito. Serve Python 3.10 o successivo e la porta 8767 libera:
    echo chiudi un'eventuale dashboard gia aperta e riprova.
    pause
)
