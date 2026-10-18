@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Nipnime Telegram Ingest and Video Worker (Laptop)
color 0b
cd /d "%~dp0"

echo ======================================================================
echo    N I P N I M E   W O R K E R   -   L A P T O P   L A U N C H E R
echo       Multi-Source Auto-Release, Watermark and 2K QHD Engine
echo ======================================================================
echo.

REM 1. Sinkronisasi modul jika terhubung ke server Z:
if exist "Z:\tools\terop-worker\modules\anime_telegram_worker.py" (
    if /i not "%~dp0"=="Z:\tools\terop-worker\" (
        echo [*] Mendeteksi Server Z:\ - Melakukan sinkronisasi file...
        robocopy "Z:\tools\terop-worker\modules" "%~dp0modules" /XO /NJH /NJS /NDL >nul 2>&1
        copy /y "Z:\tools\terop-worker\requirements.txt" "%~dp0requirements.txt" >nul 2>&1
        echo [OK] Sinkronisasi selesai.
    )
)

REM 2. Cek Python
echo [*] Memeriksa instalasi Python...
set "PY_CMD="
where python >nul 2>nul
if !errorlevel! equ 0 (
    set "PY_CMD=python"
) else (
    where py >nul 2>nul
    if !errorlevel! equ 0 (
        set "PY_CMD=py"
    )
)

if "!PY_CMD!"=="" (
    echo [ERROR] Python tidak ditemukan di laptop ini!
    echo Unduh Python di: https://www.python.org/downloads/
    echo Pastikan mencentang: Add Python to PATH
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('!PY_CMD! --version 2^>^&1') do echo [OK] %%v

REM 3. Cek file .env
if not exist ".env" (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
    ) else (
        (
            echo API_URL=https://nipnime.com/api/terop
            echo WORKER_TOKEN=nipnime_terop_secret_key_2026
            echo TELEGRAM_API_ID=37009424
            echo TELEGRAM_API_HASH=9e15f809ab7f895bcd0786c36881599d
            echo TELEGRAM_BOT_TOKEN=8613506821:AAHD74hykC4SKHUdtFqirTZTcz7MJq7k8cI
            echo TELEGRAM_CHANNEL_ID=-1004428873400
            echo TELEGRAM_STREAM_BASE_URL=https://nipnime.com/tg-stream
        ) > ".env"
    )
    echo [OK] File .env berhasil dibuat.
)

REM 4. Cek Paket Python & Akselerasi TgCrypto
echo [*] Memeriksa library Python...
!PY_CMD! -c "import pyrogram, tgcrypto, aiohttp, requests, psutil, PIL, dotenv" >nul 2>nul
if !errorlevel! neq 0 (
    echo [*] Menginstall dependencies & akselerasi TgCrypto...
    if exist "requirements.txt" (
        !PY_CMD! -m pip install -r requirements.txt
    ) else (
        !PY_CMD! -m pip install TgCrypto-pyrofork pyrogram cryptography requests aiohttp psutil pillow python-dotenv
    )
) else (
    echo [OK] Library Python lengkap (Akselerasi TgCrypto Aktif).
)

REM 5. Cek FFmpeg
set "FFMPEG_PATH=%~dp0bin\ffmpeg.exe"
if not exist "!FFMPEG_PATH!" (
    where ffmpeg >nul 2>nul
    if !errorlevel! equ 0 (
        set "FFMPEG_PATH=ffmpeg"
        echo [OK] FFmpeg ditemukan di System PATH.
    ) else (
        echo [!] FFmpeg belum ada di bin\ffmpeg.exe
    )
) else (
    echo [OK] FFmpeg siap: !FFMPEG_PATH!
)

REM 6. Cek GPU NVIDIA
echo [*] Memeriksa GPU...
where nvidia-smi >nul 2>nul
if %errorlevel% equ 0 (
    for /f "tokens=*" %%g in ('nvidia-smi --query-gpu^=name --format^=csv^,noheader 2^>nul') do echo [GPU_READY] GPU: %%g ^(Hardware NVENC Aktif!^)
) else (
    echo [GPU_INFO] GPU NVIDIA tidak ditemukan. Mode CPU Fallback aktif.
)

REM Jika ada argumen CLI (misal --daemon), langsung jalankan
if not "%~1"=="" (
    echo [*] Menjalankan perintah: %*
    !PY_CMD! -u modules\anime_telegram_worker.py %*
    exit /b !errorlevel!
)

:MENU
echo.
echo ======================================================================
echo   PILIHAN:
echo   [1] JALANKAN WORKER UTAMA (Daemon 24/7 + Watchdog Auto-Restart)
echo   [2] TEST SCAN FEED TERBARU
echo   [3] UJI BENCHMARK RENDER GPU/CPU
echo   [4] CEK STATUS EPISODE ONGOING
echo   [5] CEK KONEKSI TELEGRAM
echo   [0] Keluar
echo ======================================================================
set /p "pilih=Pilih opsi [1/2/3/4/5/0]: "

if "!pilih!"=="1" goto RUN_DAEMON
if "!pilih!"=="2" goto RUN_SCAN
if "!pilih!"=="3" goto RUN_BENCH
if "!pilih!"=="4" goto RUN_STATUS
if "!pilih!"=="5" goto RUN_CONN
if "!pilih!"=="0" exit /b
goto MENU

:RUN_DAEMON
cls
echo ======================================================================
echo   WORKER BERJALAN (DAEMON WATCHDOG NON-STOP)
echo ======================================================================
set /p "concurrency=Jumlah unduh paralel [Enter untuk 2]: "
if "!concurrency!"=="" set "concurrency=2"

:LOOP_DAEMON
echo.
echo [*] Worker dimulai pada concurrency: !concurrency!
!PY_CMD! -u modules\anime_telegram_worker.py --daemon --interval=0 --concurrency=!concurrency!
set "CODE=!errorlevel!"
echo.
echo [WATCHDOG] Worker terhenti (Exit Code: !CODE!). Restart otomatis dalam 5 detik...
timeout /t 5 >nul
goto LOOP_DAEMON

:RUN_SCAN
cls
!PY_CMD! -u modules\anime_telegram_worker.py --test-scan
pause
goto MENU

:RUN_BENCH
cls
if exist "scratch\benchmark_rtx2050.py" (
    !PY_CMD! "scratch\benchmark_rtx2050.py"
) else (
    echo File benchmark tidak ditemukan.
)
pause
goto MENU

:RUN_STATUS
cls
!PY_CMD! -u modules\anime_telegram_worker.py --view-state
pause
goto MENU

:RUN_CONN
cls
!PY_CMD! -u modules\anime_telegram_worker.py --test-conn
pause
goto MENU
