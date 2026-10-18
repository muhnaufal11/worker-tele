@echo off
chcp 65001 >nul
mode con: cols=88 lines=22
title Nipnime - Pantauan Real-Time Server Admin
color 0F
cd /d "%~dp0"

:: Sinkronkan monitor.js dari Z:\ jika tersedia
if exist "Z:\tools\terop-worker\monitor.js" (
    copy /y "Z:\tools\terop-worker\monitor.js" "%~dp0monitor.js" >nul 2>&1
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
    echo [OK] File .env berhasil dibuat.
)

:: Jalankan monitor realtime (Zero dependencies, native Node.js fetch)
node monitor.js

if %errorlevel% neq 0 (
    echo.
    echo [INFO] Monitor dihentikan.
    pause
)
