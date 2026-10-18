#!/usr/bin/env python3
"""
Nipnime YouTube to Telegram Ingest Worker
Mengunduh video anime dari YouTube (Muse Indonesia / Ani-One Asia / Custom URL),
mengunggah ke Channel Telegram Privat (MTProto 2GB max),
dan menyetorkan URL streaming ke server Nipnime (https://nipnime.com/api/terop/submit).
"""

import os
import sys
import re
import time
import json
import asyncio
import argparse
import shutil
from pathlib import Path

# Pastikan output konsol Windows mendukung Unicode / UTF-8
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from dotenv import load_dotenv
import aiohttp
from yt_dlp import YoutubeDL
from pyrogram import Client, utils

# Fix Pyrogram 64-bit channel ID support (Telegram channel ID > 2 miliar)
utils.MIN_CHANNEL_ID = -10099999999999

# Load .env dari root terop-worker
ENV_PATH = Path(__file__).resolve().parent.parent / '.env'
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

# Konfigurasi Nipnime API
API_URL = os.getenv('API_URL', 'https://nipnime.com/api/terop')
WORKER_TOKEN = os.getenv('WORKER_TOKEN', 'nipnime_terop_secret_key_2026')

# Konfigurasi Telegram
API_ID = os.getenv('TELEGRAM_API_ID', '').strip()
API_HASH = os.getenv('TELEGRAM_API_HASH', '').strip()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID', '').strip()
STREAM_BASE_URL = os.getenv('TELEGRAM_STREAM_BASE_URL', 'http://localhost:8088').rstrip('/')

# Deteksi binary FFmpeg lokal terop-worker
SCRIPT_DIR = Path(__file__).resolve().parent.parent
LOCAL_FFMPEG = SCRIPT_DIR / 'bin' / 'ffmpeg.exe'
FFMPEG_PATH = str(LOCAL_FFMPEG) if LOCAL_FFMPEG.exists() else 'ffmpeg'

# Direktori unduhan sementara lokal
TEMP_DOWNLOAD_DIR = SCRIPT_DIR / 'temp_videos'
TEMP_DOWNLOAD_DIR.mkdir(exist_ok=True)

# ANSI Colors
CYAN = '\033[96m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
GRAY = '\033[90m'
BOLD = '\033[1m'
RESET = '\033[0m'

def log(tag, msg, color=CYAN):
    t = time.strftime('%H:%M:%S')
    print(f"{GRAY}[{t}]{RESET} {color}{BOLD}[{tag}]{RESET} {msg}")

def check_credentials():
    missing = []
    if not API_ID: missing.append("TELEGRAM_API_ID")
    if not API_HASH: missing.append("TELEGRAM_API_HASH")
    if not BOT_TOKEN: missing.append("TELEGRAM_BOT_TOKEN")
    if not CHANNEL_ID: missing.append("TELEGRAM_CHANNEL_ID")

    if missing:
        log("ERROR", f"Kredensial Telegram belum lengkap di .env: {', '.join(missing)}", RED)
        log("TIPS", "Buka file .env di folder terop-worker dan masukkan kunci Anda.", YELLOW)
        return False
    return True

def auto_update_dependencies():
    """Memeriksa dan memperbarui yt-dlp secara otomatis agar tidak ketinggalan proteksi YouTube."""
    try:
        import subprocess
        log("UPDATE", "Memeriksa pembaruan yt-dlp ke versi terbaru...", GRAY)
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if "Successfully installed" in res.stdout:
            log("UPDATE", "yt-dlp berhasil diperbarui ke versi terbaru!", GREEN)
        else:
            log("UPDATE", "yt-dlp sudah menggunakan versi paling mutakhir.", GREEN)
    except Exception as e:
        log("UPDATE", f"Peringatan cek update: {e}", YELLOW)

