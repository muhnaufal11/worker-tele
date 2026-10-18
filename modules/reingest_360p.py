#!/usr/bin/env python3
"""
Nipnime Telegram Re-Ingest & Upgrade Tool
Memperbaiki video 360p yang terlanjur terupload (akibat batasan Android SABR lama),
mengunduh ulang video sumber dalam resolusi asli HD (720p / 1080p),
mengunggah ke Channel Telegram, memperbarui database Nipnime,
dan membersihkan video 360p lama.
"""

import os
import sys
import re
import time
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import aiohttp
from pyrogram import Client, utils

# Fix Pyrogram 64-bit channel ID
utils.MIN_CHANNEL_ID = -10099999999999

# Windows Unicode output
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = SCRIPT_DIR / '.env'
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

MODULES_DIR = Path(__file__).resolve().parent
if str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))

from yt_telegram_worker import (
    download_from_youtube,
    upload_to_telegram,
    submit_to_nipnime,
    match_title_with_nipnime,
    check_credentials,
    API_URL, WORKER_TOKEN,
    API_ID, API_HASH, BOT_TOKEN, CHANNEL_ID, STREAM_BASE_URL,
    log, CYAN, GREEN, YELLOW, RED, GRAY, BOLD, RESET
)

async def get_db_info_for_msg(msg_id: int):
    """Cari informasi episode di database Nipnime untuk message ID tertentu."""
    url = f"{API_URL}/find-tg-msg?msg_id={msg_id}"
    headers = {
        'X-Terop-Token': WORKER_TOKEN,
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) NipnimeWorker/2.0'
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('success'):
                        return data
    except Exception:
        pass
    return None

