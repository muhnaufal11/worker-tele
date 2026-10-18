#!/usr/bin/env bash
# ======================================================================
#   N I P N I M E   W O R K E R   -   C O D E S P A C E   L A U N C H E R
#   High-Speed Cloud Engine for Anime Ongoing, Watermark & Video Ingest
# ======================================================================

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ANSI Colors
CYAN='\033[96m'
GREEN='\033[92m'
YELLOW='\033[93m'
RED='\033[91m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${CYAN}======================================================================${NC}"
echo -e "${BOLD}${CYAN}   N I P N I M E   W O R K E R   -   G I T H U B   C O D E S P A C E  ${NC}"
echo -e "${CYAN}       Multi-Source Auto-Release, Watermark & Video Engine             ${NC}"
echo -e "${CYAN}======================================================================${NC}"
echo ""

# 1. Pastikan file .env ada
if [ ! -f ".env" ]; then
    if [ -f ".env.codespace.example" ]; then
        echo -e "${YELLOW}[*] Menyiapkan .env dari template Codespaces...${NC}"
        cp .env.codespace.example .env
        echo -e "${GREEN}[OK] File .env berhasil dibuat.${NC}"
    else
        cat << 'EOF' > .env
API_URL=https://nipnime.com/api/terop
WORKER_TOKEN=nipnime_terop_secret_key_2026
WORKER_ROLE=codespace
TELEGRAM_API_ID=37009424
TELEGRAM_API_HASH=9e15f809ab7f895bcd0786c36881599d
TELEGRAM_BOT_TOKEN=8613506821:AAHD74hykC4SKHUdtFqirTZTcz7MJq7k8cI
TELEGRAM_CHANNEL_ID=-1004428873400
TELEGRAM_STREAM_BASE_URL=https://nipnime.com/tg-stream
HEADLESS=true
EOF
        echo -e "${GREEN}[OK] File .env default berhasil dibuat.${NC}"
    fi
fi

# Pastikan WORKER_ROLE terdefinisi di environment
export WORKER_ROLE="codespace"
export PYTHONUNBUFFERED="1"

# 2. Cek Python Binary
PY_CMD=""
if command -v python3 >/dev/null 2>&1; then
    PY_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PY_CMD="python"
else
    echo -e "${RED}[ERROR] Python tidak ditemukan di sistem ini!${NC}"
    exit 1
fi

PY_VER=$($PY_CMD --version 2>&1)
echo -e "${GREEN}[OK] Menggunakan ${PY_VER}${NC}"

# 3. Cek Library Python
echo -e "${YELLOW}[*] Memeriksa paket Python...${NC}"
if ! $PY_CMD -c "import pyrogram, requests, aiohttp, psutil, PIL, dotenv" >/dev/null 2>&1; then
    echo -e "${YELLOW}[*] Menginstall dependencies Python...${NC}"
    if [ -f "requirements.txt" ]; then
        $PY_CMD -m pip install -q -r requirements.txt
    else
        $PY_CMD -m pip install -q pyrogram requests aiohttp psutil pillow python-dotenv TgCrypto-pyrofork cryptography
    fi
    echo -e "${GREEN}[OK] Dependencies Python terpasang.${NC}"
else
    echo -e "${GREEN}[OK] Seluruh library Python siap (Pyrogram, Aiohttp, PIL, TgCrypto).${NC}"
fi

# 4. Cek FFmpeg
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo -e "${YELLOW}[!] FFmpeg belum terpasang di sistem PATH.${NC}"
    if command -v sudo >/dev/null 2>&1; then
        echo -e "${YELLOW}[*] Memasang FFmpeg via apt...${NC}"
        sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg >/dev/null 2>&1 || true
    fi
fi

if command -v ffmpeg >/dev/null 2>&1; then
    echo -e "${GREEN}[OK] FFmpeg siap.$(command -v ffmpeg)${NC}"
else
    echo -e "${YELLOW}[WARN] FFmpeg belum tersedia. Ekstraksi audio/watermark video mungkin terbatas.${NC}"
fi

# 5. Cek 7-Zip (7z / 7zz)
if [ -f "bin/7zz" ]; then
    chmod +x bin/7zz 2>/dev/null || true
    echo -e "${GREEN}[OK] Standalone 7zz Linux siap di bin/7zz${NC}"
elif ! command -v 7z >/dev/null 2>&1 && ! command -v 7zz >/dev/null 2>&1; then
    if command -v sudo >/dev/null 2>&1; then
        sudo apt-get install -y -qq p7zip-full >/dev/null 2>&1 || true
    fi
