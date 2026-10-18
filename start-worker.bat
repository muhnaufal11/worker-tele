@echo off
chcp 65001 >nul
title Nipnime Remote Worker - All-in-One
color 0F
cd /d "%~dp0"

:: Sinkronkan seluruh script dan modul terbaru dari Z:\tools\terop-worker jika drive Z: terhubung
if exist "Z:\tools\terop-worker\modules\yt_playlist_watcher.py" (
    if /i not "%~dp0"=="Z:\tools\terop-worker\" (
        robocopy "Z:\tools\terop-worker\modules" "%~dp0modules" /XO /NJH /NJS /NDL >nul 2>&1
        copy /y "Z:\tools\terop-worker\*.bat" "%~dp0" >nul 2>&1
        copy /y "Z:\tools\terop-worker\worker.js" "%~dp0worker.js" >nul 2>&1
        copy /y "Z:\tools\terop-worker\muse_playlists.json" "%~dp0muse_playlists.json" >nul 2>&1
    )
)

:: Cek apakah Node.js terpasang
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Node.js belum terpasang di komputer ini.
    echo Silakan install Node.js terlebih dahulu dari https://nodejs.org
    echo.
    pause
    exit /b 1
)

:: Buat file .env otomatis jika belum ada
if not exist ".env" (
    echo [INFO] Membuat file .env otomatis...
    echo API_URL=https://nipnime.com/api/terop > .env
    echo WORKER_TOKEN=nipnime_terop_secret_key_2026 >> .env
    echo DEFAULT_SOURCE=all >> .env
    echo DEFAULT_LIMIT=20 >> .env
    echo POLL_INTERVAL_SECONDS=45 >> .env
    echo HEADLESS=true >> .env
    echo [OK] File .env berhasil dibuat.
)

:MENU
set BROWSER_MODE=HIDE
set BROWSER_FLAG=--hide
set BROWSER_DESC=Senyap di Latar Belakang (Tanpa Jendela Browser)

if exist "%~dp0browser_mode.txt" (
    findstr /i "TAMPIL" "%~dp0browser_mode.txt" >nul 2>&1
    if not errorlevel 1 (
        set BROWSER_MODE=TAMPIL
        set BROWSER_FLAG=--show
        set BROWSER_DESC=Jendela Brave Terbuka di Layar (Visual Monitor)
    )
)
if not "%BROWSER_MODE%"=="TAMPIL" if exist "%~dp0.env" (
    findstr /i "HEADLESS=false" "%~dp0.env" >nul 2>&1
    if not errorlevel 1 (
        set BROWSER_MODE=TAMPIL
        set BROWSER_FLAG=--show
        set BROWSER_DESC=Jendela Brave Terbuka di Layar (Visual Monitor)
    )
)

