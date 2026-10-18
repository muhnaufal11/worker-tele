#!/usr/bin/env python3
"""
Nipnime YouTube Playlist-First Scraper & Auto-Watcher Engine
Fitur:
1. Ekstrak playlist anime Muse Indonesia secepat kilat (< 1 detik).
2. Fallback cerdas ke tab /videos: Jika ada episode baru yang baru saja diupload
   atau premiere oleh Muse Indonesia dan belum dimasukkan ke playlist oleh admin,
   sistem otomatis mencari dan menemukannya di tab /videos!
3. Auto-Add Episode Baru: Begitu terdeteksi episode baru (misal Tensura rilis episode baru),
   sistem otomatis membuat episode di database Nipnime (auto_create_episode: true),
   mengunduh resolusi target (1080p, 720p), mengunggah ke Telegram CDN, dan
   menghubungkannya ke website tanpa campur tangan manual!
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
import aiohttp

# Pastikan output konsol Windows mendukung Unicode / UTF-8
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Import direktori modul worker pendukung
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
    auto_update_dependencies,
    log,
    CYAN, GREEN, YELLOW, RED, GRAY, BOLD, RESET
)

PLAYLISTS_CATALOG = SCRIPT_DIR / 'muse_playlists.json'
DEFAULT_CHANNEL_VIDEOS = "https://www.youtube.com/@MuseIndonesia/videos"
CHECKPOINT_FILE = SCRIPT_DIR / '.worker_checkpoint.json'

def save_checkpoint(anime_title: str, target_url: str, quality: str = "1080,720", current_ep=None, status: str = "running"):
    """Menyimpan status pemrosesan aktif untuk pemulihan otomatis jika komputer/program mati mendadak."""
    try:
        data = {
            'anime_title': anime_title,
            'target_url': target_url,
            'quality': quality,
            'current_ep': current_ep,
            'status': status,
            'timestamp': time.time(),
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def load_checkpoint():
    """Membaca checkpoint jika ada sesi sebelumnya yang belum tuntas."""
    if not CHECKPOINT_FILE.exists():
        return None
    try:
        with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Valid jika usianya kurang dari 48 jam
            if time.time() - data.get('timestamp', 0) < 172800:
                return data
    except Exception:
        pass
    return None

def clear_checkpoint():
    """Menghapus checkpoint setelah antrean selesai tuntas 100%."""
    try:
        if CHECKPOINT_FILE.exists():
            CHECKPOINT_FILE.unlink()
    except Exception:
        pass

def cleanup_orphaned_temp_files():
    """
    Membersihkan sisa file unduhan sementara yang tertinggal jika program sebelumnya mati mendadak,
    sehingga harddisk tidak penuh dan file korup tidak mengganggu proses baru.
    """
    temp_dir = SCRIPT_DIR / 'temp_videos'
    if not temp_dir.exists():
        return
    cleaned = 0
    now = time.time()
    for p in temp_dir.glob('*.*'):
        try:
            if p.suffix in ['.part', '.ytdl'] or (now - p.stat().st_mtime > 180):
                p.unlink()
                cleaned += 1
        except Exception:
            pass
    if cleaned > 0:
        log("CLEANUP", f"Sistem Keamanan: Membersihkan {cleaned} file sementara sisa sesi sebelumnya.", GRAY)

async def check_internet_connection(timeout_sec=5):
    """Mengecek apakah koneksi internet aktif."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://nipnime.com/api/health", timeout=timeout_sec) as resp:
                return resp.status == 200
    except Exception:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://www.youtube.com", timeout=timeout_sec) as resp:
                    return resp.status < 500
        except Exception:
            return False

async def ensure_internet_connection():
    """Jika koneksi internet terputus, masuk ke mode siaga dan tunggu sampai internet pulih."""
    if await check_internet_connection():
        return True
    
    log("OFFLINE", "Koneksi internet terputus atau server tidak merespons. Mengaktifkan mode siaga...", YELLOW)
    wait_sec = 5
    while True:
        await asyncio.sleep(wait_sec)
        if await check_internet_connection():
            log("ONLINE", "Koneksi internet kembali aktif! Melanjutkan tugas...", GREEN)
            return True
        log("OFFLINE", "Menunggu jaringan internet terhubung kembali...", GRAY)

