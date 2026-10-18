@echo off
chcp 65001 >nul
title Nipnime Ongoing Anime Multi-Source First-Release dan Backfill Worker
color 0b
cd /d "%~dp0"

:MENU
cls
echo ======================================================================
echo    N I P N I M E   O N G O I N G   A N I M E   T O   T E L E G R A M
echo       Pemantau Rilisan Baru Otomatis (Fastest Real-World Release)
echo           AnimeSail vs Kuramanime vs NontonAnimeID + Backfill
echo ======================================================================
echo.
echo   [1] JALANKAN PEMANTAU OTOMATIS (Daemon Background Non-Stop)
echo       - Membaca halaman update dari 3 sumber: AnimeSail, Kurama, NontonAnimeID
echo       - Sumber yang rilis paling cepat / rilis duluan LANGSUNG diambil
echo       - Download dan upload resolusi yang tersedia ke Telegram (langsung tayang!)
echo       - Otomatis cek ulang dan lengkapi resolusi lain (1080p, 720p, 480p, 360p)
echo         baik dari sumber awal maupun sumber yang menyusul rilis
echo       - Otomatis cek dan lengkapi episode sebelumnya jika belum ada di web
echo.
echo   [2] TEST SCAN FEED RILISAN SEKARANG
echo       - Memindai halaman terbaru dari ketiga sumber dan menampilkan hasilnya
echo.
echo   [3] CEK STATUS RESOLUSI ANIME ONGOING (.ongoing_quality_state.json)
echo       - Melihat anime yang sudah lengkap vs yang masih menunggu resolusi lain
echo.
echo   [4] CEK KONEKSI BOT DAN CHANNEL TELEGRAM
echo       - Menguji bot Telegram, ID channel privat, dan koneksi MTProto
echo.
echo   [0] Keluar
echo.
echo ======================================================================
set /p "pilihan=Pilih menu [1/2/3/4/0]: "

if "%pilihan%"=="1" goto DAEMON_MODE
if "%pilihan%"=="2" goto TEST_SCAN
if "%pilihan%"=="3" goto VIEW_STATE
if "%pilihan%"=="4" goto TEST_CONN
if "%pilihan%"=="0" exit /b
goto MENU

:DAEMON_MODE
cls
echo ======================================================================
echo   MODE PEMANTAU RILISAN ONGOING DAN AUTO BACKFILL (NON-STOP)
echo   - Memantau halaman rilisan terbaru setiap interval waktu
echo   - Mengambil episode dari sumber yang rilis pertama kali
echo   - Melengkapi episode sebelumnya dan resolusi susulan dari semua sumber
echo   - Pengaman Watchdog: Auto-restart jika program terhenti atau error
echo ======================================================================
echo.
set "interval_sec=0"
echo [*] Mode Pemantauan: NON-STOP (Tanpa Waktu Istirahat)
echo.
set /p "concurrency=Jumlah unduh paralel / concurrency (Tekan Enter untuk 2): "
if "%concurrency%"=="" set "concurrency=2"

:DAEMON_LOOP
echo.
echo [*] Menjalankan pemantau rilisan anime ongoing (Watchdog Aktif)...
echo [*] Mode Paralel: %concurrency% Episode Bersamaan.
echo [*] Tekan Ctrl + C jika ingin menghentikan worker secara permanen.
echo.
set "NIPNIME_WATCHDOG=1"

for %%F in ("modules\anime_telegram_worker.py") do (
    if %%~zF lss 400000 (
        echo [ANTI-CRASH GUARD] Terdeteksi skrip terpotong [%%~zF bytes ^< 400 KB]!
        if exist "modules\anime_telegram_worker.py.bak" (
            echo [ANTI-CRASH GUARD] Memulihkan skrip stabil dari backup .bak...
            copy /y "modules\anime_telegram_worker.py.bak" "modules\anime_telegram_worker.py" >nul
            if exist "anime_telegram_worker.py.bak" copy /y "anime_telegram_worker.py.bak" "anime_telegram_worker.py" >nul
        )
    )
)

python -u modules\anime_telegram_worker.py --daemon --interval=%interval_sec% --concurrency=%concurrency%
set EXIT_CODE=%errorlevel%
echo.
echo [WATCHDOG] Worker terhenti (Exit Code: %EXIT_CODE%).

REM Pemeriksaan Integritas Pasca-Berhenti: Cek syntax error dan ukuran file
set "NEED_ROLLBACK=0"
if not "%EXIT_CODE%"=="0" (
    python -m py_compile modules\anime_telegram_worker.py >nul 2>&1
    if errorlevel 1 set "NEED_ROLLBACK=1"
)
for %%F in ("modules\anime_telegram_worker.py") do (
    if %%~zF lss 400000 set "NEED_ROLLBACK=1"
)

if "%NEED_ROLLBACK%"=="1" (
    echo [ANTI-CRASH GUARD] Terdeteksi kode rusak atau terpotong!
    if exist "modules\anime_telegram_worker.py.bak" (
        echo [ANTI-CRASH GUARD] Memulihkan skrip stabil sebelumnya dari backup .bak...
        copy /y "modules\anime_telegram_worker.py.bak" "modules\anime_telegram_worker.py" >nul
        if exist "anime_telegram_worker.py.bak" copy /y "anime_telegram_worker.py.bak" "anime_telegram_worker.py" >nul
        echo [ANTI-CRASH GUARD] Selesai rollback ke versi stabil. Memulai ulang worker...
    )
)

echo [WATCHDOG] Memulai ulang otomatis dalam 5 detik...
timeout /t 5 >nul
goto DAEMON_LOOP

:TEST_SCAN
cls
echo ======================================================================
echo   UJI PEMINDAIAN FEED RILISAN TERBARU (3 SUMBER)
echo ======================================================================
echo.
echo [*] Menghubungi AnimeSail, Kuramanime, dan NontonAnimeID...
echo.
python -u modules\anime_telegram_worker.py --test-scan
echo.
pause
goto MENU

:VIEW_STATE
cls
echo ======================================================================
echo   STATUS RESOLUSI EPISODE ONGOING SAAT INI
echo ======================================================================
echo.
python -u modules\anime_telegram_worker.py --view-state
echo.
pause
goto MENU

:TEST_CONN
cls
echo ======================================================================
echo   UJI KONEKSI TELEGRAM MTPROTO
echo ======================================================================
echo.
python -u modules\anime_telegram_worker.py --test-conn
echo.
pause
goto MENU
