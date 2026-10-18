#!/usr/bin/env python3
"""
Nipnime Telegram Setup Wizard
Menyimpan kredensial API Telegram langsung dari terminal ke file .env
(otomatis disinkronkan ke D:\tools\terop-worker\.env dan Z:\tools\terop-worker\.env).
"""

import os
import sys
import argparse
import asyncio
from pathlib import Path
from pyrogram import Client, utils

# Fix Pyrogram 64-bit channel ID support
utils.MIN_CHANNEL_ID = -10099999999999

# ANSI Colors
CYAN = '\033[96m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
GRAY = '\033[90m'
BOLD = '\033[1m'
RESET = '\033[0m'

def update_env(file_path: Path, updates: dict):
    if not file_path.exists():
        return False

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    new_lines = []
    keys_found = set()

    for line in lines:
        stripped = line.strip()
        matched = False
        for k, v in updates.items():
            if stripped.startswith(f"{k}="):
                new_lines.append(f"{k}={v}\n")
                keys_found.add(k)
                matched = True
                break
        if not matched:
            new_lines.append(line)

    for k, v in updates.items():
        if k not in keys_found:
            new_lines.append(f"{k}={v}\n")

    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    return True

async def test_telegram(api_id, api_hash, bot_token, channel_id):
    print(f"\n{CYAN}[*] Menguji validasi kunci ke server Telegram MTProto...{RESET}")
    session_dir = Path(__file__).resolve().parent.parent / '.tg_sessions'
    session_dir.mkdir(exist_ok=True)

    app = Client(
        name="nipnime_test_setup",
        api_id=int(api_id),
        api_hash=api_hash,
        bot_token=bot_token,
        workdir=str(session_dir)
    )

    await app.start()
    try:
        me = await app.get_me()
        print(f"{GREEN}[✓] Otentikasi Bot Berhasil: @{me.username} ({me.first_name}){RESET}")
        try:
            chat = await app.get_chat(int(channel_id))
            print(f"{GREEN}[✓] Akses Channel Berhasil: '{chat.title}' (ID: {chat.id}){RESET}")
            return True
        except Exception as ce:
            print(f"{RED}[!] Gagal mengakses Channel: {ce}{RESET}")
            print(f"{YELLOW}    Pastikan Bot @{me.username} sudah dimasukkan ke Channel dan dijadikan ADMINISTRATOR!{RESET}")
            return False
    except Exception as e:
        print(f"{RED}[✗] Gagal login Bot Telegram: {e}{RESET}")
        return False
    finally:
        try:
            await app.stop()
        except Exception:
            pass

def main():
    parser = argparse.ArgumentParser(description="Simpan kunci Telegram API ke .env")
    parser.add_argument('--api-id', type=str, help="Telegram API ID (angka)")
    parser.add_argument('--api-hash', type=str, help="Telegram API Hash (string)")
    parser.add_argument('--bot-token', type=str, help="Telegram Bot Token (dari @BotFather)")
    parser.add_argument('--channel-id', type=str, help="Channel ID (contoh -100xxxxxxxxxx)")

    args = parser.parse_args()

    api_id = (args.api_id or '').strip()
    api_hash = (args.api_hash or '').strip()
    bot_token = (args.bot_token or '').strip()
    channel_id = (args.channel_id or '').strip()

    if not (api_id and api_hash and bot_token and channel_id):
        print(f"\n{CYAN}{BOLD}======================================================{RESET}")
        print(f"{CYAN}{BOLD}      SETUP KUNCI TELEGRAM API - NIPNIME WORKER{RESET}")
        print(f"{CYAN}{BOLD}======================================================{RESET}\n")

        if not api_id:
            api_id = input(f"{BOLD}Masukkan TELEGRAM_API_ID (angka): {RESET}").strip()
        if not api_hash:
            api_hash = input(f"{BOLD}Masukkan TELEGRAM_API_HASH (string): {RESET}").strip()
        if not bot_token:
            bot_token = input(f"{BOLD}Masukkan TELEGRAM_BOT_TOKEN (@BotFather): {RESET}").strip()
        if not channel_id:
            channel_id = input(f"{BOLD}Masukkan TELEGRAM_CHANNEL_ID (-100...): {RESET}").strip()

    if not (api_id and api_hash and bot_token and channel_id):
        print(f"\n{RED}[ERROR] Semua kunci wajib diisi! Setup dibatalkan.{RESET}")
        sys.exit(1)

    updates = {
        'TELEGRAM_API_ID': api_id,
        'TELEGRAM_API_HASH': api_hash,
        'TELEGRAM_BOT_TOKEN': bot_token,
        'TELEGRAM_CHANNEL_ID': channel_id
    }

    env_paths = [
        Path(r'D:\tools\terop-worker\.env'),
        Path(r'Z:\tools\terop-worker\.env')
    ]

    print(f"\n{CYAN}[*] Menyimpan kunci ke file .env...{RESET}")
    for ep in env_paths:
        if ep.exists():
            if update_env(ep, updates):
                print(f"{GREEN}[✓] Berhasil disimpan di: {ep}{RESET}")
        else:
            print(f"{GRAY}[-] File tidak ditemukan (dilewati): {ep}{RESET}")

    test_ok = asyncio.run(test_telegram(api_id, api_hash, bot_token, channel_id))
    if test_ok:
        print(f"\n{GREEN}{BOLD}🎉 SELAMAT! Setup Telegram Worker 100% Selesai & Berfungsi!{RESET}\n")
    else:
        print(f"\n{YELLOW}[i] Kunci sudah disimpan. Perbaiki akses bot di channel lalu uji kembali via start-yt-telegram.bat.{RESET}\n")

if __name__ == '__main__':
    main()
