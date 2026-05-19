@echo off
chcp 65001 > nul
title DrumPad Sampler
color 0A

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

REM Controlla che l'installazione sia stata fatta
if not exist "%PROJECT_DIR%venv\Scripts\activate.bat" (
    echo.
    echo  [ERRORE] Ambiente virtuale non trovato.
    echo  Esegui prima INSTALLA.bat!
    echo.
    pause
    exit /b 1
)

REM Attiva venv
call "%PROJECT_DIR%venv\Scripts\activate.bat"

REM Imposta PYTHONPATH
set "PYTHONPATH=%PROJECT_DIR%"

REM Avvia l'applicazione
echo  Avvio DrumPad Sampler...
python -m app.main

REM Se va in crash mostra l'errore
if %errorlevel% neq 0 (
    echo.
    echo  L'applicazione si e' chiusa con un errore.
    echo  Premi un tasto per vedere i dettagli.
    pause
)
