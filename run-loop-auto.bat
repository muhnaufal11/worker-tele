@echo off
title Nipnime Remote Terop Worker (Auto Loop)
cd /d "%~dp0"

echo ================================================================
echo        NIPNIME REMOTE WORKER - AUTO LOOP RUNNER
echo ================================================================
echo.
echo Mode: Otomatis Berkelanjutan (All Sumber, Limit: 50)
echo Menghubungkan ke https://nipnime.com/api/terop...
echo.
echo Tekan Ctrl+C untuk menghentikan worker kapan saja.
echo.

:: Deteksi pengaturan mode browser dari argumen CLI, browser_mode.txt, atau .env
set BROWSER_MODE=HIDE
set B_FLAG=--hide

if exist "%~dp0browser_mode.txt" (
    findstr /i "TAMPIL" "%~dp0browser_mode.txt" >nul 2>&1
    if not errorlevel 1 set BROWSER_MODE=TAMPIL
)
if not "%BROWSER_MODE%"=="TAMPIL" if exist "%~dp0.env" (
    findstr /i "HEADLESS=false" "%~dp0.env" >nul 2>&1
    if not errorlevel 1 set BROWSER_MODE=TAMPIL
)
if "%1"=="--show" set BROWSER_MODE=TAMPIL
if "%1"=="--hide" set BROWSER_MODE=HIDE

if "%BROWSER_MODE%"=="TAMPIL" (
    set B_FLAG=--show
    echo Mode Browser: TAMPIL (Jendela Brave terbuka di layar)
) else (
    set B_FLAG=--hide
    echo Mode Browser: HIDE (Brave berjalan senyap di latar belakang)
)
echo (Untuk mengubah mode tampilan, jalankan atur-mode-browser.bat atau start-worker.bat)
echo.

node worker.js --mode=loop --source=all --limit=50 %B_FLAG%
pause
