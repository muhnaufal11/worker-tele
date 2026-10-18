#!/usr/bin/env bash
set -e

echo "======================================================"
echo "    N I P N I M E   W O R K E R   -   S E T U P       "
echo "======================================================"

echo "[1/4] Installing system dependencies (FFmpeg, 7-Zip, Libraries)..."
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg p7zip-full libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 libasound2 >/dev/null 2>&1 || sudo apt-get install -y ffmpeg p7zip-full

echo "[2/4] Installing Python packages (Pyrogram, TgCrypto, Aiohttp)..."
pip install --no-cache-dir -r requirements.txt

echo "[3/4] Preparing binary permissions..."
chmod +x start-codespace.sh 2>/dev/null || true
if [ -f "bin/7zz" ]; then
    chmod +x bin/7zz 2>/dev/null || true
fi

echo "[4/4] Checking configuration (.env)..."
if [ ! -f ".env" ] && [ -f ".env.codespace.example" ]; then
    cp .env.codespace.example .env
    echo "[OK] Created initial .env configuration."
fi

if [ -f "package.json" ]; then
    echo "[*] Installing Node.js packages (Puppeteer scraper support)..."
    npm install --no-audit --prefer-offline 2>/dev/null || true
fi

echo "======================================================"
echo " [OK] Setup Selesai! Jalankan: ./start-codespace.sh   "
echo "======================================================"
