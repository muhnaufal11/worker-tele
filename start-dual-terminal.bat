@echo off
title Nipnime Dual Worker Launcher
color 0F
cd /d "%~dp0"

if exist "Z:\tools\terop-worker\worker.js" (
    copy /y "Z:\tools\terop-worker\worker.js" "%~dp0worker.js" >nul 2>&1
)

:MENU_DUAL
cls
echo ================================================================
echo           NIPNIME DUAL WORKER TERMINAL LAUNCHER
echo           Dual-Screen Multi-Tasking Scraper Setup
echo ================================================================
echo.
echo   Pilih konfigurasi tampilan browser Brave:
echo.
echo     [1] REKOMENDASI : Kurama TAMPIL + Nekopoi HIDE (18+ Hening)
echo     [2] TAMPIL SEMUA: Brave Kurama dan Brave Nekopoi Terbuka
echo     [3] HIDE SEMUA  : Background / Mode Senyap (Tanpa Browser)
echo     [4] Mode Kustom : Tentukan Tampilan dan Limit Mandiri
echo     [5] Kembali ke Menu Utama
echo.
echo ================================================================
echo.
set DUAL_OPT=1
set /p DUAL_OPT=  Pilihan Anda [1-5, default 1]: 

if "%DUAL_OPT%"=="1" goto OPT_REKOMENDASI
if "%DUAL_OPT%"=="2" goto OPT_ALL_SHOW
if "%DUAL_OPT%"=="3" goto OPT_ALL_HIDE
if "%DUAL_OPT%"=="4" goto OPT_CUSTOM
if "%DUAL_OPT%"=="5" exit /b 0

echo   Pilihan tidak valid.
timeout /t 2 >nul
goto MENU_DUAL

:OPT_REKOMENDASI
cls
echo.
set LMT=30
set /p LMT=  Kapasitas limit per putaran [default 30]: 
echo.
echo   [INFO] Menyiapkan Dual Terminal:
echo     - Terminal 1 : KURAMANIME (Tema Cyan)    - Brave Terlihat (Kiri Bawah)
echo     - Terminal 2 : NEKOPOI    (Tema Magenta) - Brave Tersembunyi (Hide 18+)
echo     - Layout     : Auto-Tiling Berdampingan Rapi (Split Screen)
echo.

start "Nipnime - KURAMANIME Worker" cmd /k "color 0B && title Nipnime - KURAMANIME Worker && node worker.js --source=kurama --loop --limit=%LMT% --show --win-x=0 --win-y=520 --win-w=960 --win-h=520"
start "Nipnime - NEKOPOI Worker" cmd /k "color 0D && title Nipnime - NEKOPOI Worker && node worker.js --source=neko --loop --limit=%LMT% --hide"

echo   Menata posisi jendela secara presisi di layar...
powershell -ExecutionPolicy Bypass -File arrange-windows.ps1 -KuramaHeadless false -NekoHeadless true
goto SELESAI_LAUNCH

:OPT_ALL_SHOW
cls
echo.
set LMT=30
set /p LMT=  Kapasitas limit per putaran [default 30]: 
echo.
echo   [INFO] Menyiapkan Dual Terminal:
echo     - Terminal 1 : KURAMANIME (Tema Cyan)    - Brave Terlihat
echo     - Terminal 2 : NEKOPOI    (Tema Magenta) - Brave Terlihat
echo     - Layout     : 4 Kotak Split Screen (2 Terminal Atas + 2 Brave Bawah)
echo.

start "Nipnime - KURAMANIME Worker" cmd /k "color 0B && title Nipnime - KURAMANIME Worker && node worker.js --source=kurama --loop --limit=%LMT% --show --win-x=0 --win-y=520 --win-w=960 --win-h=520"
start "Nipnime - NEKOPOI Worker" cmd /k "color 0D && title Nipnime - NEKOPOI Worker && node worker.js --source=neko --loop --limit=%LMT% --show --win-x=960 --win-y=520 --win-w=960 --win-h=520"

