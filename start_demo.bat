@echo off
setlocal enabledelayedexpansion

:: ==========================================================================
:: DeepTune Demo — One-Click Launcher (Patch File Final)
:: ==========================================================================
:: 1. Starts the backend (Docker Compose or local fallback)
:: 2. Waits for http://localhost:8000/api/v1/health to return 200
:: 3. Starts the frontend (npm run dev in apps/web)
:: 4. Opens http://localhost:3000 in the default browser
:: 5. Prints a giant green "DEMO READY" message
:: ==========================================================================

cd /d "%~dp0"

echo.
echo ========================================================================
echo  DeepTune Demo — One-Click Launcher
echo ========================================================================
echo.

:: ------------------------------------------------------------------------
:: Step 1: Start the backend
:: ------------------------------------------------------------------------
echo [1/4] Starting backend…

:: Check if Docker is available
where docker >nul 2>&1
if %errorlevel% equ 0 (
    echo     Docker detected — starting with docker compose…
    docker compose up -d >nul 2>&1
    if %errorlevel% neq 0 (
        echo     WARNING: docker compose failed, falling back to local backend.
    )
) else (
    echo     Docker not found — starting local backend…
)

:: Start local backend if not already running
powershell -Command "if (-not (Test-NetConnection -ComputerName 127.0.0.1 -Port 8000 -InformationLevel Quiet)) { Start-Process -FilePath 'apps/api\.venv\Scripts\python.exe' -ArgumentList '-m', 'uvicorn', 'src.main:app', '--host', '127.0.0.1', '--port', '8000' -WorkingDirectory 'apps/api' -WindowStyle Hidden }" >nul 2>&1

:: ------------------------------------------------------------------------
:: Step 2: Wait for health endpoint
:: ------------------------------------------------------------------------
echo [2/4] Waiting for API at http://localhost:8000/api/v1/health …
set /a attempts=0
:wait_health
powershell -Command "try { $r = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/health' -TimeoutSec 3; if ($r.status -eq 'ok') { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if %errorlevel% equ 0 goto health_ok
set /a attempts+=1
if %attempts% geq 60 (
    echo     ERROR: API did not become healthy after 60 seconds.
    goto end
)
timeout /t 2 >nul
goto wait_health

:health_ok
echo     API is healthy.

:: ------------------------------------------------------------------------
:: Step 3: Start the frontend
:: ------------------------------------------------------------------------
echo [3/4] Starting frontend (npm run dev)…
cd apps/web
call npm.cmd run dev >nul 2>&1 &
cd ".."

:: ------------------------------------------------------------------------
:: Step 4: Open the browser
:: ------------------------------------------------------------------------
echo [4/4] Opening http://localhost:3000 …
start "" "http://localhost:3000" >nul 2>&1

:: ------------------------------------------------------------------------
:: Step 5: DEMO READY
:: ------------------------------------------------------------------------
:demo_ready
echo.
echo ========================================================================
echo.
echo                       DEMO READY
echo.
echo ========================================================================
echo.
echo  Backend : http://localhost:8000
echo  Frontend: http://localhost:3000
echo  Health  : http://localhost:8000/api/v1/health
echo.
echo  Demo mode: ON (JWT bypassed, auto-connect, golden-path fallback)
echo.
echo  Press Ctrl+C to stop the demo servers.
echo.
:end
endlocal