fi

# 6. Mode Argumen CLI Langsung (jika script dipanggil dengan parameter, misal --daemon)
SCRIPT_FILE="modules/anime_telegram_worker.py"
if [ ! -f "$SCRIPT_FILE" ] && [ -f "anime_telegram_worker.py" ]; then
    SCRIPT_FILE="anime_telegram_worker.py"
fi

if [ $# -gt 0 ]; then
    echo -e "${CYAN}[*] Menjalankan perintah: $PY_CMD -u $SCRIPT_FILE $@${NC}"
    exec $PY_CMD -u "$SCRIPT_FILE" "$@"
fi

# 7. Menu Interaktif
show_menu() {
    echo ""
    echo -e "${BOLD}${CYAN}======================================================================${NC}"
    echo -e "${BOLD}  PILIHAN MENU CODESPACE WORKER:${NC}"
    echo -e "  ${GREEN}[1] JALANKAN WORKER UTAMA (Daemon 24/7 + Watchdog Auto-Restart)${NC}"
    echo -e "  ${YELLOW}[2] TEST SCAN FEED TERBARU (AnimeSail vs Kurama vs NontonAnimeID)${NC}"
    echo -e "  ${YELLOW}[3] CEK KONEKSI TELEGRAM & NIPNIME API${NC}"
    echo -e "  ${YELLOW}[4] CEK STATUS EPISODE & RESOLUSI ONGOING${NC}"
    echo -e "  ${CYAN}[5] JALANKAN SCRAPER KURAMANIME & NEKOPOI (Puppeteer Headless)${NC}"
    echo -e "  ${RED}[0] Keluar${NC}"
    echo -e "${BOLD}${CYAN}======================================================================${NC}"
    read -p "Pilih opsi [1/2/3/4/5/0]: " PILIH
}

run_daemon() {
    clear
    echo -e "${CYAN}======================================================================${NC}"
    echo -e "${BOLD}${GREEN}  WORKER BERJALAN DI GITHUB CODESPACES (DAEMON 24/7 NON-STOP)${NC}"
    echo -e "${CYAN}======================================================================${NC}"
    read -p "Jumlah download paralel [Tekan Enter untuk 2]: " CONC
    CONC=${CONC:-2}

    echo ""
    echo -e "${GREEN}[*] Worker dimulai dengan concurrency: $CONC (Watchdog Aktif)...${NC}"
    echo -e "${YELLOW}[TIPS] Pantau status worker di: https://nipnime.com/admin/ongoing-watcher${NC}"
    echo -e "${YELLOW}[INFO] Tekan Ctrl+C untuk menghentikan.${NC}"
    echo ""

    while true; do
        $PY_CMD -u "$SCRIPT_FILE" --daemon --interval=0 --concurrency="$CONC" --role=codespace
        EXIT_CODE=$?
        echo ""
        echo -e "${RED}[WATCHDOG] Worker terhenti (Exit Code: $EXIT_CODE). Restart otomatis dalam 5 detik...${NC}"
        sleep 5
    done
}

run_scraper() {
    clear
    echo -e "${CYAN}======================================================================${NC}"
    echo -e "${BOLD}${CYAN}  SCRAPER KURAMANIME & NEKOPOI (PUPPETEER HEADLESS)${NC}"
    echo -e "${CYAN}======================================================================${NC}"
    if command -v node >/dev/null 2>&1 && [ -f "worker.js" ]; then
        node worker.js --source=all --loop --hide
    else
        echo -e "${RED}[ERROR] Node.js atau worker.js tidak ditemukan!${NC}"
    fi
}

while true; do
    show_menu
    case "$PILIH" in
        1)
            run_daemon
            ;;
        2)
            $PY_CMD -u "$SCRIPT_FILE" --test-scan --role=codespace
            read -p "Tekan Enter untuk kembali ke menu..."
            ;;
        3)
            $PY_CMD -u "$SCRIPT_FILE" --test-conn --role=codespace
            read -p "Tekan Enter untuk kembali ke menu..."
            ;;
        4)
            $PY_CMD -u "$SCRIPT_FILE" --view-state --role=codespace
            read -p "Tekan Enter untuk kembali ke menu..."
            ;;
        5)
            run_scraper
            read -p "Tekan Enter untuk kembali ke menu..."
            ;;
        0)
            echo "Keluar."
            exit 0
            ;;
        *)
            echo -e "${RED}Pilihan tidak valid!${NC}"
            ;;
    esac
done