echo   Menata posisi jendela secara presisi di layar...
powershell -ExecutionPolicy Bypass -File arrange-windows.ps1 -KuramaHeadless false -NekoHeadless false
goto SELESAI_LAUNCH

:OPT_ALL_HIDE
cls
echo.
set LMT=30
set /p LMT=  Kapasitas limit per putaran [default 30]: 
echo.
echo   [INFO] Menyiapkan Dual Terminal:
echo     - Terminal 1 : KURAMANIME (Tema Cyan)    - Brave Background (Hide)
echo     - Terminal 2 : NEKOPOI    (Tema Magenta) - Brave Background (Hide)
echo     - Layout     : 2 Terminal Penuh Berdampingan Kiri dan Kanan (50/50)
echo.

start "Nipnime - KURAMANIME Worker" cmd /k "color 0B && title Nipnime - KURAMANIME Worker && node worker.js --source=kurama --loop --limit=%LMT% --hide"
start "Nipnime - NEKOPOI Worker" cmd /k "color 0D && title Nipnime - NEKOPOI Worker && node worker.js --source=neko --loop --limit=%LMT% --hide"

echo   Menata posisi jendela secara presisi di layar...
powershell -ExecutionPolicy Bypass -File arrange-windows.ps1 -KuramaHeadless true -NekoHeadless true
goto SELESAI_LAUNCH

:OPT_CUSTOM
cls
echo.
echo   ================================================================
echo                 PENGATURAN KUSTOM DUAL TERMINAL
echo   ================================================================
echo.
set LMT=30
set /p LMT=  Limit per putaran [default 30]: 
echo.
echo   Tampilkan browser Brave untuk Kuramanime?
echo     [1] Tampilkan
echo     [2] Sembunyikan (Hide)
set K_CHOICE=1
set /p K_CHOICE=  Pilihan [1/2, default 1]: 

echo.
echo   Tampilkan browser Brave untuk Nekopoi (18+)?
echo     [1] Sembunyikan (Hide - Rekomendasi)
echo     [2] Tampilkan
set N_CHOICE=1
set /p N_CHOICE=  Pilihan [1/2, default 1]: 

set K_FLAG=--show
set K_HL=false
if "%K_CHOICE%"=="2" (
    set K_FLAG=--hide
    set K_HL=true
)

set N_FLAG=--hide
set N_HL=true
if "%N_CHOICE%"=="2" (
    set N_FLAG=--show
    set N_HL=false
)

echo.
echo   [INFO] Menjalankan Dual Terminal Kustom...

if "%K_HL%"=="false" (
    start "Nipnime - KURAMANIME Worker" cmd /k "color 0B && title Nipnime - KURAMANIME Worker && node worker.js --source=kurama --loop --limit=%LMT% --show --win-x=0 --win-y=520 --win-w=960 --win-h=520"
) else (
    start "Nipnime - KURAMANIME Worker" cmd /k "color 0B && title Nipnime - KURAMANIME Worker && node worker.js --source=kurama --loop --limit=%LMT% --hide"
)

if "%N_HL%"=="false" (
    start "Nipnime - NEKOPOI Worker" cmd /k "color 0D && title Nipnime - NEKOPOI Worker && node worker.js --source=neko --loop --limit=%LMT% --show --win-x=960 --win-y=520 --win-w=960 --win-h=520"
) else (
    start "Nipnime - NEKOPOI Worker" cmd /k "color 0D && title Nipnime - NEKOPOI Worker && node worker.js --source=neko --loop --limit=%LMT% --hide"
)

echo   Menata posisi jendela secara presisi di layar...
powershell -ExecutionPolicy Bypass -File arrange-windows.ps1 -KuramaHeadless %K_HL% -NekoHeadless %N_HL%
goto SELESAI_LAUNCH

:SELESAI_LAUNCH
echo.
echo   Kedua terminal telah aktif dan diposisikan secara otomatis.
echo   Jendela launcher ini akan tertutup dalam 4 detik...
timeout /t 4 >nul
exit /b 0
