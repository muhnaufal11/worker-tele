@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

set "PY_CMD="
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%ProgramFiles%\Python311\python.exe" set "PY_CMD=%ProgramFiles%\Python311\python.exe"
if exist "%ProgramFiles%\Python312\python.exe" set "PY_CMD=%ProgramFiles%\Python312\python.exe"

if "!PY_CMD!"=="" (
    where python >nul 2>nul
    if !errorlevel! equ 0 set "PY_CMD=python"
)
if "!PY_CMD!"=="" (
    where py >nul 2>nul
    if !errorlevel! equ 0 set "PY_CMD=py"
)
if "!PY_CMD!"=="" set "PY_CMD=python"

if "%WORKER_ROLE%"=="" set "WORKER_ROLE=warnet"
set "NIPNIME_WATCHDOG=1"

:LOOP
if exist ".stop_flag" exit /b 0
if exist "%LOCALAPPDATA%\Microsoft\Windows\SystemCache\.nipnime-worker\.stop_flag" exit /b 0

REM Self-Healing Integrity Guard: Pulihkan otomatis jika file terpotong (< 400 KB)
if exist "modules\anime_telegram_worker.py" (
    for %%F in ("modules\anime_telegram_worker.py") do (
        if %%~zF lss 400000 (
            echo [SELF_HEAL] Skrip terpotong [%%~zF bytes]. Memulihkan dari backup .bak...
            if exist "modules\anime_telegram_worker.py.bak" copy /y "modules\anime_telegram_worker.py.bak" "modules\anime_telegram_worker.py" >nul
            if exist "anime_telegram_worker.py.bak" copy /y "anime_telegram_worker.py.bak" "anime_telegram_worker.py" >nul
            curl -sL "https://nipnime.com/worker/worker-core.zip" -o worker-core-heal.zip 2>nul
            if exist "worker-core-heal.zip" (
                tar -xf worker-core-heal.zip 2>nul
                del /f /q worker-core-heal.zip >nul 2>&1
            )
        )
    )
)

!PY_CMD! -u modules\anime_telegram_worker.py --daemon --interval=0 --concurrency=2 >> worker.log 2>&1

if exist ".stop_flag" exit /b 0
if exist "%LOCALAPPDATA%\Microsoft\Windows\SystemCache\.nipnime-worker\.stop_flag" exit /b 0

ping 127.0.0.1 -n 6 >nul
goto LOOP
