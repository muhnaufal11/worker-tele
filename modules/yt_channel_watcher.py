#!/usr/bin/env python3
"""
Nipnime YouTube Channel Auto-Watcher Daemon
Memantau channel YouTube anime resmi (Muse Indonesia, Muse Asia, Ani-One, dll.)
secara otomatis tanpa perlu input URL manual:
- Mendeteksi penayangan anime baru, episode baru, dan status penayangan premiere.
- Menunggu penayangan premiere selesai rilis sebelum mengunduh.
- Mencocokkan judul secara cerdas dengan database Nipnime (termasuk judul berbahasa Indonesia).
- Mengunduh (1080p/720p) dan mengunggah langsung ke Telegram Private Channel CDN.
- Berjalan dalam mode Single-Scan (--once) atau Daemon Loop (--interval).
"""

import os
import sys
import re
import time
import json
import asyncio
import argparse
from datetime import datetime
from pathlib import Path

# Pastikan output konsol Windows mendukung Unicode / UTF-8
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

# Import modul worker pendukung
SCRIPT_DIR = Path(__file__).resolve().parent.parent
MODULES_DIR = Path(__file__).resolve().parent
if str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from yt_dlp import YoutubeDL
from yt_telegram_worker import (
    match_title_with_nipnime,
    process_single_video,
    check_credentials,
    log,
    CYAN, GREEN, YELLOW, RED, GRAY, BOLD, RESET
)

# Direktori & File Konfigurasi / Cache
DATA_DIR = SCRIPT_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)
CHANNELS_FILE = SCRIPT_DIR / 'channels.json'
PROCESSED_FILE = DATA_DIR / 'processed_videos.json'

DEFAULT_CHANNELS = [
    {
        "id": "muse_indonesia",
        "name": "Muse Indonesia",
        "url": "https://www.youtube.com/@MuseIndonesia/videos",
        "enabled": True,
        "description": "Channel resmi Muse Indonesia (Subtitle Bahasa Indonesia)"
    }
]

def load_channels():
    if not CHANNELS_FILE.exists():
        try:
            with open(CHANNELS_FILE, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_CHANNELS, f, indent=2, ensure_ascii=False)
            return DEFAULT_CHANNELS
        except Exception as e:
            log("CONFIG", f"Gagal membuat file default channels.json: {e}", YELLOW)
            return DEFAULT_CHANNELS

    try:
        with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log("CONFIG", f"Gagal membaca channels.json: {e}, menggunakan konfigurasi default.", RED)
        return DEFAULT_CHANNELS