async def reingest_all_360p(start_id: int = 44, end_id: int = 125, dry_run: bool = False):
    if not check_credentials():
        sys.exit(1)

    print(f"\n{CYAN}{BOLD}======================================================================{RESET}")
    print(f"{CYAN}{BOLD}   NIPNIME AUTO RE-INGEST ^& UPGRADE VIDEO 360p -> HD (720p/1080p){RESET}")
    print(f"   * Target Rentang Pesan : ID {start_id} s/d {end_id}")
    print(f"   * Mode Operasi         : {'Simulasi (Dry-Run)' if dry_run else 'Aktif Unduh, Upload ^& Ganti'}")
    print(f"{CYAN}{BOLD}======================================================================{RESET}\n")

    int_channel_id = int(CHANNEL_ID)
    session_dir = SCRIPT_DIR / '.tg_sessions'
    session_dir.mkdir(exist_ok=True)

    app = Client(
        name="reingest_bot",
        api_id=int(API_ID),
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        workdir=str(session_dir)
    )

    await app.start()
    try:
        log("SCAN", f"Memindai pesan {start_id} s/d {end_id} di channel Telegram...", CYAN)
        msg_ids = list(range(start_id, end_id + 1))
        messages = await app.get_messages(int_channel_id, msg_ids)

        # Kelompokkan video 360p berdasarkan YouTube Video ID
        # Format: {yt_id: {'old_msg_ids': [44, 45], 'caption': str, 'filename': str}}
        tasks = {}
        for m in messages:
            if not m or not m.video:
                continue
            if m.video.height == 360:
                fn = m.video.file_name or ''
                match = re.match(r'^([a-zA-Z0-9_-]{11})', fn)
                if not match:
                    continue
                yt_id = match.group(1)
                if yt_id not in tasks:
                    tasks[yt_id] = {
                        'yt_id': yt_id,
                        'old_msg_ids': [],
                        'caption': m.caption or '',
                        'title': (m.caption or '').splitlines()[0] if m.caption else fn
                    }
                tasks[yt_id]['old_msg_ids'].append(m.id)

        total_unique = len(tasks)
        total_old_msgs = sum(len(t['old_msg_ids']) for t in tasks.values())
        log("SCAN", f"Ditemukan {BOLD}{total_old_msgs} pesan 360p{RESET} dari {BOLD}{total_unique} episode YouTube unik{RESET}!", GREEN)

        if total_unique == 0:
            log("DONE", "Tidak ada video 360p yang perlu diperbaiki.", GREEN)
            return

        idx = 0
        success_count = 0
        for yt_id, t in tasks.items():
            idx += 1
            yt_url = f"https://www.youtube.com/watch?v={yt_id}"
            clean_title = t['title'].encode('ascii', 'ignore').decode().strip()
            print(f"\n{CYAN}----------------------------------------------------------------------{RESET}")
            log("PROGRESS", f"[{idx}/{total_unique}] Memproses: {BOLD}{clean_title}{RESET}", CYAN)
            log("INFO", f"YouTube URL: {yt_url} | Pesan Lama: {t['old_msg_ids']}", GRAY)

            # 1. Dapatkan Episode ID di database Nipnime dari pesan lama di DB
            ep_id = None
            audio_type = 'sub'
            anime_label = ""
            for old_mid in t['old_msg_ids']:
                db_info = await get_db_info_for_msg(old_mid)
                if db_info:
                    ep_id = db_info.get('episode_id')
                    audio_type = db_info.get('audio_type', 'sub')
                    anime_label = f"{db_info.get('anime_title')} Ep {db_info.get('episode_number')}"
                    break

            if not ep_id:
                # Fallback matcher
                match_data = await match_title_with_nipnime(t['title'], auto_create=False)
                ep_info = match_data.get('episode') if match_data else None
                ep_id = ep_info.get('id') if ep_info else None
                audio_type = match_data.get('parsed', {}).get('audio_type') or (ep_info.get('audio_type') if ep_info else 'sub')

            if ep_id:
                log("MATCH", f"Episode Target: ID {ep_id} ({anime_label or clean_title}) [Audio: {audio_type}]", GREEN)
            else:
                log("WARN", f"Episode ID tidak ditemukan otomatis di DB Nipnime. Melewati update website.", YELLOW)

            if dry_run:
                log("DRY-RUN", f"[Simulasi] Siap mengunduh HD untuk Ep ID {ep_id} dan mengganti pesan {t['old_msg_ids']}.", YELLOW)
                continue

            # 2. Unduh video asli dari YouTube dalam resolusi HD (1080p / 720p asli)
            dl_info = None
            try:
                dl_info = download_from_youtube(yt_url, quality="1080")
                actual_height = dl_info.get('height', 720)
                actual_qual_str = f"{actual_height}p"
                log("DOWNLOAD", f"Berhasil mengunduh resolusi riil: {BOLD}{actual_qual_str}{RESET} ({actual_height}p)", GREEN)

                # 3. Upload ke Channel Telegram
                new_msg_id = await upload_to_telegram(app, dl_info, int_channel_id)
                new_stream_url = f"{STREAM_BASE_URL}/stream/{new_msg_id}"
                log("UPLOAD", f"Berhasil diunggah ke Telegram! ID Baru: {BOLD}{new_msg_id}{RESET}", GREEN)

                # 4. Setor ke Database Nipnime (Otomatis hapus referensi pesan 360p lama)
                if ep_id:
                    ok = await submit_to_nipnime(
                        ep_id,
                        new_stream_url,
                        quality=actual_qual_str,
                        audio_type=audio_type,
                        old_msg_ids=t['old_msg_ids']
                    )
                    if ok:
                        log("API", f"Database Nipnime berhasil diperbarui ke resolusi [{actual_qual_str}]!", GREEN)

                # 5. Hapus pesan 360p lama di Telegram agar channel bersih & hemat
                old_ids = t['old_msg_ids']
                try:
                    await app.delete_messages(int_channel_id, old_ids)
                    log("CLEANUP", f"Pesan lama {old_ids} berhasil dihapus dari Telegram.", GRAY)
                except Exception as de:
                    log("CLEANUP", f"Peringatan hapus pesan lama: {de}", YELLOW)

                success_count += 1

            except Exception as e:
                log("ERROR", f"Gagal memproses {clean_title}: {e}", RED)
            finally:
                if dl_info and 'file_path' in dl_info:
                    p = Path(dl_info['file_path'])
                    if p.exists():
                        try: p.unlink()
                        except Exception: pass

            # Jeda 3 detik antar video
            await asyncio.sleep(3)

        print(f"\n{CYAN}{BOLD}======================================================================{RESET}")
        print(f"{GREEN}{BOLD}   PROSES RE-INGEST SELESAI TUNTAS{RESET}")
        print(f"   * Berhasil Diperbarui : {success_count} / {total_unique} episode")
        print(f"{CYAN}{BOLD}======================================================================{RESET}\n")

    finally:
        await app.stop()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Nipnime Telegram Re-Ingest 360p -> HD")
    parser.add_argument('--start', type=int, default=44, help="ID pesan awal (default 44)")
    parser.add_argument('--end', type=int, default=125, help="ID pesan akhir (default 125)")
    parser.add_argument('--dry-run', action='store_true', help="Hanya simulasi tanpa unduh dan upload")
    args = parser.parse_args()

    asyncio.run(reingest_all_360p(start_id=args.start, end_id=args.end, dry_run=args.dry_run))
