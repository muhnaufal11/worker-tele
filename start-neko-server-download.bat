@echo off
chcp 65001 >nul
title Nipnime - NEKOPOI Worker (Server-Side Auto Download di CasaOS)
color 0B
cd /d "%~dp0"

if exist "Z:\tools\terop-worker\worker.js" (
    copy /y "Z:\tools\terop-worker\worker.js" "%~dp0worker.js" >nul 2>&1
)

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
    echo   [INFO] Mode Browser: TAMPIL (Jendela Brave terbuka di layar)
) else (
    set B_FLAG=--hide
    echo   [INFO] Mode Browser: HIDE (Brave berjalan senyap di latar belakang)
)
echo   (Untuk mengubah mode tampilan, jalankan atur-mode-browser.bat atau start-worker.bat)
echo.

node worker.js --source=neko --download --server-download --loop --limit=30 %B_FLAG%
pause