def load_playlists_catalog():
    if not PLAYLISTS_CATALOG.exists():
        return []
    try:
        with open(PLAYLISTS_CATALOG, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log("CATALOG", f"Gagal membaca muse_playlists.json: {e}", YELLOW)
        return []

def search_playlists_catalog(keyword: str):
    catalog = load_playlists_catalog()
    if not keyword:
        return catalog
    k_lower = keyword.strip().lower()
    matches = []
    for item in catalog:
        title = item.get('title', '').lower()
        if k_lower in title:
            matches.append(item)
    return matches

def is_non_anime_or_teaser(title: str) -> bool:
    """
    Filter cepat untuk mengabaikan video non-episode seperti:
    Highlight, PV, Teaser, Trailer, Marathon, MV, OST, Podcast, Wawancara, dll.
    """
    tl = title.lower()

    bad_keywords = [
        'teaser', 'trailer', 'highlight', 'highlights', '#highlight', 'ending theme', 'opening theme',
        'theme pv', 'teaser pv', 'special pv', 'main pv', 'official pv', 'official trailer',
        'gelut kita', 'wawancara', 'podcast', 'marathon', 'semua episode', 'soundtrack', 'original soundtrack',
        'full ost', 'creditless', 'non-credit', 'pengumuman', 'behind the scene', 'recap',
        'nonton bareng', 'talkshow', 'livestream', 'q&a'
    ]
    for kw in bad_keywords:
        if kw in tl:
            return True

    has_ep = re.search(r'(?:episode|ep\.?|bagian|musim|s\d+e\d+|\b#\d+\b|-\s*\d{1,4}(?:\s*\[|\s*\(|\s*$))', tl)
    if not has_ep:
        return True

    return False

def fetch_playlist_entries(playlist_url: str):
    """
    Mengekstrak seluruh daftar video di dalam playlist YouTube secara instan (< 1 detik)
    menggunakan flat metadata extractor.
    """
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)
            if not info:
                return None, []
            playlist_title = info.get('title', 'YouTube Playlist')
            entries = list(info.get('entries', []))
            return playlist_title, entries
    except Exception as e:
        log("PLAYLIST", f"Gagal mengekstrak playlist {playlist_url}: {e}", RED)
        return None, []

_RECENT_VIDEOS_CACHE = {"timestamp": 0, "entries": []}

