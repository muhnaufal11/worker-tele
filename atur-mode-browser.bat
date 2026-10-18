@echo off
chcp 65001 >nul
title Nipnime Worker - Pengaturan Mode Tampilan Browser Brave
color 0F
cd /d "%~dp0"

:CEK_STATUS
set BROWSER_MODE=HIDE
set BROWSER_DESC=Senyap di Latar Belakang (Jendela Browser Tertutup)

if exist "%~dp0browser_mode.txt" (
    findstr /i "TAMPIL" "%~dp0browser_mode.txt" >nul 2>&1
    if not errorlevel 1 (
        set BROWSER_MODE=TAMPIL
        set BROWSER_DESC=Jendela Brave Terbuka di Layar (Visual Monitor)
    )
)
if not "%BROWSER_MODE%"=="TAMPIL" if exist "%~dp0.env" (
    findstr /i "HEADLESS=false" "%~dp0.env" >nul 2>&1
    if not errorlevel 1 (
        set BROWSER_MODE=TAMPIL
        set BROWSER_DESC=Jendela Brave Terbuka di Layar (Visual Monitor)
    )
)

:MENU
cls
echo ================================================================
echo           PENGATURAN MODE TAMPILAN BROWSER BRAVE
echo                Nipnime Remote Terop Scraper
echo ================================================================
echo.
if "%BROWSER_MODE%"=="HIDE" (
    echo   Status Saat Ini : [ HIDE / SENYAP ]
    echo   Keterangan      : %BROWSER_DESC%
) else (
    echo   Status Saat Ini : [ TAMPIL ]
    echo   Keterangan      : %BROWSER_DESC%
)
echo.
echo ================================================================
echo.
echo   Pilih mode yang diinginkan:
echo.
echo     [1] MODE HIDE (Latar Belakang / Senyap - Rekomendasi)
echo         - Brave berjalan senyap tanpa membuka jendela sama sekali.
echo         - Tidak ada pop-up tab yang mengganggu aktivitas layar laptop.
echo.
echo     [2] MODE TAMPIL (Jendela Terbuka di Layar)
echo         - Jendela Brave muncul di layar laptop.
echo         - Cocok jika Anda ingin memantau visual proses scraping / bypass.
echo.
echo     [0] Selesai / Kembali
echo.
echo ================================================================
echo.
set PIL=1
if "%BROWSER_MODE%"=="HIDE" set PIL=2
set /p PIL=  Pilihan Anda [0-2, default %PIL%]: 

if "%PIL%"=="1" goto SET_HIDE
if "%PIL%"=="2" goto SET_SHOW
if "%PIL%"=="0" exit /b 0

echo   Pilihan tidak valid.
timeout /t 2 >nul
goto MENU

:SET_HIDE
set BROWSER_MODE=HIDE
set BROWSER_DESC=Senyap di Latar Belakang (Jendela Browser Tertutup)
(echo HIDE)> "%~dp0browser_mode.txt"
if exist "Z:\tools\terop-worker\" (echo HIDE)> "Z:\tools\terop-worker\browser_mode.txt" 2>nul
if exist "D:\tools\terop-worker\" (echo HIDE)> "D:\tools\terop-worker\browser_mode.txt" 2>nul
attrib -h "%~dp0.env" 2>nul
attrib -h "Z:\tools\terop-worker\.env" 2>nul
attrib -h "D:\tools\terop-worker\.env" 2>nul
node -e "const fs=require('fs'); ['%~dp0.env','Z:\\tools\\terop-worker\\.env','D:\\tools\\terop-worker\\.env'].forEach(p=>{if(fs.existsSync(p)){let c=fs.readFileSync(p,'utf8');fs.writeFileSync(p,c.replace(/HEADLESS=.*/g,'HEADLESS=true'),'utf8');}})" 2>nul
color 0A
echo.
echo   ================================================================
echo   [OK] BERHASIL! Mode Browser sekarang: HIDE (Latar Belakang)
echo        Semua worker sekarang akan berjalan senyap tanpa jendela.
echo   ================================================================
echo.
timeout /t 1 >nul
color 0F
goto CEK_STATUS

:SET_SHOW
set BROWSER_MODE=TAMPIL
set BROWSER_DESC=Jendela Brave Terbuka di Layar (Visual Monitor)
(echo TAMPIL)> "%~dp0browser_mode.txt"
if exist "Z:\tools\terop-worker\" (echo TAMPIL)> "Z:\tools\terop-worker\browser_mode.txt" 2>nul
if exist "D:\tools\terop-worker\" (echo TAMPIL)> "D:\tools\terop-worker\browser_mode.txt" 2>nul
attrib -h "%~dp0.env" 2>nul
attrib -h "Z:\tools\terop-worker\.env" 2>nul
attrib -h "D:\tools\terop-worker\.env" 2>nul
node -e "const fs=require('fs'); ['%~dp0.env','Z:\\tools\\terop-worker\\.env','D:\\tools\\terop-worker\\.env'].forEach(p=>{if(fs.existsSync(p)){let c=fs.readFileSync(p,'utf8');fs.writeFileSync(p,c.replace(/HEADLESS=.*/g,'HEADLESS=false'),'utf8');}})" 2>nul
color 0E
echo.
echo   ================================================================
echo   [OK] BERHASIL! Mode Browser sekarang: TAMPIL (Jendela Terbuka)
echo        Worker akan memunculkan jendela Brave di layar saat berjalan.
echo   ================================================================
echo.
timeout /t 1 >nul
color 0F
goto CEK_STATUS