cls
echo ================================================================
echo             N I P N I M E   R E M O T E   W O R K E R
echo         All-in-One: Web Scraper, Auto-Watcher ^& CDN Ingest
echo ================================================================
echo.
if "%BROWSER_MODE%"=="HIDE" (
    echo   Mode Browser : [ HIDE / SENYAP ] (Latar Belakang - Tanpa Jendela)
) else (
    echo   Mode Browser : [ TAMPIL ] (Jendela Brave Terbuka di Layar)
)
echo.
echo   [YOUTUBE ^& TELEGRAM UNLIMITED CDN]
echo     [1] PANTAU OTOMATIS (Loop Daemon Non-Stop Tiap 15 Menit)
echo         - Auto-detect episode baru (Tensura, dll.) ^& otomatis nambah ke web
echo     [2] SCRAPE ANIME SEKARANG (Ketik Nama Anime / Tempel Link YouTube)
echo         - Playlist-First (^<1 dtk) + Fallback /videos + Auto-Add Episode
echo     [3] SIMULASI SCRAPE YOUTUBE (Dry-Run / Cek Tanpa Download ^& Upload)
echo     [4] JALANKAN TELEGRAM STREAM PROXY SERVER (Port 8088)
echo     [5] CEK KONEKSI BOT ^& CHANNEL TELEGRAM
echo     [A] PEMANTAU ONGOING ANIME (AnimeSail vs Kurama vs NontonAnimeID)
echo         - Rilis tercepat + cek ep sebelumnya + auto backfill resolusi
echo     [F] PERBAIKI VIDEO 360p (Otomatis re-ingest ke HD 720p/1080p asli ^& update link web)
echo     [U] PERBARUI / UPDATE LIBRARY (yt-dlp, challenge solver ^& modul worker)
echo.
echo   [MODE STREAM SCRAPER ^& SERVER DOWNLOAD]
echo     [6] Kuramanime + Nekopoi Paralel (Semua Sumber)
echo     [7] Kuramanime Saja (Serial TV)
echo     [8] Kuramanime Movie Saja
echo     [9] NEKOPOI Server Download (CasaOS)
echo     [D] Buka Dual Terminal (Kurama + Neko Split-Screen)
echo.
echo   [PANTAUAN REAL-TIME ^& PENGATURAN]
echo     [M] Pantau Server Admin Live (Dashboard Real-Time)
echo     [B] Ubah Mode Browser (Ganti ke HIDE / TAMPIL)
echo     [C] Mode Kustom (Pilih Sumber, Limit, ^& Download)
echo     [R] Reset Nomor Halaman Katalog
echo     [0] Keluar
echo.
echo ================================================================
echo.
set PILIHAN=1
set /p PILIHAN=  Pilihan Anda [1-9, F, U, D, M, B, C, R, 0, default 1]: 

if "%PILIHAN%"=="1" goto RUN_AUTO_WATCHER
if "%PILIHAN%"=="2" goto RUN_SCRAPE_ANIME
if "%PILIHAN%"=="3" goto RUN_DRY_RUN
if "%PILIHAN%"=="4" goto RUN_STREAM_PROXY
if "%PILIHAN%"=="5" goto RUN_TEST_TG
if /i "%PILIHAN%"=="f" goto RUN_REINGEST_360
if /i "%PILIHAN%"=="u" goto RUN_UPDATE_LIB
if "%PILIHAN%"=="6" goto RUN_ALL
if "%PILIHAN%"=="7" goto RUN_KURAMA
if "%PILIHAN%"=="8" goto RUN_KURAMA_MOVIE
if "%PILIHAN%"=="9" goto RUN_NEKO_SERVER_DL
if /i "%PILIHAN%"=="d" goto RUN_DUAL
if /i "%PILIHAN%"=="m" goto RUN_MONITOR
if /i "%PILIHAN%"=="p" goto RUN_AUTO_WATCHER
if /i "%PILIHAN%"=="b" goto TOGGLE_BROWSER_MODE
if /i "%PILIHAN%"=="c" goto RUN_CUSTOM
if /i "%PILIHAN%"=="r" goto RUN_RESET_HALAMAN
if /i "%PILIHAN%"=="y" goto RUN_SCRAPE_ANIME
if /i "%PILIHAN%"=="t" goto RUN_TEST_TG
if /i "%PILIHAN%"=="a" goto RUN_ANIME_TELEGRAM
if "%PILIHAN%"=="0" goto KELUAR

echo Pilihan tidak valid.
timeout /t 2 >nul
goto MENU

:RUN_ANIME_TELEGRAM
call "%~dp0start-anime-telegram.bat"
goto MENU

:RUN_AUTO_WATCHER
cls
color 0B
echo ================================================================
echo   MODE PANTAU OTOMATIS (NON-STOP TIAP 15 MENIT)
echo   - Memantau Playlist Anime Aktif Muse Indonesia + Tab /videos
echo   - Episode baru (misal Tensura rilis) otomatis dibuat di web (Auto-Add)
echo   - Otomatis unduh (1080p ^& 720p) dan upload ke Telegram CDN
echo   - Dilengkapi Watchdog Auto-Restart jika program mati mendadak
echo ================================================================
echo.
set /p "interval_min=Interval pemantauan dalam menit (Tekan Enter untuk 15 menit): "
if "%interval_min%"=="" set "interval_min=15"
set /a interval_sec=%interval_min%*60

