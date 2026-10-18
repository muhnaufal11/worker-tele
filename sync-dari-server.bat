@echo off
chcp 65001 >nul
title Sinkronisasi Terop Worker (Server Z: -> Laptop D:)
color 0A
cd /d "%~dp0"

echo ================================================================
echo   SINKRONISASI TEROP WORKER (Server Z: -^> Laptop D:)
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

echo Menyinkronkan file script dari Z:\tools\terop-worker ke "%CURR_DIR%"...
robocopy "Z:\tools\terop-worker" "%CURR_DIR%" /XD node_modules .git /XF .env /XO /NJH /NJS /NDL

echo.
echo ================================================================
echo   Sinkronisasi selesai! File worker di laptop sudah ter-update.
echo ================================================================
echo.
pause