def fetch_channel_videos(channel_url: str = DEFAULT_CHANNEL_VIDEOS, limit: int = 40):
    """
    Mengekstrak daftar video terbaru dari tab /videos channel YouTube
    secara instan dengan caching 5 menit untuk efisiensi tinggi.
    """
    global _RECENT_VIDEOS_CACHE
    now = time.time()
    if _RECENT_VIDEOS_CACHE["entries"] and (now - _RECENT_VIDEOS_CACHE["timestamp"]) < 300:
        return _RECENT_VIDEOS_CACHE["entries"]

    ydl_opts = {
        'extract_flat': True,
        'playlist_items': f'1-{limit}',
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            if info and 'entries' in info:
                entries = list(info['entries'])
                _RECENT_VIDEOS_CACHE = {"timestamp": now, "entries": entries}
                return entries
            return []
    except Exception as e:
        log("VIDEOS_TAB", f"Gagal membaca tab /videos: {e}", YELLOW)
        return []

async def find_fallback_videos(anime_id: int, anime_title: str, playlist_video_ids: set, playlist_title: str = "", channel_url: str = DEFAULT_CHANNEL_VIDEOS, limit: int = 40):
    """
    Memeriksa tab /videos untuk mencari apakah ada video yang cocok dengan anime ini
    namun BELUM dimasukkan oleh Muse Indonesia ke dalam playlist.
    Menggunakan filter keyword awal yang instan (0ms) sebelum memanggil API matcher.
    """
    recent_videos = fetch_channel_videos(channel_url, limit=limit)
    if not recent_videos:
        return []

    # Ekstrak kata kunci anime (misal: "tensura", "slime", "cheat", "doraemon")
    keywords = set()
    for text in [anime_title, playlist_title]:
        if not text:
            continue
        clean_words = re.findall(r'[A-Za-z0-9]{3,}', text.lower())
        for w in clean_words:
            if w not in ['musim', 'season', 'episode', 'takarir', 'bahasa', 'indonesia', 'part', 'cour', 'full', 'official']:
                keywords.add(w)

    fallback_videos = []
    for v in recent_videos:
        vid_id = v.get('id')
        if not vid_id or vid_id in playlist_video_ids:
            continue

        v_title = v.get('title', '').strip()
        if not v_title:
            continue

        v_lower = v_title.lower()
        # Abaikan highlight/teaser/marathon
        if is_non_anime_or_teaser(v_title):
            continue

        # Jika tidak ada kata kunci yang cocok, lewati secara instan (0ms)
        if keywords and not any(kw in v_lower for kw in keywords):
            continue

        # Cek kecocokan anime di Nipnime jika lolos filter kata kunci
        match_data = await match_title_with_nipnime(v_title, auto_create=False)
        if match_data and match_data.get('matched'):
            m_anime = match_data.get('anime', {})
            if m_anime.get('id') == anime_id:
                fallback_videos.append({
                    'video': v,
                    'match_data': match_data,
                    'is_fallback': True
                })
    return fallback_videos

async def process_anime_playlist(
    playlist_url_or_query: str,
    quality: str = "1080,720",
    dry_run: bool = False,
    fallback_to_videos: bool = True,
    latest_first: bool = False
):
    """
    Memproses scraping playlist anime secara lengkap:
    1. Cek playlist terlebih dahulu (Super Cepat).
    2. Cek tab /videos jika ada episode baru yang belum masuk playlist (Fallback).
    3. Auto-Add episode baru ke database Nipnime jika ada rilis baru.
    4. Download & Upload ke Telegram CDN.
    """
    # 1. Resolusi input (Bisa berupa URL video tunggal, URL playlist, ID playlist, atau nama anime)
    target_url = playlist_url_or_query.strip()

    # 1a. Jika input adalah video tunggal YouTube (bukan playlist)
    if ('watch?v=' in target_url or 'youtu.be/' in target_url) and 'list=' not in target_url:
        log("INPUT", f"Mendeteksi URL video tunggal: {target_url}", CYAN)
        if dry_run:
            log("DRY-RUN", f"[Simulasi] Memeriksa status video tunggal...", YELLOW)
        res = await process_single_video(
            target_url,
            quality=quality,
            auto_match=True,
            skip_existing=True
        )
        return bool(res and res.get('success'))

    # 1b. Resolusi ID playlist (PL...) atau kata kunci nama anime di katalog
    if not target_url.startswith('http'):
        if target_url.startswith('PL'):
            target_url = f"https://www.youtube.com/playlist?list={target_url}"
        else:
            matches = search_playlists_catalog(target_url)
            if not matches:
                log("SEARCH", f"Tidak ditemukan playlist dengan kata kunci '{target_url}' di katalog.", RED)
                return False
            if len(matches) > 1:
                log("SEARCH", f"Ditemukan {len(matches)} playlist cocok untuk '{target_url}':", CYAN)
                for idx, m in enumerate(matches[:5], 1):
                    log("SEARCH", f"  [{idx}] {m['title']}", GRAY)
            selected = matches[0]
            target_url = selected['url']
            log("CATALOG", f"Memproses playlist: {BOLD}{selected['title']}{RESET} ({target_url})", GREEN)

    print(f"\n{CYAN}{BOLD}======================================================================{RESET}")
    print(f"{CYAN}{BOLD}   NIPNIME PLAYLIST-FIRST INGESTION & AUTO-ADD NEW EPISODES{RESET}")
    print(f"{GRAY}   URL Playlist : {target_url}{RESET}")
    print(f"{GRAY}   Kualitas     : {quality} | Mode Simulasi: {'Ya (Dry-Run)' if dry_run else 'Tidak (Aktif Ingest)'}{RESET}")
    print(f"{GRAY}   Fallback     : {'Aktif (Cek tab /videos jika episode baru belum di playlist)' if fallback_to_videos else 'Non-Aktif'}{RESET}")
    print(f"{CYAN}{BOLD}======================================================================{RESET}\n")

    # 2. Ekstrak playlist dengan flat metadata
    start_time = time.time()
    log("PLAYLIST", "Mengambil metadata playlist dari YouTube...", CYAN)
    pl_title, entries = fetch_playlist_entries(target_url)
    extract_duration = time.time() - start_time

    if not entries:
        log("PLAYLIST", f"Playlist kosong atau tidak dapat diakses: {target_url}", RED)
        return False

    save_checkpoint(pl_title, target_url, quality=quality, status="running")
    log("PLAYLIST", f"Berhasil membaca {BOLD}{len(entries)} video{RESET} di playlist '{pl_title}' dalam {BOLD}{extract_duration:.2f} detik{RESET}!", GREEN)

    # Catat ID video yang ada di playlist
    playlist_video_ids = set()
    for e in entries:
        vid_id = e.get('id')
        if vid_id:
            playlist_video_ids.add(vid_id)

    # 3. Identifikasi Anime dari video pertama playlist
    log("MATCHER", "Mendeteksi judul anime di database Nipnime...", CYAN)
    first_title = entries[0].get('title', pl_title)
    first_match = await match_title_with_nipnime(first_title, auto_create=False)

    matched_anime_id = None
    matched_anime_title = None
    if first_match and first_match.get('matched'):
        anime_data = first_match.get('anime', {})
        matched_anime_id = anime_data.get('id')
        matched_anime_title = anime_data.get('title')
        log("MATCHER", f"Teridentifikasi: {GREEN}{BOLD}{matched_anime_title}{RESET} (ID: {matched_anime_id})", GREEN)
    else:
        log("MATCHER", f"Peringatan: Judul awal belum cocok di Nipnime, akan mencocokkan tiap episode secara mandiri.", YELLOW)

    # 4. Fallback ke Tab /videos: Cari episode yang mungkin belum dimasukkan ke playlist
    fallback_entries = []
    if fallback_to_videos and matched_anime_id:
        log("FALLBACK", "Memeriksa tab /videos untuk mencari episode yang belum masuk playlist...", CYAN)
        fallback_items = await find_fallback_videos(
            anime_id=matched_anime_id,
            anime_title=matched_anime_title,
            playlist_video_ids=playlist_video_ids,
            playlist_title=pl_title
        )
        if fallback_items:
            log("FALLBACK", f"{GREEN}{BOLD}Ditemukan {len(fallback_items)} episode di tab /videos yang belum ada di playlist!{RESET}", GREEN)
            for fb in fallback_items:
                v = fb['video']
                fallback_entries.append(v)
                log("FALLBACK", f"  -> [Episode Tambahan]: {BOLD}{v.get('title')}{RESET}", CYAN)
        else:
            log("FALLBACK", "Semua episode terbaru sudah rapi tercakup di dalam playlist.", GRAY)

    # Gabungkan daftar video: playlist entries + fallback entries
    all_videos = list(entries) + list(fallback_entries)

    # Urutkan urutan proses
    if latest_first:
        log("QUEUE", "Urutan Proses: Dari Episode Terbaru ke Terlama.", CYAN)
        all_videos = list(reversed(all_videos))
    else:
        log("QUEUE", "Urutan Proses: Dari Episode Pertama ke Terakhir.", CYAN)

    total_processed = 0
    total_skipped = 0
    total_new = 0
    total_uploaded = 0
    failed_items = []

    # 5. Iterasi dan proses setiap video
    for idx, item in enumerate(all_videos, 1):
        vid_id = item.get('id')
        raw_t = item.get('title')
        if not raw_t or raw_t.strip() in ['[Deleted video]', '[Private video]']:
            log("SKIP", f"Video dihapus atau disetel privat oleh channel (ID: {vid_id}). Melewati.", GRAY)
            continue
        v_title = raw_t.strip()
        v_url = item.get('url') or item.get('webpage_url') or f"https://www.youtube.com/watch?v={vid_id}"
        live_status = item.get('live_status')
        is_fb = vid_id not in playlist_video_ids

        tag_source = f"{YELLOW}[DARI TAB /VIDEOS]{RESET} " if is_fb else f"{CYAN}[PLAYLIST]{RESET} "

        print(f"\n{CYAN}----------------------------------------------------------------------{RESET}")
        log("ITEM", f"[{idx}/{len(all_videos)}] {tag_source}{BOLD}{v_title}{RESET}", CYAN)

        # Cek jika live premiere belum selesai
        if live_status in ['is_upcoming', 'is_live']:
            log("PREMIERE", f"Video masih berstatus Premiere/Live. Menunggu penayangan tuntas.", YELLOW)
            continue

        # Lewati video teaser / PV / marathon / klip / non-episode
        if is_non_anime_or_teaser(v_title):
            log("SKIP", f"Bukan episode anime (PV/Teaser/Highlight/Marathon): {GRAY}{v_title}{RESET}", GRAY)
            continue

        # Cocokkan judul video dengan Nipnime (auto_create=True jika bukan dry_run)
        match_data = await match_title_with_nipnime(v_title, auto_create=(not dry_run))
        if not match_data or not match_data.get('matched'):
            log("UNMATCHED", f"Judul belum terdaftar di database Nipnime: '{v_title}'", YELLOW)
            continue

        anime_info = match_data.get('anime', {})
        ep_info = match_data.get('episode') or {}
        parsed_info = match_data.get('parsed', {})

        anime_name = anime_info.get('title', 'Unknown')
        ep_num = ep_info.get('episode_number') or parsed_info.get('relative_episode_number') or parsed_info.get('episode_number') or '?'
        target_ep_id = ep_info.get('id')
        is_auto_created = ep_info.get('auto_created', False)

        audio_type = parsed_info.get('audio_type') or ep_info.get('audio_type') or 'sub'
        audio_label = "Sulih Suara (Dub Indo) [🇮🇩]" if audio_type == 'dub' else "Takarir (Sub Indo) [🇯🇵]"

        if is_auto_created:
            log("AUTO-ADD", f"{GREEN}{BOLD}★ EPISODE BARU BERHASIL DIBUAT OTOMATIS DI NIPNIME! ★{RESET}", GREEN)
            log("AUTO-ADD", f"Anime: {BOLD}{anime_name}{RESET} | Episode: {BOLD}{ep_num}{RESET} (ID: {target_ep_id})", GREEN)
            total_new += 1
        else:
            log("MATCH", f"Anime: {GREEN}{BOLD}{anime_name}{RESET} | Episode: {BOLD}{ep_num}{RESET} (ID: {target_ep_id})", GREEN)
        
        log("MATCH", f"Versi Audio: {GREEN}{BOLD}{audio_label}{RESET}", GREEN)

        # Cek ketersediaan resolusi server Telegram
        tg_qualities = [q.lower().replace('p', '') for q in (ep_info.get('telegram_qualities') or [])]
        target_q_list = [q.strip().lower().replace('p', '') for q in quality.split(',') if q.strip()]
        missing_q = [q for q in target_q_list if q not in tg_qualities]

        if not missing_q and tg_qualities:
            log("SKIP", f"Episode {ep_num} ({anime_name}) sudah memiliki server Telegram lengkap ({', '.join([q+'p' for q in tg_qualities])}). Melewati.", GREEN)
            total_skipped += 1
            continue

        # Episode perlu diproses / diunduh
        log("PROCESS", f"Resolusi dibutuhkan: {CYAN}{BOLD}{', '.join([q+'p' for q in missing_q])}{RESET}", CYAN)

        if dry_run:
            log("DRY-RUN", f"[Simulasi] Siap unduh & upload ke Telegram CDN: {v_title}", YELLOW)
            total_processed += 1
            continue

        # Eksekusi Download, Upload ke Telegram CDN, dan Bind ke Episode Nipnime
        res = await process_single_video(
            v_url,
            episode_id=target_ep_id,
            quality=",".join(missing_q),
            auto_match=True,
            skip_existing=True
        )

        if res and res.get('success'):
            total_uploaded += 1
            log("SUCCESS", f"Episode {ep_num} ({anime_name}) berhasil disetor ke Nipnime CDN!", GREEN)
        else:
            log("FAILED", f"Gagal mengunggah episode: {v_title}", RED)
            failed_items.append({
                'v_url': v_url,
                'target_ep_id': target_ep_id,
                'missing_q': missing_q,
                'ep_num': ep_num,
                'anime_name': anime_name,
                'v_title': v_title
            })

        # Jeda santai antar episode
        await asyncio.sleep(2)

    # Auto-Retry Pass: Jika ada episode yang sempat terkendala/gagal, lakukan percobaan ulang otomatis
    if failed_items and not dry_run:
        print(f"\n{YELLOW}{BOLD}======================================================================{RESET}")
        log("AUTO-RETRY", f"Mendeteksi {len(failed_items)} episode yang sempat terkendala. Mengulang otomatis dalam 4 detik...", YELLOW)
        print(f"{YELLOW}{BOLD}======================================================================{RESET}\n")
        await asyncio.sleep(4)
        retry_queue = list(failed_items)
        failed_items.clear()
        for r in retry_queue:
            log("RETRY-ITEM", f"Mencoba ulang episode: {BOLD}{r['v_title']}{RESET}", CYAN)
            res = await process_single_video(
                r['v_url'],
                episode_id=r['target_ep_id'],
                quality=",".join(r['missing_q']),
                auto_match=True,
                skip_existing=True
            )
            if res and res.get('success'):
                total_uploaded += 1
                log("SUCCESS", f"Episode {r['ep_num']} ({r['anime_name']}) berhasil terunggah pada percobaan ulang!", GREEN)
            else:
                log("FAILED", f"Percobaan ulang belum berhasil untuk: {r['v_title']}", RED)
            await asyncio.sleep(2)

    print(f"\n{CYAN}{BOLD}======================================================================{RESET}")
    print(f"{GREEN}{BOLD}   RINGKASAN SCRAPING PLAYLIST SELESAI{RESET}")
    print(f"   * Total Video Dianalisis   : {len(all_videos)}")
    print(f"   * Episode Sudah Lengkap    : {total_skipped}")
    print(f"   * Episode Baru Dibuat      : {total_new}")
    if dry_run:
        print(f"   * Episode Siap Diproses    : {total_processed} (Simulasi)")
    else:
        print(f"   * Episode Berhasil Upload  : {total_uploaded}")
    print(f"{CYAN}{BOLD}======================================================================{RESET}\n")
    clear_checkpoint()
    return True

async def run_daemon(interval_seconds: int = 900, quality: str = "1080,720", dry_run: bool = False, once: bool = False):
    """
    Mode Daemon / Single-Scan: Memantau playlist anime Muse Indonesia secara berkala + tab /videos
    agar episode baru (seperti Tensura rilis episode baru) otomatis bertambah sendiri.
    """
    if not dry_run and not check_credentials():
        sys.exit(1)

    if not dry_run:
        auto_update_dependencies()

    print(f"\n{GREEN}{BOLD}=== NIPNIME PLAYLIST-FIRST & AUTO-ADD PEMANTAU AKTIF ==={RESET}")
    print(f"Mode Operasi        : {'Pindai 1 Kali (Single-Scan)' if once else f'Loop Daemon tiap {int(interval_seconds / 60)} menit'}")
    print(f"Kualitas Video      : {quality}")
    print(f"Mode Simulasi       : {'Ya (Dry-Run)' if dry_run else 'Tidak (Aktif Ingest)'}")
    print(f"Auto-Add Episode    : Aktif (Episode baru otomatis dibuat di database Nipnime)")
    if not once:
        print(f"Tekan {YELLOW}Ctrl + C{RESET} untuk menghentikan pemantau.\n")

    catalog = load_playlists_catalog()
    # Memantau 15 playlist anime teratas + fallback /videos
    monitored_playlists = catalog[:15] if catalog else []

    # Cek pemulihan otomatis jika komputer/program sebelumnya mati mendadak
    cp = load_checkpoint()
    if cp and cp.get('status') == 'running' and cp.get('target_url'):
        log("RECOVERY", f"{YELLOW}{BOLD}★ SISTEM KEAMANAN: MEMULIHKAN SESI SEBELUMNYA ★{RESET}", YELLOW)
        log("RECOVERY", f"Melanjutkan anime: {BOLD}{cp.get('anime_title')}{RESET} ({cp.get('target_url')})", CYAN)
        try:
            await ensure_internet_connection()
            await process_anime_playlist(
                cp['target_url'],
                quality=quality,
                dry_run=dry_run,
                fallback_to_videos=True,
                latest_first=True
            )
            clear_checkpoint()
            log("RECOVERY", "Sesi yang tertunda berhasil dipulihkan tuntas!", GREEN)
        except Exception as e:
            log("RECOVERY", f"Peringatan pemulihan: {e}. Melanjutkan antrean pemantau normal.", YELLOW)

    cycle = 1
    while True:
        try:
            await ensure_internet_connection()
            log("CYCLE", f"Memulai Siklus Pemindaian #{cycle} ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})...", CYAN)
            for p in monitored_playlists:
                try:
                    await ensure_internet_connection()
                    p_url = p.get('url')
                    p_title = p.get('title', 'Anime Playlist')
                    log("DAEMON", f"Memeriksa playlist: {BOLD}{p_title}{RESET}...", CYAN)
                    await process_anime_playlist(
                        p_url,
                        quality=quality,
                        dry_run=dry_run,
                        fallback_to_videos=True,
                        latest_first=True
                    )
                except Exception as pe:
                    log("DAEMON", f"Peringatan playlist '{p.get('title')}': {pe}. Melanjutkan playlist berikutnya...", YELLOW)
                await asyncio.sleep(2)

            if once:
                log("CYCLE", f"Pemindaian 1x selesai tuntas. Seluruh episode baru telah diproses dan auto-add.", GREEN)
                break

            cycle += 1
            log("SLEEP", f"Menunggu {int(interval_seconds / 60)} menit untuk siklus pemindaian berikutnya...", GRAY)
            
            remaining = interval_seconds
            step = 30
            while remaining > 0:
                await asyncio.sleep(min(step, remaining))
                remaining -= step

        except asyncio.CancelledError:
            log("SHUTDOWN", "Daemon dihentikan oleh pengguna.", YELLOW)
            break
        except Exception as e:
            log("ERROR", f"Kesalahan pada siklus #{cycle}: {e}", RED)
            if once:
                break
            log("RETRY", "Mencoba kembali dalam 60 detik...", YELLOW)
            await asyncio.sleep(60)

def main():
    parser = argparse.ArgumentParser(description="Nipnime YouTube Playlist-First Scraper & Auto-Watcher")
    parser.add_argument('--url', type=str, help="URL playlist YouTube, ID playlist (PL...), atau kata kunci anime di katalog")
    parser.add_argument('--list', action='store_true', help="Tampilkan daftar seluruh playlist Muse Indonesia di katalog")
    parser.add_argument('--search', type=str, help="Cari playlist di katalog berdasarkan judul")
    parser.add_argument('--quality', type=str, default="1080,720", help="Resolusi yang diunduh (default: 1080,720)")
    parser.add_argument('--dry-run', action='store_true', help="Simulasi pengecekan tanpa download/upload dan tanpa membuat episode")
    parser.add_argument('--no-fallback', action='store_true', help="Jangan cek tab /videos (hanya playlist murni)")
    parser.add_argument('--latest-first', action='store_true', help="Proses episode terbaru terlebih dahulu")
    parser.add_argument('--daemon', action='store_true', help="Jalankan sebagai Daemon yang memantau terus menerus")
    parser.add_argument('--once', action='store_true', help="Hanya jalankan 1 kali pemindaian pemantau lalu selesai")
    parser.add_argument('--interval', type=int, default=900, help="Interval daemon dalam detik (default: 900 detik / 15 menit)")

    args = parser.parse_args()

    # Sistem Keamanan: Bersihkan file sementara yang tertinggal jika program sebelumnya mati mendadak
    cleanup_orphaned_temp_files()

    # 1. Menu Tampilkan Seluruh Playlist di Katalog
    if args.list:
        catalog = load_playlists_catalog()
        print(f"\n{CYAN}{BOLD}=== KATALOG PLAYLIST MUSE INDONESIA ({len(catalog)} PLAYLIST) ==={RESET}\n")
        for p in catalog:
            print(f"[{p['index']:3d}] {BOLD}{p['title']}{RESET}")
            print(f"      URL: {CYAN}{p['url']}{RESET}")
        print(f"\n{GREEN}Total {len(catalog)} playlist tersedia.{RESET}\n")
        return

    # 2. Menu Cari Playlist di Katalog
    if args.search:
        results = search_playlists_catalog(args.search)
        print(f"\n{CYAN}{BOLD}=== HASIL PENCARIAN PLAYLIST: '{args.search}' ({len(results)} DITEMUKAN) ==={RESET}\n")
        for r in results:
            print(f"[{r['index']:3d}] {BOLD}{r['title']}{RESET}")
            print(f"      URL: {CYAN}{r['url']}{RESET}")
        print()
        return

    # 3. Mode Daemon Non-Stop / Single Scan
    if args.daemon or args.once:
        try:
            asyncio.run(run_daemon(interval_seconds=args.interval, quality=args.quality, dry_run=args.dry_run, once=args.once))
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Pemantau dihentikan.{RESET}")
        return

    # 4. Mode Scrape Playlist Tertentu
    if args.url:
        if not args.dry_run and not check_credentials():
            sys.exit(1)
        asyncio.run(process_anime_playlist(
            args.url,
            quality=args.quality,
            dry_run=args.dry_run,
            fallback_to_videos=(not args.no_fallback),
            latest_first=args.latest_first
        ))
        return

    # Jika dijalankan tanpa argumen, tampilkan bantuan interaktif
    parser.print_help()

if __name__ == '__main__':
    main()