def load_processed_cache():
    if not PROCESSED_FILE.exists():
        return {}
    try:
        with open(PROCESSED_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_processed_cache(cache):
    try:
        with open(PROCESSED_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log("CACHE", f"Gagal menyimpan cache processed_videos.json: {e}", RED)

def is_non_anime_or_teaser(title: str) -> bool:
    """
    Filter cepat untuk mengabaikan video non-episode seperti:
    Highlight, PV, Teaser, Trailer, Marathon, MV, OST, Podcast, Wawancara, dll.
    """
    tl = title.lower()

    # 1. Blacklist kata kunci non-episode
    bad_keywords = [
        'teaser', 'trailer', 'highlight', 'highlights', 'ending theme', 'opening theme',
        'theme pv', 'teaser pv', 'special pv', 'main pv', 'official pv', 'official trailer',
        'gelut kita', 'wawancara', 'podcast', 'marathon', 'soundtrack', 'original soundtrack',
        'full ost', 'creditless', 'non-credit', 'pengumuman', 'behind the scene', 'recap',
        'nonton bareng', 'talkshow', 'livestream', 'q&a'
    ]
    for kw in bad_keywords:
        if kw in tl:
            return True

    # 2. Cek apakah ada indikator nomor episode
    has_ep = re.search(r'(?:episode|ep\.?|bagian|musim|s\d+e\d+|\b#\d+\b|-\s*\d{1,4}(?:\s*\[|\s*\(|\s*$))', tl)
    if not has_ep:
        return True

    return False

async def fetch_channel_videos(channel_url: str, limit: int = 12):
    """
    Mengekstrak daftar video terbaru dari tab /videos channel YouTube
    menggunakan flat metadata extractor yang cepat dan ringan.
    """
    ydl_opts = {
        'extract_flat': True,
        'playlist_items': f'1-{limit}',
        'quiet': True,
        'no_warnings': True,
    }

    loop = asyncio.get_event_loop()
    try:
        def _extract():
            with YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(channel_url, download=False)
        info = await loop.run_in_executor(None, _extract)
        if info and 'entries' in info:
            return list(info['entries'])
        return []
    except Exception as e:
        log("EXTRACT", f"Error saat membaca {channel_url}: {e}", RED)
        return []

async def scan_all_channels(quality: str = "1080", dry_run: bool = False, limit: int = 12):
    """
    Melakukan 1 putaran pemindaian lengkap ke seluruh channel yang aktif.
    """
    channels = [c for c in load_channels() if c.get('enabled', True)]
    processed_cache = load_processed_cache()

    total_new_uploaded = 0
    total_skipped = 0
    total_upcoming = 0

    print(f"\n{CYAN}{BOLD}======================================================================{RESET}")
    print(f"{CYAN}{BOLD}   NIPNIME AUTO-WATCHER: PEMINDAIAN CHANNEL YOUTUBE ANIME{RESET}")
    print(f"{GRAY}   Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Total Channel Aktif: {len(channels)}{RESET}")
    print(f"{CYAN}{BOLD}======================================================================{RESET}\n")

    for ch in channels:
        ch_name = ch.get('name', 'YouTube Channel')
        ch_url = ch.get('url')
        log("CHANNEL", f"Memeriksa {BOLD}{ch_name}{RESET} ({ch_url})...", CYAN)

        videos = await fetch_channel_videos(ch_url, limit=limit)
        log("CHANNEL", f"Ditemukan {len(videos)} video terbaru di '{ch_name}'.", GREEN)

        if not videos:
            continue

        # Proses dari video terlama ke video terbaru di antara batch N video
        # agar episode urut saat pertama kali ingest
        for v in reversed(videos):
            vid_id = v.get('id')
            if not vid_id:
                continue

            v_title = v.get('title', f"Video {vid_id}").strip()
            v_url = v.get('url') or f"https://www.youtube.com/watch?v={vid_id}"
            live_status = v.get('live_status')

            # 1. Cek jika sudah pernah diproses tuntas di cache lokal
            cached = processed_cache.get(vid_id)
            if cached:
                if cached.get('status') == 'ignored_not_anime':
                    continue
                cached_q = [q.lower().replace('p', '') for q in (cached.get('uploaded_qualities') or [])]
                target_q_list = [q.strip().lower().replace('p', '') for q in quality.split(',') if q.strip()]
                if cached.get('status') in ['uploaded', 'already_in_db'] and all(q in cached_q for q in target_q_list):
                    continue

            # 2. Tangani status siaran premiere
            # Jika 'is_upcoming': penayangan perdana belum dimulai (masih hitung mundur)
            if live_status == 'is_upcoming':
                total_upcoming += 1
                log("PREMIERE", f"[MENUNGGU TAYANG] '{v_title}' dijadwalkan tayang perdana. Belum dirilis.", YELLOW)
                # JANGAN simpan sebagai permanen processed, agar siklus berikutnya mengecek apakah sudah tayang
                continue

            # Jika 'is_live': sedang siaran perdana langsung
            if live_status == 'is_live':
                total_upcoming += 1
                log("LIVE", f"[SEDANG LIVE PERDANA] '{v_title}' sedang siaran langsung. Menunggu tayang selesai...", YELLOW)
                continue

            # 3. Filter cepat: Lewati video teaser / PV / marathon / non-episode
            if is_non_anime_or_teaser(v_title):
                log("SKIP", f"Bukan episode anime (PV/Teaser/Klip): {GRAY}{v_title}{RESET}", GRAY)
                processed_cache[vid_id] = {
                    'title': v_title,
                    'channel': ch_name,
                    'status': 'ignored_not_anime',
                    'updated_at': datetime.now().isoformat()
                }
                save_processed_cache(processed_cache)
                continue

            # 4. Cocokkan judul dengan Database Nipnime
            print(f"\n{CYAN}--- Memeriksa Episode Baru ------------------------------------------{RESET}")
            log("INSPECT", f"Video: {BOLD}{v_title}{RESET}", CYAN)

            match_res = await match_title_with_nipnime(v_title, auto_create=(not dry_run))
            if not match_res or not match_res.get('matched'):
                log("UNMATCHED", f"Judul belum terdaftar di database Nipnime: '{v_title}'", YELLOW)
                # Catat agar tidak spam API berulang kali dalam waktu dekat
                processed_cache[vid_id] = {
                    'title': v_title,
                    'channel': ch_name,
                    'status': 'unmatched',
                    'updated_at': datetime.now().isoformat()
                }
                save_processed_cache(processed_cache)
                continue

            anime_info = match_res.get('anime', {})
            ep_info = match_res.get('episode') or {}
            parsed_info = match_res.get('parsed', {})
            ep_num = ep_info.get('episode_number') or parsed_info.get('relative_episode_number') or parsed_info.get('episode_number') or '?'
            anime_title = anime_info.get('title', 'Unknown')
            target_ep_id = ep_info.get('id')
            is_auto_created = ep_info.get('auto_created', False)

            audio_type = parsed_info.get('audio_type') or ep_info.get('audio_type') or 'sub'
            audio_label = "Sulih Suara (Dub Indo) [🇮🇩]" if audio_type == 'dub' else "Takarir (Sub Indo) [🇯🇵]"

            if is_auto_created:
                log("AUTO-ADD", f"{GREEN}{BOLD}★ EPISODE BARU BERHASIL DIBUAT OTOMATIS DI NIPNIME! ★{RESET}", GREEN)
                log("AUTO-ADD", f"Anime: {BOLD}{anime_title}{RESET} | Episode: {BOLD}{ep_num}{RESET} (ID: {target_ep_id})", GREEN)
            else:
                log("MATCH", f"Cocok: {GREEN}{BOLD}{anime_title}{RESET} - {BOLD}Episode {ep_num}{RESET} (ID: {target_ep_id})", GREEN)
            
            log("MATCH", f"Versi Audio: {GREEN}{BOLD}{audio_label}{RESET}", GREEN)

            # 5. Cek apakah episode ini sudah memiliki semua kualitas server Telegram di Nipnime (sesuai tipe audio sub/dub)
            tg_qualities = [q.lower().replace('p', '') for q in (ep_info.get('telegram_qualities') or [])]
            target_q_list = [q.strip().lower().replace('p', '') for q in quality.split(',') if q.strip()]
            missing_q = [q for q in target_q_list if q not in tg_qualities]

            if not missing_q and tg_qualities:
                log("SKIP", f"Episode {ep_num} ({anime_title}) sudah memiliki server Telegram lengkap ({', '.join([q+'p' for q in tg_qualities])}). Melewati.", GREEN)
                total_skipped += 1
                processed_cache[vid_id] = {
                    'title': v_title,
                    'channel': ch_name,
                    'status': 'already_in_db',
                    'anime_id': anime_info.get('id'),
                    'episode_id': target_ep_id,
                    'uploaded_qualities': [f"{q}p" for q in tg_qualities],
                    'updated_at': datetime.now().isoformat()
                }
                save_processed_cache(processed_cache)
                continue

            # 6. EPISODE BARU / RESOLUSI BARU DITEMUKAN! Siap diproses
            log("NEW", f"{GREEN}{BOLD}>>> DETEKSI EPISODE BARU / RESOLUSI DIBUTUHKAN ({', '.join([q+'p' for q in missing_q])})! <<<{RESET}", GREEN)
            log("TARGET", f"Anime: {anime_title} | Ep {ep_num} | URL: {v_url}", CYAN)

            if dry_run:
                log("DRY-RUN", f"[Simulasi] Siap unduh & upload: {v_title} ({', '.join([q+'p' for q in missing_q])})", YELLOW)
                total_new_uploaded += 1
                continue

            log("DOWNLOAD", f"Memulai pengunduhan otomatis ({', '.join([q+'p' for q in missing_q])}) dan pengunggahan...", CYAN)
            res = await process_single_video(
                v_url,
                episode_id=target_ep_id,
                quality=",".join(missing_q),
                auto_match=True,
                skip_existing=True
            )

            if res and res.get('success'):
                total_new_uploaded += 1
                log("SUCCESS", f"Episode {ep_num} ({anime_title}) berhasil disetor ke Nipnime CDN!", GREEN)
                processed_cache[vid_id] = {
                    'title': v_title,
                    'channel': ch_name,
                    'status': 'uploaded',
                    'anime_id': anime_info.get('id'),
                    'episode_id': target_ep_id,
                    'uploaded_qualities': [f"{q}p" for q in target_q_list],
                    'results': res.get('results'),
                    'updated_at': datetime.now().isoformat()
                }
                save_processed_cache(processed_cache)
            else:
                log("FAILED", f"Gagal memproses episode: {v_title}", RED)

            # Jeda singkat antar episode agar ramah resource & network
            await asyncio.sleep(3)

    log("SUMMARY", f"Selesai! Berhasil Upload: {total_new_uploaded}, Sudah Ada: {total_skipped}, Menunggu Premiere: {total_upcoming}", GREEN)
    return {
        'uploaded': total_new_uploaded,
        'skipped': total_skipped,
        'upcoming': total_upcoming
    }

async def run_daemon(interval_seconds: int = 900, quality: str = "1080,720", dry_run: bool = False, limit: int = 12):
    """
    Mode Daemon: Berjalan terus menerus memantau channel dengan jeda interval_seconds.
    """
    if not dry_run and not check_credentials():
        sys.exit(1)

    print(f"\n{GREEN}{BOLD}=== NIPNIME AUTO-WATCHER DAEMON AKTIF ==={RESET}")
    print(f"Interval Pemindaian : {interval_seconds} detik ({int(interval_seconds / 60)} menit)")
    print(f"Kualitas Video      : Otomatis Ambil Semua ({quality})")
    print(f"Mode Simulasi       : {'Ya (Dry-Run)' if dry_run else 'Tidak (Aktif Ingest)'}")
    print(f"Tekan {YELLOW}Ctrl + C{RESET} untuk menghentikan pemantau.\n")

    cycle = 1
    while True:
        try:
            log("CYCLE", f"Memulai Siklus Pemindaian #{cycle}...", CYAN)
            await scan_all_channels(quality=quality, dry_run=dry_run, limit=limit)
            cycle += 1

            log("SLEEP", f"Menunggu {int(interval_seconds / 60)} menit untuk siklus pemindaian berikutnya...", GRAY)
            
            # Tidur dengan countdown interaktif per menit
            remaining = interval_seconds
            step = 30
            while remaining > 0:
                await asyncio.sleep(min(step, remaining))
                remaining -= step
                if remaining > 0 and remaining % 300 == 0:
                    log("WAIT", f"Siklus berikutnya dalam {int(remaining / 60)} menit...", GRAY)

        except asyncio.CancelledError:
            log("SHUTDOWN", "Daemon dihentikan oleh pengguna.", YELLOW)
            break
        except Exception as e:
            log("ERROR", f"Kesalahan tak terduga pada siklus #{cycle}: {e}", RED)
            log("RETRY", "Mencoba kembali dalam 60 detik...", YELLOW)
            await asyncio.sleep(60)

def main():
    parser = argparse.ArgumentParser(description="Nipnime YouTube Channel Auto-Watcher Daemon")
    parser.add_argument('--once', action='store_true', help="Hanya pindai satu kali lalu keluar (bukan loop daemon)")
    parser.add_argument('--interval', type=int, default=900, help="Interval loop daemon dalam detik (default 900 detik / 15 menit)")
    parser.add_argument('--quality', type=str, default="1080,720", help="Resolusi yang diunduh (default: 1080,720)")
    parser.add_argument('--limit', type=int, default=12, help="Jumlah video terbaru yang dicek per channel (default 12)")
    parser.add_argument('--dry-run', action='store_true', help="Simulasi pemindaian tanpa download/upload ke Telegram")

    args = parser.parse_args()

    if args.once:
        if not args.dry_run and not check_credentials():
            sys.exit(1)
        asyncio.run(scan_all_channels(quality=args.quality, dry_run=args.dry_run, limit=args.limit))
    else:
        try:
            asyncio.run(run_daemon(interval_seconds=args.interval, quality=args.quality, dry_run=args.dry_run, limit=args.limit))
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Auto-Watcher dihentikan oleh pengguna.{RESET}")

if __name__ == '__main__':
    main()