def download_from_youtube(video_url: str, quality="1080"):
    log("DOWNLOAD", f"Mengekstrak & mengunduh resolusi [{quality}p]: {video_url}")
    out_template = str(TEMP_DOWNLOAD_DIR / f'%(id)s_{quality}p.%(ext)s')

    # Deteksi JavaScript runtime (Node.js) untuk menyelesaikan YouTube n-challenge
    node_path = shutil.which('node') or (r'C:\Program Files\nodejs\node.exe' if Path(r'C:\Program Files\nodejs\node.exe').exists() else None)
    js_runtimes = {'node': {'path': str(node_path)}} if node_path else {}

    ydl_opts = {
        'format': f'bestvideo[height<={quality}]+bestaudio[ext=m4a]/bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
        'outtmpl': out_template,
        'merge_output_format': 'mp4',
        'ffmpeg_location': FFMPEG_PATH,
        'quiet': True,
        'no_warnings': True,
        'retries': 10,
        'fragment_retries': 10,
        'retry_sleep': 3,
        'remote_components': ['ejs:github'],
    }
    if js_runtimes:
        ydl_opts['js_runtimes'] = js_runtimes

    max_retries = 3
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                title = info.get('title', 'Anime Episode')
                duration = info.get('duration', 0)
                video_id = info.get('id')
                width = info.get('width', 1920)
                height = info.get('height') or (int(quality) if str(quality).isdigit() else 1080)
                
                final_file = TEMP_DOWNLOAD_DIR / f"{video_id}_{quality}p.mp4"
                if not final_file.exists():
                    files = list(TEMP_DOWNLOAD_DIR.glob(f"{video_id}_{quality}p.*"))
                    if files:
                        final_file = files[0]
                    else:
                        final_file = TEMP_DOWNLOAD_DIR / f"{video_id}.mp4"

            log("DOWNLOAD", f"Unduhan [{height}p] selesai: {title} ({final_file.stat().st_size / (1024*1024):.1f} MB)", GREEN)
            return {
                'file_path': str(final_file),
                'title': title,
                'duration': duration,
                'width': width,
                'height': height,
                'video_id': video_id,
                'quality': f"{height}p"
            }
        except Exception as e:
            last_err = e
            err_str = str(e)
            if '403' in err_str or 'Forbidden' in err_str:
                log("RETRY", f"Terdeteksi batasan 403 Forbidden dari YouTube. Mencoba ulang (Percobaan {attempt}/{max_retries}) dalam 3 detik...", YELLOW)
                time.sleep(3)
                if attempt == 1:
                    ydl_opts['extractor_args'] = {'youtube': {'player_client': ['tv_embedded', 'web']}}
                elif attempt == 2:
                    ydl_opts['extractor_args'] = {'youtube': {'player_client': ['mweb', 'web']}}
            else:
                if attempt < max_retries:
                    log("RETRY", f"Percobaan download {attempt}/{max_retries} gagal: {e}. Mengulang dalam 2 detik...", YELLOW)
                    time.sleep(2)
                else:
                    raise e
    if last_err:
        raise last_err

async def upload_to_telegram(client: Client, file_info: dict, channel_id: int):
    file_path = file_info['file_path']
    title = file_info['title']
    duration = file_info['duration']
    width = file_info['width']
    height = file_info['height']

    log("UPLOAD", f"Mengunggah ke Channel Telegram [{channel_id}]...", CYAN)

    last_logged_pct = [-1]
    def progress(current, total):
        pct = int((current / total) * 100)
        if pct % 20 == 0 and pct != last_logged_pct[0]:
            last_logged_pct[0] = pct
            cur_mb = current / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            log("PROGRESS", f"Upload: {pct}% ({cur_mb:.1f}/{tot_mb:.1f} MB)", GRAY)

    caption = (
        f"🎬 **{title}**\n\n"
        f"📺 Resolusi: {height}p\n"
        f"⏱ Durasi: {duration // 60}m {duration % 60}s\n"
        f"#Nipnime #AnimeStream"
    )

    message = await client.send_video(
        chat_id=channel_id,
        video=file_path,
        caption=caption,
        duration=int(duration) if duration else None,
        width=int(width) if width else None,
        height=int(height) if height else None,
        supports_streaming=True,
        progress=progress
    )

    log("UPLOAD", f"Berhasil diunggah! Message ID: {message.id}", GREEN)
    return message.id

async def submit_to_nipnime(episode_id: int, stream_url: str, quality="1080p", audio_type="sub", old_msg_ids=None):
    if not episode_id:
        log("API", "Episode ID kosong, melewati submit ke server Nipnime.", YELLOW)
        return False

    submit_url = f"{API_URL}/submit"
    headers = {
        'X-Terop-Token': WORKER_TOKEN,
        'Accept': 'application/json'
    }
    qual_str = f"{quality}p" if not str(quality).lower().endswith('p') and str(quality).isdigit() else quality
    server_suffix = " Dub" if audio_type == 'dub' else ""
    payload = {
        'episode_id': episode_id,
        'source': 'telegram',
        'server_name': f"Nipnime Stream [Cloud {qual_str}{server_suffix}]",
        'url': stream_url,
        'quality': quality,
        'audio_type': audio_type
    }
    if old_msg_ids:
        payload['old_msg_ids'] = list(old_msg_ids)

    log("API", f"Menyetorkan hasil ke {submit_url}...", CYAN)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(submit_url, json=payload, headers=headers, timeout=15) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get('success'):
                    log("API", f"Berhasil disimpan di Nipnime: +{data.get('created', 1)} server!", GREEN)
                    return True
                else:
                    log("API", f"Gagal submit ke Nipnime: {data}", RED)
                    return False
    except Exception as e:
        log("API", f"Error koneksi ke API Nipnime: {e}", RED)
        return False

