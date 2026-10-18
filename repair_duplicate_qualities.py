#!/usr/bin/env python3
"""
Repair & Re-Ingest Tool for Duplicate Quality Episodes in Nipnime
=================================================================
Mengunduh ulang resolusi asli (480p, 360p, dan 1080p jika tersedia)
dari Kuramanime / AnimeSail / NontonAnimeID menggunakan parser baru yang akurat,
mengunggah ke Telegram Channel, memperbarui database Nipnime, dan
menghapus pesan Telegram lama yang kembar / redundan.
"""

import os
import sys
import re
import time
import asyncio
import html
import subprocess
from pathlib import Path
from dotenv import load_dotenv
import aiohttp
from pyrogram import Client, utils

utils.MIN_CHANNEL_ID = -10099999999999

SCRIPT_DIR = Path(__file__).resolve().parent
MODULES_DIR = SCRIPT_DIR / "modules"
if str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import anime_telegram_worker as w

TARGETS = [
    {
        "anime_title": "Tantei wa Mou, Shindeiru. Season 2",
        "episode_number": 1,
        "episode_id": 213893,
        "bad_msgs": {"360p": 1391, "480p": 1392, "1080p": 1393}
    },
    {
        "anime_title": "Black Clover 2nd Season",
        "episode_number": 1,
        "episode_id": 207858,
        "bad_msgs": {"360p": 1397, "480p": 1396, "1080p": 1395}
    },
    {
        "anime_title": "Doumo, Suki na Hito ni Horegusuri wo Irai sareta Majo desu.",
        "episode_number": 1,
        "episode_id": 211084,
        "bad_msgs": {"360p": 1390, "480p": 1389, "1080p": 1387}
    },
    {
        "anime_title": "Psyren",
        "episode_number": 1,
        "episode_id": 211094,
        "bad_msgs": {"360p": 1386, "480p": 1385, "1080p": 1383}
    },
    {
        "anime_title": "Tensei shitara Ken deshita 2",
        "episode_number": 2,
        "episode_id": 214005,
        "bad_msgs": {"360p": 1365, "480p": 1364, "1080p": 1363}
    },
    {
        "anime_title": "Tensei shitara Ken deshita 2",
        "episode_number": 1,
        "episode_id": 202699,
        "bad_msgs": {"360p": 1366, "480p": 1367, "1080p": 1369}
    },
    {
        "anime_title": "Dark Summoner to Dekiteiru",
        "episode_number": 1,
        "episode_id": 209725,
        "bad_msgs": {"360p": 1374, "480p": 1373, "1080p": 1371}
    },
    {
        "anime_title": "Mahou Shoujo Ikusei Keikaku: Restart",
        "episode_number": 1,
        "episode_id": 211349,
        "bad_msgs": {"360p": 1375, "480p": 1376, "1080p": 1378}
    },
    {
        "anime_title": "Shin Tennis no Oujisama: U-17 World Cup Kesshou Member Ketteisen",
        "episode_number": 2,
        "episode_id": 214239,
        "bad_msgs": {"360p": 1382, "480p": 1381, "1080p": 1380}
    },
    {
        "anime_title": "Magic Knight Rayearth (2026)",
        "episode_number": 1,
        "episode_id": 213995,
        "bad_msgs": {"360p": 1361, "480p": 1360}
    }
]