:WATCHER_DAEMON_LOOP
echo.
echo [*] Menjalankan pemantau otomatis (Pengecekan tiap %interval_min% menit)...
echo [*] Tekan Ctrl + C jika ingin menghentikan pemantau.
echo.
python -u modules\yt_playlist_watcher.py --daemon --interval=%interval_sec% --quality=1080,720
set EXIT_CODE=%ERRORLEVEL%

:: Deteksi jika pengguna sengaja menghentikan dengan Ctrl+C (kode 3221225786 / -1073741510) atau selesai normal (0)
if %EXIT_CODE% equ 0 goto WATCHER_DAEMON_EXIT
if %EXIT_CODE% equ 3221225786 goto WATCHER_DAEMON_EXIT
if %EXIT_CODE% equ -1073741510 goto WATCHER_DAEMON_EXIT

echo.
color 0C
echo ================================================================
echo   [SISTEM KEAMANAN] Worker terhenti mendadak (Kode Keluar: %EXIT_CODE%)
echo   Auto-Restart aktif: Memulihkan tugas otomatis dalam 6 detik...
echo   (Tekan Ctrl + C sekarang jika ingin membatalkan dan kembali ke menu)
echo ================================================================
color 0B
timeout /t 6
goto WATCHER_DAEMON_LOOP

:WATCHER_DAEMON_EXIT
echo.
color 0F
pause
goto MENU

:RUN_SCRAPE_ANIME
cls
color 0B
echo ================================================================
echo   SCRAPE ANIME (PLAYLIST-FIRST + FALLBACK /VIDEOS + AUTO-ADD)
echo   - Dilengkapi Crash-Recovery & Smart Resume otomatis
echo ================================================================
echo.
echo Ketik nama anime (misal: Tensura, Doraemon, Level 2, Wind Breaker)
echo atau tempel URL video / playlist YouTube:
echo.
set "target_anime="
set /p "target_anime=Nama Anime / URL: "
if "%target_anime%"=="" goto MENU

:SCRAPE_ANIME_LOOP
echo.
echo [*] Memulai proses scraping kilat, fallback /videos, dan auto-add episode baru...
echo [*] Resolusi: Otomatis 1080p ^& 720p
python -u modules\yt_playlist_watcher.py --url="%target_anime%" --quality=1080,720
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE% equ 0 goto SCRAPE_ANIME_EXIT
if %EXIT_CODE% equ 3221225786 goto SCRAPE_ANIME_EXIT
if %EXIT_CODE% equ -1073741510 goto SCRAPE_ANIME_EXIT

echo.
color 0C
echo ================================================================
echo   [SISTEM KEAMANAN] Scraper terhenti sebelum tuntas (Kode Keluar: %EXIT_CODE%)
echo   Melanjutkan otomatis dari titik episode terakhir dalam 6 detik...
echo   (Episode yang sudah selesai tidak akan diulang)
echo   Tekan Ctrl + C jika ingin membatalkan restart.
echo ================================================================
color 0B
timeout /t 6
goto SCRAPE_ANIME_LOOP

:SCRAPE_ANIME_EXIT
echo.
color 0F
pause
goto MENU

:RUN_DRY_RUN
cls
color 0E
echo ================================================================
echo   SIMULASI PENGECEKAN (DRY-RUN / TANPA DOWNLOAD ^& TANPA UPLOAD)
echo ================================================================
echo.
echo Ketik nama anime (misal: Tensura, Doraemon, Level 2, Wind Breaker)
echo atau tempel URL video / playlist YouTube:
echo.
set "dry_anime="
set /p "dry_anime=Nama Anime / URL: "
if "%dry_anime%"=="" goto MENU

echo.
echo [*] Menjalankan simulasi pengecekan status episode...
python -u modules\yt_playlist_watcher.py --url="%dry_anime%" --dry-run
echo.
color 0F
pause
goto MENU

