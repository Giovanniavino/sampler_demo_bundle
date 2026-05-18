@echo off
chcp 65001 > nul
title Installazione DrumPad Sampler
color 0A

echo.
echo  =====================================================
echo       DRUMPAD SAMPLER - Installazione automatica
echo  =====================================================
echo.
echo  Questo processo potrebbe richiedere 10-20 minuti.
echo  Non chiudere questa finestra!
echo.
pause

REM ─────────────────────────────────────────────────────
REM  Cartella base del progetto (dove si trova questo bat)
REM ─────────────────────────────────────────────────────
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

REM ─────────────────────────────────────────────────────
REM  STEP 1 — Controlla Python
REM ─────────────────────────────────────────────────────
echo  [1/6] Controllo Python...
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  Python non trovato. Lo scarico e installo automaticamente...
    echo  (potrebbe aprirsi una finestra di installazione)
    echo.
    curl -L -o "%TEMP%\python_installer.exe" "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    if %errorlevel% neq 0 (
        echo.
        echo  [ERRORE] Impossibile scaricare Python. Controlla la connessione internet.
        pause
        exit /b 1
    )
    "%TEMP%\python_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_test=0
    del "%TEMP%\python_installer.exe"
    
    REM Ricarica il PATH dopo l'installazione
    call refreshenv > nul 2>&1
    
    python --version > nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo  [ERRORE] Installazione Python fallita.
        echo  Scarica Python 3.11 manualmente da https://www.python.org
        echo  e spunta "Add Python to PATH" durante l'installazione.
        pause
        exit /b 1
    )
)
for /f "tokens=*" %%i in ('python --version') do echo  OK: %%i trovato.


REM ─────────────────────────────────────────────────────
REM  STEP 2 — Crea ambiente virtuale
REM ─────────────────────────────────────────────────────
echo.
echo  [2/6] Creo ambiente virtuale isolato...
if exist "%PROJECT_DIR%venv" (
    echo  Ambiente virtuale gia' esistente, lo uso.
) else (
    python -m venv "%PROJECT_DIR%venv"
    if %errorlevel% neq 0 (
        echo  [ERRORE] Impossibile creare l'ambiente virtuale.
        pause
        exit /b 1
    )
    echo  OK: ambiente virtuale creato.
)


REM ─────────────────────────────────────────────────────
REM  STEP 3 — Attiva venv e aggiorna pip
REM ─────────────────────────────────────────────────────
echo.
echo  [3/6] Aggiorno pip...
call "%PROJECT_DIR%venv\Scripts\activate.bat"
python -m pip install --upgrade pip --quiet
echo  OK: pip aggiornato.


REM ─────────────────────────────────────────────────────
REM  STEP 4 — Dipendenze base
REM ─────────────────────────────────────────────────────
echo.
echo  [4/6] Installo dipendenze base (PyQt6, audio, ecc.)...
echo  Potrebbe volerci qualche minuto...
pip install -r "%PROJECT_DIR%requirements.txt" --quiet
if %errorlevel% neq 0 (
    echo  [ERRORE] Installazione requirements.txt fallita.
    pause
    exit /b 1
)
echo  OK: dipendenze base installate.


REM ─────────────────────────────────────────────────────
REM  STEP 5 — PyTorch con GPU NVIDIA (CUDA 12.1)
REM ─────────────────────────────────────────────────────
echo.
echo  [5/6] Installo PyTorch con supporto GPU NVIDIA...
echo  Questo e' il passaggio piu' pesante (~2-3 GB da scaricare).
echo  Non chiudere la finestra, ci vorra' del tempo...
echo.
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 --quiet
if %errorlevel% neq 0 (
    echo  [ERRORE] Installazione PyTorch fallita. Controlla la connessione.
    pause
    exit /b 1
)
echo  OK: PyTorch con CUDA installato.

echo.
echo  Installo Demucs e dipendenze AI...
pip install -r "%PROJECT_DIR%requirements-ai.txt" --quiet
if %errorlevel% neq 0 (
    echo  [ERRORE] Installazione requirements-ai.txt fallita.
    pause
    exit /b 1
)
echo  OK: Demucs e AI installati.


REM ─────────────────────────────────────────────────────
REM  STEP 6 — Crea collegamento sul Desktop
REM ─────────────────────────────────────────────────────
echo.
echo  [6/6] Creo collegamento sul Desktop...
powershell -NoProfile -Command ^
  "$s=(New-Object -COM WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\DrumPad Sampler.lnk');" ^
  "$s.TargetPath='%PROJECT_DIR%Avvia.bat';" ^
  "$s.WorkingDirectory='%PROJECT_DIR%';" ^
  "$s.WindowStyle=7;" ^
  "$s.Description='Avvia DrumPad Sampler';" ^
  "$s.Save()"
echo  OK: collegamento creato sul Desktop.


REM ─────────────────────────────────────────────────────
REM  FINE
REM ─────────────────────────────────────────────────────
echo.
echo  =====================================================
echo       INSTALLAZIONE COMPLETATA CON SUCCESSO!
echo  =====================================================
echo.
echo  Trovi il collegamento "DrumPad Sampler" sul Desktop.
echo  D'ora in poi fai doppio clic su quello per avviarlo.
echo.
echo  NOTA: al primo avvio Demucs scarichera' i modelli AI
echo  (~300 MB). Ci vorranno alcuni minuti, e' normale.
echo.
pause