async def match_title_with_nipnime(title: str, auto_create: bool = True):
    match_url = f"{API_URL}/match-title"
    headers = {
        'X-Terop-Token': WORKER_TOKEN,
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    payload = {
        'title': title,
        'auto_create_episode': auto_create
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(match_url, json=payload, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    data = await resp.json()
                    log("MATCH", f"Gagal respon API ({resp.status}): {data.get('message') or data}", YELLOW)
    except Exception as e:
        log("MATCH", f"Error koneksi ke API matcher Nipnime: {e}", RED)
    return None

async def process_single_video(yt_url: str, episode_id: int = None, quality="1080,720", auto_match=True, skip_existing=False):
    if not check_credentials():
        return False

    int_channel_id = int(CHANNEL_ID)
    session_dir = SCRIPT_DIR / '.tg_sessions'
    session_dir.mkdir(exist_ok=True)

    # Parsing list kualitas target (default: 1080p dan 720p)
    if isinstance(quality, str):
        target_qualities = [q.strip().lower().replace('p', '') for q in quality.split(',') if q.strip()]
    elif isinstance(quality, (list, tuple)):
        target_qualities = [str(q).strip().lower().replace('p', '') for q in quality if str(q).strip()]
    else:
        target_qualities = ["1080", "720"]
    if not target_qualities:
        target_qualities = ["1080", "720"]

    # 1. Ekstrak metadata awal untuk deteksi judul & pencocokan otomatis dengan database Nipnime
    meta_ydl_opts = {
        'ffmpeg_location': FFMPEG_PATH,
        'quiet': True,
        'no_warnings': True,
    }
    
    yt_title = "Anime Episode"
    try:
        log("METADATA", f"Mengekstrak info video dari YouTube: {yt_url}")
        with YoutubeDL(meta_ydl_opts) as ydl:
            meta_info = ydl.extract_info(yt_url, download=False)
            yt_title = meta_info.get('title', yt_title)
            log("METADATA", f"Judul Asli YouTube: {BOLD}{yt_title}{RESET}")
    except Exception as me:
        log("METADATA", f"Gagal membaca metadata awal: {me}", YELLOW)

    existing_tg_qualities = []
    anime_title = "Unknown Anime"
    ep_num = "?"
    target_ep_id = None
    detected_audio_type = 'dub' if re.search(r'(?:Sulih\s+Suara|Bahasa\s+Indonesia|Bahasa\s+ID|Dub\s+Indo|Dubbing|Indo\s+Dub|\bDub\b)', yt_title, re.IGNORECASE) else 'sub'

    # 2. Lakukan pencocokan otomatis jika episode_id belum diisi dan auto_match aktif
    if not episode_id and auto_match:
        log("MATCH", "Mencocokkan judul YouTube dengan database anime Nipnime...", CYAN)
        match_data = await match_title_with_nipnime(yt_title)

        if match_data and match_data.get('matched'):
            anime_info = match_data.get('anime', {})
            ep_info = match_data.get('episode') or {}
            confidence = match_data.get('confidence', 0.0)

            anime_title = anime_info.get('title', 'Unknown')
            anime_id = anime_info.get('id')
            ep_num = ep_info.get('episode_number')
            target_ep_id = ep_info.get('id')
            existing_tg_qualities = [q.lower().replace('p', '') for q in (ep_info.get('telegram_qualities') or [])]
            detected_audio_type = match_data.get('parsed', {}).get('audio_type') or ep_info.get('audio_type') or detected_audio_type

            audio_label = "Sulih Suara / Dub Indo [🇮🇩]" if detected_audio_type == 'dub' else "Takarir / Sub Indo [🇯🇵]"
            log("MATCH", f"Anime Cocok     : {GREEN}{BOLD}{anime_title}{RESET} (ID: {anime_id})", GREEN)
            log("MATCH", f"Versi Audio     : {GREEN}{BOLD}{audio_label}{RESET}", GREEN)
            if target_ep_id:
                log("MATCH", f"Episode Target  : {GREEN}{BOLD}Episode {ep_num}{RESET} (Episode ID: {target_ep_id}) [Akurasi: {int(confidence * 100)}%]", GREEN)
                if existing_tg_qualities:
                    log("MATCH", f"Server Aktif    : {', '.join([q+'p' for q in existing_tg_qualities])}", CYAN)
                episode_id = target_ep_id
            else:
                log("MATCH", "Anime cocok, namun nomor episode tidak terdeteksi pada judul video.", YELLOW)
        else:
            log("MATCH", f"Pencocokan otomatis tidak menemukan anime yang pas di database Nipnime.", YELLOW)
            log("MATCH", "Video tetap akan diunduh dan diunggah ke Telegram (tanpa bind episode).", YELLOW)

    # 3. Filter resolusi yang belum ada di database
    needed_qualities = []
    for q in target_qualities:
        if skip_existing and q in existing_tg_qualities:
            log("SKIP", f"Episode {ep_num} ({anime_title}): Resolusi [{q}p] sudah ada di Telegram Nipnime.", GREEN)
        else:
            needed_qualities.append(q)

    if not needed_qualities:
        log("SKIP", f"Episode {ep_num} ({anime_title}): Semua resolusi ({', '.join([q+'p' for q in target_qualities])}) sudah ada di database Nipnime.", GREEN)
        return {
            'success': True,
            'skipped': True,
            'episode_id': episode_id,
            'title': yt_title
        }

    log("DOWNLOAD", f"Resolusi yang akan diproses: {', '.join([q+'p' for q in needed_qualities])}", CYAN)

    app = Client(
        name="nipnime_bot",
        api_id=int(API_ID),
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        workdir=str(session_dir)
    )

    uploaded_results = []
    last_uploaded_msg = None
    last_source_height = None
    for q in needed_qualities:
        q_int = int(q) if str(q).isdigit() else 720
        # Optimasi Cerdas: Jika video sebelumnya sudah terunggah dan resolusi riilnya <= q_int
        # (misal video YouTube aslinya maksimal hanya 720p dan tadi sudah terupload saat putaran 1080p)
        if last_uploaded_msg and last_source_height and q_int <= last_source_height:
            log("OPTIMIZE", f"Resolusi riil ({last_source_height}p) sudah terunggah sebelumnya. Melewati unduhan [{q}p].", GREEN)
            continue

        dl_info = None
        try:
            print(f"\n{CYAN}>>> Mengunduh & Mengunggah Resolusi [{q}p]...{RESET}")
            dl_info = download_from_youtube(yt_url, quality=q)
            actual_height = dl_info.get('height') or q_int
            last_source_height = actual_height

            await app.start()
            try:
                msg_id = await upload_to_telegram(app, dl_info, int_channel_id)
            finally:
                try:
                    await app.stop()
                except Exception:
                    pass

            stream_url = f"{STREAM_BASE_URL}/stream/{msg_id}"
            actual_qual_str = f"{actual_height}p"
            log("STREAM", f"URL Streaming [{actual_qual_str}] Siap: {stream_url}", GREEN)

            if episode_id:
                await submit_to_nipnime(episode_id, stream_url, quality=actual_qual_str, audio_type=detected_audio_type)
            else:
                log("INFO", f"Video [{actual_qual_str}] tersimpan di Telegram ID {msg_id}. Tidak disetor ke website karena Episode ID kosong.", YELLOW)

            uploaded_item = {
                'quality': actual_qual_str,
                'message_id': msg_id,
                'stream_url': stream_url
            }
            uploaded_results.append(uploaded_item)
            last_uploaded_msg = uploaded_item

            # Jeda santai 3 detik antar kualitas agar aman dari rate limit YouTube
            await asyncio.sleep(3)

        except Exception as e:
            log("ERROR", f"Terjadi kesalahan saat memproses resolusi [{q}p]: {e}", RED)
        finally:
            if dl_info and 'file_path' in dl_info:
                p = Path(dl_info['file_path'])
                if p.exists():
                    try:
                        p.unlink()
                        log("CLEANUP", f"File sementara [{q}p] dihapus: {p.name}", GRAY)
                    except Exception:
                        pass

    return {
        'success': len(uploaded_results) > 0,
        'results': uploaded_results,
        'title': yt_title,
        'episode_id': episode_id
    }

async def process_youtube_input(target_url: str, episode_id: int = None, quality="1080,720", auto_match=True, latest_first=True, skip_existing=True):
    # Cek apakah URL merupakan Playlist YouTube (misal playlist Muse Indonesia / Muse Asia)
    is_playlist = 'playlist?list=' in target_url or '&list=' in target_url

    if is_playlist:
        log("PLAYLIST", f"Mendeteksi URL Playlist YouTube: {target_url}", CYAN)
        playlist_opts = {
            'extract_flat': True,
            'quiet': True,
            'no_warnings': True,
        }

        entries = []
        try:
            with YoutubeDL(playlist_opts) as ydl:
                info = ydl.extract_info(target_url, download=False)
                if 'entries' in info:
                    entries = list(info['entries'])
                    log("PLAYLIST", f"Ditemukan {len(entries)} video anime di playlist '{info.get('title', 'YouTube Playlist')}'.", GREEN)
        except Exception as pe:
            log("PLAYLIST", f"Gagal mengekstrak playlist: {pe}, mencoba sebagai video tunggal...", YELLOW)

        if entries:
            if latest_first:
                log("PLAYLIST", "Mode Urutan: [TERBARU DULU] Memproses dari episode paling baru (akhir playlist) ke awal.", CYAN)
                entries = list(reversed(entries))
            else:
                log("PLAYLIST", "Mode Urutan: [DARI AWAL] Memproses dari episode 1 ke akhir playlist.", CYAN)

            success_count = 0
            skipped_count = 0
            for idx, item in enumerate(entries, 1):
                item_url = item.get('url') or item.get('webpage_url')
                if not item_url:
                    item_id = item.get('id')
                    if item_id:
                        item_url = f"https://www.youtube.com/watch?v={item_id}"
                if not item_url:
                    continue

                item_title = item.get('title', f"Video {idx}")
                print(f"\n{CYAN}{BOLD}----------------------------------------------------------------------{RESET}")
                log("PLAYLIST", f"[{idx}/{len(entries)}] Memeriksa: {item_title}", CYAN)
                print(f"{CYAN}{BOLD}----------------------------------------------------------------------{RESET}")

                res = await process_single_video(item_url, episode_id=None, quality=quality, auto_match=True, skip_existing=skip_existing)
                if res:
                    if res.get('skipped'):
                        skipped_count += 1
                    elif res.get('success'):
                        success_count += 1
                
                # Jeda singkat antar episode agar ramah rate limit
                await asyncio.sleep(2)

            log("PLAYLIST", f"Selesai! Berhasil diupload: {success_count}, Dilewati (sudah ada): {skipped_count}, Total: {len(entries)} video.", GREEN)
            return

    # Jika video tunggal biasa
    await process_single_video(target_url, episode_id=episode_id, quality=quality, auto_match=auto_match, skip_existing=skip_existing)

async def test_matcher(title_to_test: str):
    print(f"\n{CYAN}{BOLD}=== UJI COBA PENCOCOKAN JUDUL MUSE / YOUTUBE ==={RESET}")
    print(f"Judul Input: {YELLOW}{title_to_test}{RESET}\n")

    res = await match_title_with_nipnime(title_to_test, auto_create=False)
    if not res:
        print(f"{RED}[ERROR] Gagal menghubungi API atau server tidak merespon.{RESET}")
        return

    if res.get('matched'):
        anime = res.get('anime', {})
        ep = res.get('episode') or {}
        parsed = res.get('parsed', {})
        conf = int((res.get('confidence') or 0.0) * 100)

        print(f"{GREEN}{BOLD}[OK] BERHASIL DICOCOKKAN! (Akurasi: {conf}%){RESET}")
        print(f"  * Anime ID      : {CYAN}{anime.get('id')}{RESET}")
        print(f"  * Judul Anime   : {BOLD}{anime.get('title')}{RESET}")
        if anime.get('title_en'):
            print(f"  * Judul English : {GRAY}{anime.get('title_en')}{RESET}")
        print(f"  * Slug Anime    : {anime.get('slug')}")
        print(f"  * Status        : {anime.get('status')} | Total Ep: {anime.get('total_episodes')}")
        
        if ep:
            print(f"  * Target Episode: {GREEN}{BOLD}Episode {ep.get('episode_number')}{RESET}")
            print(f"  * Episode ID    : {CYAN}{ep.get('id')}{RESET}")
            print(f"  * Judul Episode : {ep.get('title')}")
            print(f"  * Ada Telegram  : {'Ya (Sudah Aktif)' if ep.get('has_telegram') else 'Belum (Siap Dimasukkan)'}")
            if ep.get('auto_created'):
                print(f"  * Auto Created  : {YELLOW}Ya (Episode baru dibuat di database){RESET}")
        else:
            print(f"  * Episode       : {YELLOW}Nomor episode tidak terdeteksi pada judul{RESET}")

        print(f"\n{GRAY}[Detail Parsing]{RESET}")
        print(f"  - Judul Bersih  : {parsed.get('clean_title')}")
        print(f"  - No. Episode   : {parsed.get('episode_number')}")
        print(f"  - Season        : {parsed.get('season')}")
        print(f"  - Part          : {parsed.get('part')}")
    else:
        print(f"{YELLOW}[TIDAK COCOK] {res.get('message', 'Anime tidak ditemukan di database.')}{RESET}")
        parsed = res.get('parsed', {})
        print(f"  - Judul Bersih  : {parsed.get('clean_title')}")
        print(f"  - No. Episode   : {parsed.get('episode_number')}")
        candidates = res.get('candidates', [])
        if candidates:
            print(f"  - Kandidat mirip: {', '.join(candidates[:5])}")

def main():
    parser = argparse.ArgumentParser(description="Nipnime YouTube to Telegram Ingest Worker")
    parser.add_argument('--url', type=str, help="URL video atau playlist YouTube (misal dari Muse Indonesia)")
    parser.add_argument('--episode-id', type=int, default=None, help="Episode ID di database Nipnime (opsional jika ingin manual)")
    parser.add_argument('--quality', type=str, default="1080,720", help="Resolusi yang diunduh (default: 1080,720 untuk mengambil 1080p dan 720p sekaligus)")
    parser.add_argument('--auto-match', action='store_true', default=True, help="Otomatis cocokkan judul YouTube ke database Nipnime")
    parser.add_argument('--no-auto-match', dest='auto_match', action='store_false', help="Matikan pencocokan otomatis")
    parser.add_argument('--latest-first', dest='latest_first', action='store_true', default=True, help="Proses playlist dari episode terbaru terlebih dahulu (default: True)")
    parser.add_argument('--oldest-first', dest='latest_first', action='store_false', help="Proses playlist dari episode pertama/terlama")
    parser.add_argument('--skip-existing', dest='skip_existing', action='store_true', default=True, help="Lewati unduhan jika episode sudah memiliki server Telegram di Nipnime (default: True)")
    parser.add_argument('--no-skip-existing', dest='skip_existing', action='store_false', help="Tetap unduh meskipun server Telegram sudah ada di Nipnime")
    parser.add_argument('--test', action='store_true', help="Uji coba koneksi bot Telegram")
    parser.add_argument('--test-match', type=str, default=None, help="Uji coba pencocokan judul YouTube/Muse ke database Nipnime")

    args = parser.parse_args()

    if args.test_match:
        asyncio.run(test_matcher(args.test_match))
        sys.exit(0)

    if args.test:
        print(f"\n{CYAN}{BOLD}=== UJI COBA KONEKSI TELEGRAM BOT NIPNIME ==={RESET}")
        if not check_credentials():
            sys.exit(1)

        session_dir = SCRIPT_DIR / '.tg_sessions'
        session_dir.mkdir(exist_ok=True)
        app = Client(
            name="nipnime_bot",
            api_id=int(API_ID),
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workdir=str(session_dir)
        )

        async def test_conn():
            await app.start()
            try:
                me = await app.get_me()
                log("AUTH", f"Bot terautentikasi: @{me.username} ({me.first_name})", GREEN)
                try:
                    chat = await app.get_chat(int(CHANNEL_ID))
                    log("CHANNEL", f"Channel terhubung: '{chat.title}' (ID: {chat.id})", GREEN)
                    log("SUCCESS", "Setup Telegram 100% Siap Digunakan!", GREEN)
                except Exception as ce:
                    log("CHANNEL", f"Gagal akses channel: {ce}", RED)
            finally:
                try:
                    await app.stop()
                except Exception:
                    pass

        asyncio.run(test_conn())
        sys.exit(0)

    if not args.url:
        print(f"{YELLOW}Masukkan argumen --url=\"https://youtube.com/watch?v=...\"{RESET}")
        parser.print_help()
        sys.exit(1)

    asyncio.run(process_youtube_input(
        args.url,
        args.episode_id,
        args.quality,
        auto_match=args.auto_match,
        latest_first=args.latest_first,
        skip_existing=args.skip_existing
    ))

if __name__ == '__main__':
    main()

