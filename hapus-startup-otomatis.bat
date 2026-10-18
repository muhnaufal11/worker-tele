@echo off
title Hapus Auto Start Nipnime Worker
cd /d "%~dp0"

echo ================================================================
echo    MENGHAPUS NIPNIME TEROP WORKER DARI STARTUP WINDOWS
echo ================================================================
echo.

powershell -NoProfile -Command "Remove-Item -Path ([System.IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Startup\Nipnime Terop Worker.lnk')) -Force -ErrorAction SilentlyContinue"

echo [OK] Auto Start berhasil dimatikan.
echo Worker tidak akan berjalan otomatis lagi saat laptop menyala.
echo.
pause
