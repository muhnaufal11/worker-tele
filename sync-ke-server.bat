@echo off
chcp 65001 >nul
title Sinkronisasi Terop Worker (Laptop D: -> Server Z:)
color 0B
cd /d "%~dp0"

echo ================================================================
echo   SINKRONISASI TEROP WORKER (Laptop D: -^> Server Z:)
echo ================================================================
echo.

if not exist "Z:\tools\terop-worker" (
    echo [GAGAL] Drive Z: tidak terhubung atau server tidak aktif.
    echo Pastikan Samba/Network Share Z: sudah terpasang.
    pause
    exit /b 1
)

set "CURR_DIR=%~dp0"
if "%CURR_DIR:~-1%"=="\" set "CURR_DIR=%CURR_DIR:~0,-1%"

echo Menyalin file script dari "%CURR_DIR%" ke Z:\tools\terop-worker...
robocopy "%CURR_DIR%" "Z:\tools\terop-worker" /XD node_modules .git /XF .env /NJH /NJS /NDL

echo.
echo ================================================================
echo   Sinkronisasi ke server selesai!
echo ================================================================
echo.
pause
