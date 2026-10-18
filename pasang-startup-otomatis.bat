@echo off
title Pasang Auto Start Nipnime Worker
cd /d "%~dp0"

echo ================================================================
echo    MEMASANG NIPNIME TEROP WORKER KE STARTUP WINDOWS
echo ================================================================
echo.
echo Worker akan otomatis berjalan setiap kali laptop dinyalakan atau login.
echo.

powershell -NoProfile -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut([System.IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Startup\Nipnime Terop Worker.lnk')); $s.TargetPath='%~dp0run-loop-auto.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save();"

if %errorlevel% equ 0 (
    echo [OK] Berhasil dipasang ke folder Startup Windows.
    echo Sekarang setiap kali laptop dinyalakan, worker akan langsung berjalan otomatis.
) else (
    echo [ERROR] Gagal membuat shortcut startup.
)

echo.
pause