:RUN_STREAM_PROXY
cls
color 0A
echo ================================================================
echo   NIPNIME TELEGRAM HTTP STREAM PROXY SERVER (Port 8088)
echo   (Biarkan jendela ini tetap terbuka agar video bisa diputar di web)
echo ================================================================
echo.
python -u modules\telegram_stream_proxy.py
color 0F
pause
goto MENU

:RUN_TEST_TG
cls
color 0B
echo ================================================================
echo   MENGUJI KONEKSI BOT TELEGRAM ^& CHANNEL PRIVAT
echo ================================================================
echo.
python -u modules\yt_telegram_worker.py --test
echo.
color 0F
pause
goto MENU

:RUN_MONITOR
cls
color 0E
mode con: cols=88 lines=22
title Nipnime - Pantauan Real-Time Server Admin
if exist "Z:\tools\terop-worker\monitor.js" (
    copy /y "Z:\tools\terop-worker\monitor.js" "%~dp0monitor.js" >nul 2>&1
)
if exist "%~dp0monitor.js" (
    node "%~dp0monitor.js"
) else (
    echo [ERROR] File monitor.js tidak ditemukan!
    pause
)
color 0F
goto MENU

:RUN_NEKO_SERVER_DL
cls
color 0B
title Nipnime - NEKOPOI Server Download (CasaOS)
echo.
echo   [INFO] Menjalankan Nekopoi Auto-Download via Server CasaOS...
echo   Laptop hanya bypass tautan, server CasaOS yang mengunduh MP4 fisik.
echo   Mode Browser: %BROWSER_MODE% (%BROWSER_DESC%)
echo.
node worker.js --source=neko --download --server-download --loop --limit=30 %BROWSER_FLAG%
echo.
color 0F
pause
goto MENU

:RUN_NEKO_LOCAL_DL
cls
color 0D
title Nipnime - NEKOPOI Local Download (Drive Y:\)
echo.
echo   [INFO] Menjalankan Nekopoi Auto-Download langsung ke Drive Y:\...
echo   Mode Browser: %BROWSER_MODE% (%BROWSER_DESC%)
echo.
node worker.js --source=neko --download --loop --limit=30 %BROWSER_FLAG%
echo.
color 0F
pause
goto MENU

:RUN_DUAL
call start-dual-terminal.bat
goto MENU

:RUN_ALL
cls
color 0A
echo.
echo   [INFO] Mode Browser: %BROWSER_MODE% (%BROWSER_DESC%)
echo.
node worker.js --source=all --limit=30 --loop %BROWSER_FLAG%
echo.
color 0F
pause
goto MENU

:RUN_KURAMA
cls
color 0B
echo.
echo   [INFO] Mode Browser: %BROWSER_MODE% (%BROWSER_DESC%)
echo.
node worker.js --source=kurama --limit=30 --loop %BROWSER_FLAG%
echo.
color 0F
pause
goto MENU

:RUN_KURAMA_MOVIE
cls
color 0B
echo.
echo   [INFO] Mode Browser: %BROWSER_MODE% (%BROWSER_DESC%)
echo.
node worker.js --source=kurama --movie --limit=30 --loop %BROWSER_FLAG%
echo.
color 0F
pause
goto MENU

:RUN_NEKO_STREAM
cls
color 0D
echo.
echo   [INFO] Mode Browser: %BROWSER_MODE% (%BROWSER_DESC%)
echo.
node worker.js --source=neko --limit=30 --loop %BROWSER_FLAG%
echo.
color 0F
pause
goto MENU

