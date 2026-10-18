@echo off
chcp 65001 >nul
title Nipnime YouTube to Telegram CDN Worker
color 0b

:MENU
cls
echo ======================================================================
echo           N I P N I M E   Y O U T U B E   T O   T E L E G R A M
echo                 Unlimited Storage CDN ^& Video Ingest
echo ======================================================================
echo.
echo   [1] PANTAU OTOMATIS (Non-Stop Tiap 15 Menit)
echo       - Memantau playlist anime aktif ^& video terbaru secara otomatis
echo       - Episode baru langsung dibuat di website (Auto-Add) ^& diunggah
echo.
echo   [2] SCRAPE ANIME (Ketik Nama Anime / Tempel Link YouTube)
echo       - Cepat (<1 detik via Playlist) + Fallback ke Tab /videos
echo       - Episode baru otomatis dibuat di website (Auto-Add) ^& diunggah
echo.
echo   [3] SIMULASI PENGECEKAN (Dry-Run / Cek Tanpa Download)
echo       - Cek daftar episode yang ada ^& episode baru tanpa download
echo.
echo   [4] JALANKAN STREAM PROXY SERVER (Port 8088)
echo       - Wajib aktif di latar belakang agar video Telegram bisa diputar di web
echo.
echo   [5] CEK KONEKSI BOT ^& CHANNEL TELEGRAM
echo       - Menguji bot Telegram, ID channel privat, dan token API
echo.
echo   [6] PERBAIKI VIDEO 360p (RE-INGEST KE HD)
echo       - Unduh ulang video 360p lama ke 720p/1080p asli ^& ganti link web
echo.
echo   [7] PERBARUI / UPDATE LIBRARY WORKER
echo       - Cek ^& perbarui yt-dlp ke versi paling baru
echo.
echo   [0] Keluar
echo.
echo ======================================================================
set /p "pilihan=Pilih menu [1/2/3/4/5/6/7/0]: "

if "%pilihan%"=="1" goto AUTO_WATCHER
if "%pilihan%"=="2" goto SCRAPE_ANIME
if "%pilihan%"=="3" goto DRY_RUN
if "%pilihan%"=="4" goto RUN_PROXY
if "%pilihan%"=="5" goto TEST_CONN
if "%pilihan%"=="6" goto REINGEST_360
if "%pilihan%"=="7" goto UPDATE_LIB
if "%pilihan%"=="0" exit /b
goto MENU

:AUTO_WATCHER
cls
echo ======================================================================
echo   MODE PANTAU OTOMATIS (NON-STOP TIAP 15 MENIT)
echo   - Memantau Playlist Anime Aktif Muse Indonesia + Tab /videos
echo   - Episode baru (misal Tensura rilis) otomatis dibuat di website (Auto-Add)
echo   - Otomatis unduh (1080p ^& 720p) dan upload ke Telegram CDN
echo ======================================================================
echo.
set /p "interval_min=Interval pemantauan dalam menit (Tekan Enter untuk 15 menit): "
if "%interval_min%"=="" set "interval_min=15"
set /a interval_sec=%interval_min%*60

echo.
echo [*] Menjalankan pemantau otomatis (Pengecekan tiap %interval_min% menit)...
echo [*] Tekan Ctrl + C jika ingin menghentikan pemantau.
echo.
python -u modules\yt_playlist_watcher.py --daemon --interval=%interval_sec% --quality=1080,720
echo.
pause
goto MENU

:SCRAPE_ANIME
cls
echo ======================================================================
echo   SCRAPE ANIME (PLAYLIST-FIRST + FALLBACK /VIDEOS + AUTO-ADD)
echo ======================================================================
echo Ketik nama anime (misal: Tensura, Doraemon, Level 2, Wind Breaker)
echo atau tempel URL video / playlist YouTube:
echo.
set /p "target_anime=Nama Anime / URL: "
if "%target_anime%"=="" goto MENU

echo.
echo [*] Memulai proses scraping kilat, fallback /videos, dan auto-add episode baru...
echo [*] Resolusi: Otomatis 1080p ^& 720p
python -u modules\yt_playlist_watcher.py --url="%target_anime%" --quality=1080,720
echo.
pause
goto MENU

:DRY_RUN
cls
echo ======================================================================
echo   SIMULASI PENGECEKAN (DRY-RUN / TANPA DOWNLOAD ^& TANPA UPLOAD)
echo ======================================================================
echo Ketik nama anime (misal: Tensura, Doraemon, Level 2, Wind Breaker)
echo atau tempel URL video / playlist YouTube:
echo.
set /p "dry_anime=Nama Anime / URL: "
if "%dry_anime%"=="" goto MENU

echo.
echo [*] Menjalankan simulasi pengecekan status episode...
python -u modules\yt_playlist_watcher.py --url="%dry_anime%" --dry-run
echo.
pause
goto MENU

:RUN_PROXY
cls
echo ======================================================================
echo   NIPNIME TELEGRAM HTTP STREAM PROXY SERVER
echo   (Biarkan jendela ini tetap terbuka agar video bisa diputar di web)
echo ======================================================================
echo.
python -u modules\telegram_stream_proxy.py
pause
goto MENU

:TEST_CONN
cls
echo ======================================================================
echo   MENGUJI KONEKSI BOT TELEGRAM ^& CHANNEL PRIVAT
echo ======================================================================
echo.
python -u modules\yt_telegram_worker.py --test
echo.
pause
goto MENU

:REINGEST_360
cls
echo ======================================================================
echo   PERBAIKI VIDEO 360p - RE-INGEST KE HD (720p / 1080p)
echo ======================================================================
echo.
echo Script ini akan memindai video 360p di channel Telegram,
echo mengunduh resolusi HD aslinya dari YouTube, mengupload ulang,
echo memperbarui link di web Nipnime, dan membersihkan pesan 360p lama.
echo.
echo   [1] Jalankan Perbaikan Otomatis Sekarang (Unduh ^& Ganti ke HD)
echo   [2] Simulasi Dulu (Dry-Run / Cek daftar episode)
echo   [0] Batal
echo.
set FIX_OPT=1
set /p FIX_OPT="Pilihan [1/2/0, default 1]: "
if "%FIX_OPT%"=="2" (
    python -u modules\reingest_360p.py --dry-run
    echo.
    pause
    goto MENU
)
if "%FIX_OPT%"=="0" goto MENU
python -u modules\reingest_360p.py
echo.
pause
goto MENU

:UPDATE_LIB
cls
echo ======================================================================
echo   PERBARUI / UPDATE DEPENDENCY WORKER
echo ======================================================================
echo.
echo Memperbarui yt-dlp ke versi paling baru...
echo.
python -m pip install -U yt-dlp pyrogram tgcrypto aiohttp python-dotenv
echo.
echo [OK] Dependensi berhasil diperbarui!
echo.
pause
goto MENU