async def delete_db_server_by_msg_id(session: aiohttp.ClientSession, msg_id: int):
    """Hapus video_servers di MySQL Nipnime via API berdasarkan Telegram message ID."""
    try:
        url = f"{w.API_URL}/delete-server"
        headers = {'X-Terop-Token': w.WORKER_TOKEN, 'Accept': 'application/json'}
        async with session.post(url, json={'msg_id': msg_id}, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            data = await resp.json()
            return data.get('success', False)
    except Exception as e:
        print(f"Failed deleting server for msg {msg_id}: {e}")
        return False

async def repair_all():
    print(f"\n{w.CYAN}{w.BOLD}======================================================================{w.RESET}")
    print(f"{w.CYAN}{w.BOLD}   NIPNIME AUTO REPAIR: RE-INGEST DUPLICATE RESOLUTIONS               {w.RESET}")
    print(f"{w.CYAN}{w.BOLD}======================================================================{w.RESET}\n")

    session_dir = SCRIPT_DIR / ".tg_sessions"
    session_dir.mkdir(exist_ok=True)

    client = Client(
        name="repair_worker_client",
        api_id=int(w.API_ID),
        api_hash=w.API_HASH,
        bot_token=w.BOT_TOKEN,
        workdir=str(session_dir)
    )

    await client.start()
    w.log("AUTH", f"Telegram terhubung! Channel: {w.CHANNEL_ID}", w.GREEN)

    state = w.load_ongoing_state()

    async with aiohttp.ClientSession() as session:
        for idx, t in enumerate(TARGETS, 1):
            anime_title = t["anime_title"]
            ep_num = t["episode_number"]
            ep_id = t["episode_id"]
            bad_msgs = t["bad_msgs"]

            print(f"\n{w.CYAN}----------------------------------------------------------------------{w.RESET}")
            w.log("TARGET", f"[{idx}/{len(TARGETS)}] Memproses: {w.BOLD}{anime_title} Ep {ep_num}{w.RESET} (ID: {ep_id})", w.CYAN)

            # 1. Cari seluruh kualitas asli dari sumber
            found_qualities = await w.check_episode_on_all_sources(session, anime_title, ep_num)
            found_qualities = found_qualities or {}
            avail_q = list(found_qualities.keys())
            w.log("FOUND", f"Resolusi riil tersedia di sumber: {avail_q}", w.GREEN if avail_q else w.YELLOW)

            # State key
            clean_t = re.sub(r'[^a-zA-Z0-9]+', ' ', anime_title).strip().lower()
            state_key = f"{clean_t}:{ep_num}"
            ep_state = state.get(state_key, {})
            completed_q = set(ep_state.get('completed_qualities', []))

            # 2. Perbaiki 480p dan 360p
            for q in ['480p', '360p']:
                old_mid = bad_msgs.get(q)
                if q in found_qualities:
                    q_info = found_qualities[q]
                    q_url = q_info['url']
                    q_host = q_info['host']
                    q_src = q_info.get('source', 'Kuramanime')

                    w.log("DOWNLOAD", f"Mengunduh resolusi riil [{q}] dari {q_src} ({q_host})...", w.CYAN)
                    slug_title = re.sub(r'[^a-zA-Z0-9]+', '-', anime_title).strip('-').lower()
                    fn = f"{slug_title}_ep{ep_num}_{q}.mp4"
                    local_path = w.TEMP_DOWNLOAD_DIR / fn

                    ok_dl = await w.download_file(
                        url=q_url,
                        dest_path=local_path,
                        quality=q
                    )

                    if ok_dl and local_path.exists() and local_path.stat().st_size > 500000:
                        mb = local_path.stat().st_size / (1024 * 1024)
                        w.log("DONE", f"Selesai unduh [{q}]: {fn} ({mb:.1f} MB)", w.GREEN)

                        w.log("UPLOAD", f"Mengunggah [{q}] ke Telegram Channel...", w.CYAN)
                        source_info = f"{q_src} ({q_host})"
                        new_mid = await w.upload_video_to_telegram(
                            client=client,
                            file_path=local_path,
                            anime_title=anime_title,
                            episode_num=ep_num,
                            quality=q,
                            source_info=source_info
                        )

                        # Submit ke Nipnime
                        submit_ok = await w.submit_to_nipnime(session, ep_id, q, new_mid, old_msg_ids=[old_mid] if old_mid else None)
                        if submit_ok:
                            w.log("API", f"✓ Sukses perbarui link server Nipnime [{q}] -> Msg ID {new_mid}!", w.GREEN)
                            completed_q.add(q)

                        # Hapus pesan lama kembar dari Telegram
                        if old_mid and old_mid != new_mid:
                            try:
                                await client.delete_messages(int(w.CHANNEL_ID), [old_mid])
                                w.log("CLEANUP", f"✓ Pesan lama #{old_mid} ({q}) berhasil dihapus dari Telegram!", w.GRAY)
                            except Exception as de:
                                w.log("CLEANUP", f"Peringatan hapus pesan lama #{old_mid}: {de}", w.YELLOW)

                        # Bersihkan file lokal
                        try: local_path.unlink()
                        except Exception: pass
                    else:
                        w.log("WARN", f"Gagal unduh resolusi asli [{q}], melewati...", w.YELLOW)

            # 3. Tangani 1080p
            old_1080 = bad_msgs.get('1080p')
            if old_1080:
                if '1080p' in found_qualities:
                    # Ada 1080p asli di salah satu sumber!
                    q_info = found_qualities['1080p']
                    q_url = q_info['url']
                    q_host = q_info['host']
                    q_src = q_info.get('source', 'AnimeSail')

                    w.log("DOWNLOAD", f"Mengunduh resolusi riil [1080p] dari {q_src} ({q_host})...", w.CYAN)
                    slug_title = re.sub(r'[^a-zA-Z0-9]+', '-', anime_title).strip('-').lower()
                    fn = f"{slug_title}_ep{ep_num}_1080p.mp4"
                    local_path = w.TEMP_DOWNLOAD_DIR / fn

                    ok_dl = await w.download_file(
                        url=q_url,
                        dest_path=local_path,
                        quality='1080p'
                    )

                    if ok_dl and local_path.exists() and local_path.stat().st_size > 500000:
                        mb = local_path.stat().st_size / (1024 * 1024)
                        w.log("DONE", f"Selesai unduh [1080p]: {fn} ({mb:.1f} MB)", w.GREEN)

                        w.log("UPLOAD", f"Mengunggah [1080p] ke Telegram Channel...", w.CYAN)
                        source_info = f"{q_src} ({q_host})"
                        new_mid = await w.upload_video_to_telegram(
                            client=client,
                            file_path=local_path,
                            anime_title=anime_title,
                            episode_num=ep_num,
                            quality='1080p',
                            source_info=source_info
                        )

                        submit_ok = await w.submit_to_nipnime(session, ep_id, '1080p', new_mid, old_msg_ids=[old_1080] if old_1080 else None)
                        if submit_ok:
                            w.log("API", f"✓ Sukses perbarui link server Nipnime [1080p] -> Msg ID {new_mid}!", w.GREEN)
                            completed_q.add('1080p')

                        if old_1080 != new_mid:
                            try:
                                await client.delete_messages(int(w.CHANNEL_ID), [old_1080])
                                w.log("CLEANUP", f"✓ Pesan lama #{old_1080} (fake 1080p) dihapus dari Telegram!", w.GRAY)
                            except Exception as de:
                                w.log("CLEANUP", f"Peringatan hapus pesan lama #{old_1080}: {de}", w.YELLOW)

                        try: local_path.unlink()
                        except Exception: pass
                else:
                    # Sumber tidak memiliki 1080p! Bersihkan server palsu & pesan fake 1080p
                    w.log("CLEANUP", f"Sumber tidak memiliki 1080p asli. Menghapus fake 1080p (Msg #{old_1080})...", w.YELLOW)
                    try:
                        await client.delete_messages(int(w.CHANNEL_ID), [old_1080])
                        w.log("CLEANUP", f"✓ Pesan Telegram #{old_1080} (fake 1080p) berhasil dihapus!", w.GRAY)
                    except Exception as de:
                        w.log("CLEANUP", f"Peringatan hapus pesan #{old_1080}: {de}", w.YELLOW)

                    await delete_db_server_by_msg_id(session, old_1080)
                    completed_q.discard('1080p')
                    w.log("API", f"✓ Server palsu [Cloud 1080p] telah dihapus dari database Nipnime!", w.GREEN)

            # Update ongoing state
            if state_key in state:
                state[state_key]['completed_qualities'] = sorted(list(completed_q))
                state[state_key]['missing_qualities'] = [q for q in ['1080p', '720p', '480p', '360p'] if q not in completed_q]
                if not state[state_key]['missing_qualities']:
                    state[state_key]['status'] = 'complete'
                w.safe_write_json(w.ONGOING_QUALITY_STATE_FILE, state)

            await asyncio.sleep(2)

    await client.stop()
    print(f"\n{w.CYAN}{w.BOLD}======================================================================{w.RESET}")
    print(f"{w.GREEN}{w.BOLD}   SELURUH PERBAIKAN & RE-INGEST SELESAI TUNTAS!                      {w.RESET}")
    print(f"{w.CYAN}{w.BOLD}======================================================================{w.RESET}\n")

if __name__ == "__main__":
    asyncio.run(repair_all())