:RUN_CUSTOM
cls
echo.
echo   === KONFIGURASI MODE KUSTOM ===
echo.
set SRC=neko
set /p SRC=  Pilih sumber [all / kurama / neko, default neko]: 
set LMT=30
set /p LMT=  Kapasitas limit per putaran [default 30]: 
set IS_DL=y
set /p IS_DL=  Aktifkan Auto-Download MP4 Server Admin? [y/n, default y]: 
set DL_FLAG=
if /i "%IS_DL%"=="y" (
    set SRV_DL=y
    set /p SRV_DL=  Download langsung di server CasaOS? [y/n, default y]: 
    if /i "%SRV_DL%"=="y" (
        set DL_FLAG=--download --server-download
    ) else (
        set DL_FLAG=--download
    )
)
echo.
echo   Pengaturan Mode Tampilan Browser Brave:
echo     [1] HIDE   (Latar Belakang / Senyap - Tanpa Jendela)
echo     [2] TAMPIL (Jendela Browser Terbuka di Layar)
set CUSTOM_B=1
if "%BROWSER_MODE%"=="TAMPIL" set CUSTOM_B=2
set /p CUSTOM_B=  Pilih mode browser [1/2, default %CUSTOM_B%]: 
set CUSTOM_B_FLAG=--hide
if "%CUSTOM_B%"=="2" set CUSTOM_B_FLAG=--show
echo.
echo   Menjalankan: node worker.js --source=%SRC% --limit=%LMT% %DL_FLAG% %CUSTOM_B_FLAG% --loop
echo.
node worker.js --source=%SRC% --limit=%LMT% %DL_FLAG% %CUSTOM_B_FLAG% --loop
echo.
pause
goto MENU

:TOGGLE_BROWSER_MODE
cls
echo ================================================================
echo           PENGATURAN MODE TAMPILAN BROWSER BRAVE
echo ================================================================
echo.
if "%BROWSER_MODE%"=="HIDE" (
    echo   Status Saat Ini : [ HIDE / SENYAP ]
    echo   Keterangan      : Brave berjalan di latar belakang tanpa jendela.
) else (
    echo   Status Saat Ini : [ TAMPIL ]
    echo   Keterangan      : Jendela Brave terbuka di layar laptop.
)
echo.
echo   Pilih mode tampilan browser:
echo     [1] MODE HIDE   - Senyap di Latar Belakang (Rekomendasi)
echo                       Brave berjalan di background tanpa membuka jendela sama sekali.
echo     [2] MODE TAMPIL - Buka Jendela Browser
echo                       Jendela Brave terbuka di layar untuk memantau proses scraping.
echo     [0] Batal / Kembali ke Menu
echo.
echo ================================================================
echo.
set MODE_INPUT=1
set /p MODE_INPUT=  Pilih mode [1/2/0, default 1]: 

if "%MODE_INPUT%"=="1" (
    echo HIDE> "%~dp0browser_mode.txt"
    echo [OK] Mode browser diatur ke: HIDE (Senyap di Latar Belakang)
)
if "%MODE_INPUT%"=="2" (
    echo TAMPIL> "%~dp0browser_mode.txt"
    echo [OK] Mode browser diatur ke: TAMPIL (Jendela Terbuka di Layar)
)
timeout /t 2 >nul
goto MENU

:RUN_RESET_HALAMAN
cls
call reset-halaman.bat
goto MENU

:RUN_REINGEST_360
cls
echo ================================================================
echo     PERBAIKI VIDEO 360p - RE-INGEST KE HD (720p / 1080p)
echo ================================================================
echo.
echo Script ini akan memindai video 360p di channel Telegram,
echo mengunduh resolusi HD aslinya dari YouTube, mengupload ulang,
echo memperbarui link di web Nipnime, dan membersihkan pesan 360p lama.
echo.
echo   [1] Jalankan Perbaikan Otomatis Sekarang (Unduh ^& Ganti ke HD)
echo   [2] Simulasi Dulu (Dry-Run / Cek daftar episode yang terdampak)
echo   [0] Kembali ke Menu Utama
echo.
set FIX_OPT=1
set /p FIX_OPT="  Pilihan Anda [1/2/0, default 1]: "
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

:RUN_UPDATE_LIB
cls
echo ================================================================
echo     PEMBARUAN LIBRARY WORKER ^& DEPENDENCY
echo ================================================================
echo.
echo Memperbarui yt-dlp dan dependensi worker ke versi paling baru...
echo.
python -m pip install -U yt-dlp pyrogram tgcrypto aiohttp python-dotenv
echo.
echo [OK] Seluruh library worker berhasil diperbarui!
echo.
pause
goto MENU

:KELUAR
exit /b 0
