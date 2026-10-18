@echo off
chcp 65001 >nul
title Reset Halaman Scraper Nipnime
cd /d "%~dp0"
node worker.js --reset-page
pause
