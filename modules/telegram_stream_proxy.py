#!/usr/bin/env python3
"""
Nipnime Telegram HTTP Stream Proxy (High-Performance FastStream)
Mengubah file video di Channel Telegram Privat menjadi URL streaming HTTP standar (MP4/HLS)
dengan dukungan penuh Byte-Range Request 206, Disk Caching, dan Background Pre-buffering
untuk pemutaran super mulus tanpa buffering / macet di NipNime Custom Player.
"""

import os
import sys
import time
import math
import asyncio
import logging
import hmac
import hashlib
from pathlib import Path
from dotenv import load_dotenv
from aiohttp import web
from pyrogram import Client, utils
from pyrogram.errors import FloodWait

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tg_stream")

# Fix Pyrogram 64-bit channel ID support
utils.MIN_CHANNEL_ID = -10099999999999

# Load .env
ENV_PATH = Path(__file__).resolve().parent.parent / '.env'
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

API_ID = os.getenv('TELEGRAM_API_ID', '').strip()
API_HASH = os.getenv('TELEGRAM_API_HASH', '').strip()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID', '').strip()
PORT = int(os.getenv('TELEGRAM_STREAM_PORT', '8088'))
STREAM_SECRET = os.getenv('TELEGRAM_STREAM_SECRET', 'nipnime_tg_secure_stream_key_2026').strip()

# Daftar domain yang diizinkan memutar video (Anti-Hotlink)
ALLOWED_DOMAINS = [
    'nipnime.com',
    'www.nipnime.com',
    'localhost',
    '127.0.0.1',
]

def is_allowed_origin(request: web.Request) -> bool:
    """Periksa header Origin / Referer untuk proteksi Anti-Hotlink."""
    origin = request.headers.get('Origin', '')
    referer = request.headers.get('Referer', '')

    for domain in ALLOWED_DOMAINS:
        if domain in origin or domain in referer:
            return True

    # Izinkan juga IP lokal untuk admin / dev internal
    for header in [origin, referer]:
        if header and any(header.startswith(prefix) for prefix in ['http://192.168.', 'http://10.', 'http://172.', 'https://192.168.', 'https://10.']):
            return True

    return False

def verify_stream_token(msg_id: int, request: web.Request) -> bool:
    """Periksa Token Hash Rahasia & Waktu Kedaluwarsa (HMAC SHA-256)."""
    token = request.query.get('t', '').strip()
    exp = request.query.get('exp', '').strip()

    if not token or not exp:
        return False

    try:
        exp_int = int(exp)
        # Cek apakah token sudah kedaluwarsa (toleransi 300 detik)
        if time.time() > (exp_int + 300):
            return False

        expected = hmac.new(
            STREAM_SECRET.encode('utf-8'),
            f"{msg_id}:{exp}".encode('utf-8'),
            hashlib.sha256
        ).hexdigest()[:16]

        return hmac.compare_digest(token, expected)
    except Exception:
        return False

SCRIPT_DIR = Path(__file__).resolve().parent.parent
SESSION_DIR = SCRIPT_DIR / '.tg_sessions'
SESSION_DIR.mkdir(exist_ok=True)

# Cache penyimpanan chunk di disk lokal untuk akses instan (< 1ms)
CACHE_DIR = SCRIPT_DIR / 'cache_stream'
CACHE_DIR.mkdir(exist_ok=True)

CHUNK_SIZE = 1024 * 1024  # 1 MiB per Telegram part

tg_client = Client(
    name="nipnime_streamer",
    api_id=int(API_ID) if API_ID.isdigit() else 0,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=str(SESSION_DIR)
)

# Metadata cache: {msg_id: (file_size, mime_type, message, timestamp)}
_meta_cache = {}

# In-flight chunk deduplication: {(msg_id, chunk_idx): asyncio.Future}
_in_progress = {}
_lock = asyncio.Lock()


async def get_message_info(chat_id: int, msg_id: int):
    """Ambil metadata video dengan caching in-memory agar hemat request MTProto."""
    now = time.time()
    if msg_id in _meta_cache:
        file_size, mime_type, message, cached_at = _meta_cache[msg_id]
        if now - cached_at < 86400:  # Valid 24 jam
            return message, file_size, mime_type

    try:
        message = await tg_client.get_messages(chat_id, msg_id)
    except FloodWait as e:
        logger.warning(f"Telegram FloodWait {e.value}s saat mengambil pesan {msg_id}")
        await asyncio.sleep(e.value)
        message = await tg_client.get_messages(chat_id, msg_id)

    media = message.video or message.document
    if not media:
        return None, 0, None

    file_size = media.file_size
    mime_type = getattr(media, 'mime_type', 'video/mp4') or 'video/mp4'

    _meta_cache[msg_id] = (file_size, mime_type, message, now)
    return message, file_size, mime_type


async def fetch_chunk(msg_id: int, message, chunk_idx: int) -> bytes:
    """Mengambil 1 chunk (1MB) dari cache disk atau download dari Telegram jika belum ada."""
    chunk_file = CACHE_DIR / f"{msg_id}_{chunk_idx}.part"
    if chunk_file.exists():
        try:
            data = chunk_file.read_bytes()
            if len(data) > 0:
                return data
        except Exception:
            pass

    key = (msg_id, chunk_idx)
    fut = None

    async with _lock:
        if key in _in_progress:
            fut = _in_progress[key]
        else:
            fut_new = asyncio.get_running_loop().create_future()
            _in_progress[key] = fut_new

    # Jika chunk sedang didownload oleh task lain, tunggu hasilnya
    if fut is not None:
        try:
            return await fut
        except Exception:
            return b""

    # Task ini yang bertanggung jawab mengunduh dari Telegram
    chunk_data = b""
    try:
        async for chunk in tg_client.stream_media(message, limit=1, offset=chunk_idx):
            chunk_data = chunk
            break

        if chunk_data:
            try:
                chunk_file.write_bytes(chunk_data)
            except Exception as e:
                logger.error(f"Gagal menyimpan cache chunk {key}: {e}")

        async with _lock:
            setter = _in_progress.pop(key, None)
        if setter and not setter.done():
            setter.set_result(chunk_data)

        return chunk_data

    except Exception as e:
        logger.error(f"Error fetching chunk {key} dari Telegram: {e}")
        async with _lock:
            setter = _in_progress.pop(key, None)
        if setter and not setter.done():
            setter.set_exception(e)
        return b""


def prefetch_chunk(msg_id: int, message, chunk_idx: int, max_chunks: int):
    """Pre-fetch chunk berikutnya di latar belakang agar playback tidak pernah buffering."""
    if 0 <= chunk_idx < max_chunks:
        chunk_file = CACHE_DIR / f"{msg_id}_{chunk_idx}.part"
        if not chunk_file.exists() and (msg_id, chunk_idx) not in _in_progress:
            asyncio.create_task(fetch_chunk(msg_id, message, chunk_idx))


routes = web.RouteTableDef()


@routes.options('/stream/{message_id}')
@routes.options('/stream/stream/{message_id}')
@routes.options(r'/{message_id:\d+}')
async def handle_options(request):
    req_origin = request.headers.get('Origin', 'https://nipnime.com')
    cors_origin = req_origin if is_allowed_origin(request) else 'https://nipnime.com'
    headers = {
        'Access-Control-Allow-Origin': cors_origin,
        'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
        'Access-Control-Allow-Headers': 'Range, Origin, Accept, Content-Type',
        'Access-Control-Max-Age': '86400',
    }
    return web.Response(status=204, headers=headers)


@routes.get('/')
async def index_handler(request):
    return web.json_response({
        'service': 'Nipnime Telegram Stream Proxy (FastStream)',
        'status': 'ONLINE',
        'port': PORT,
        'channel_id': CHANNEL_ID,
        'uptime_timestamp': time.time(),
        'cached_parts': len(list(CACHE_DIR.glob("*.part"))),
        'docs': 'Akses video via /stream/{message_id}'
    })


@routes.get('/stream/{message_id}')
@routes.get('/stream/stream/{message_id}')
@routes.get(r'/{message_id:\d+}')
async def stream_handler(request):
    raw_msg_id = request.match_info.get('message_id')
    if not raw_msg_id or not raw_msg_id.isdigit():
        return web.Response(status=400, text="Invalid Message ID")

    msg_id = int(raw_msg_id)
    chat_id = int(CHANNEL_ID)

    # =========================================================================
    # FITUR KEAMANAN 1 & 2: ANTI-HOTLINK (REFERER GUARD) & SIGNED TOKEN (HMAC)
    # =========================================================================
    has_valid_token = verify_stream_token(msg_id, request)
    has_valid_origin = is_allowed_origin(request)

    # 1. Anti-Hotlink: Jika request berasal dari situs lain (bukan nipnime.com)
    origin_header = request.headers.get('Origin') or request.headers.get('Referer')
    if origin_header and not has_valid_origin:
        logger.warning(f"[SECURITY - HOTLINK BLOCKED] Request ditolak dari situs luar: {origin_header} | Target MSG: {msg_id}")
        return web.Response(
            status=403,
            text="403 Forbidden: Hotlinking and unauthorized embedding is blocked by Nipnime Anti-Scrape Protection."
        )

    # 2. Anti-Scrape: Jika akses direct/bot (tanpa referer dari browser resmi Nipnime), wajib sertakan token HMAC yang sah
    if not has_valid_origin and not has_valid_token:
        logger.warning(f"[SECURITY - SCRAPE BLOCKED] Scraper / direct request tanpa token sah diblokir: IP={request.remote} | Target MSG: {msg_id}")
        return web.Response(
            status=403,
            text="403 Forbidden: Protected Media Stream. A valid signed token is required to access this resource."
        )

    req_origin = request.headers.get('Origin', 'https://nipnime.com')
    cors_origin = req_origin if has_valid_origin else 'https://nipnime.com'

    try:
        message, file_size, mime_type = await get_message_info(chat_id, msg_id)
    except Exception as e:
        logger.error(f"Error get_message_info {msg_id}: {e}")
        return web.Response(status=404, text=f"Message not found in Telegram: {e}")

    if not message or not file_size:
        return web.Response(status=404, text="No playable video media found in this message")

    total_chunks = math.ceil(file_size / CHUNK_SIZE)

    # Tangani permintaan HEAD (prober media)
    if request.method == 'HEAD':
        headers = {
            'Content-Type': mime_type,
            'Content-Length': str(file_size),
            'Accept-Ranges': 'bytes',
            'Access-Control-Allow-Origin': cors_origin,
            'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
            'Access-Control-Allow-Headers': 'Range, Origin, Accept, Content-Type',
            'Cache-Control': 'public, max-age=31536000',
        }
        return web.Response(status=200, headers=headers)

    range_header = request.headers.get('Range')

    # Parsing Range Header
    if range_header:
        try:
            range_val = range_header.replace('bytes=', '').strip()
            parts = range_val.split('-')
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
        except Exception:
            start = 0
            end = file_size - 1

        if start >= file_size or start > end:
            return web.Response(
                status=416,
                headers={
                    'Content-Range': f'bytes */{file_size}',
                    'Access-Control-Allow-Origin': cors_origin
                }
            )

        end = min(end, file_size - 1)
        req_length = end - start + 1

        headers = {
            'Content-Type': mime_type,
            'Content-Range': f'bytes {start}-{end}/{file_size}',
            'Content-Length': str(req_length),
            'Accept-Ranges': 'bytes',
            'Access-Control-Allow-Origin': cors_origin,
            'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
            'Access-Control-Allow-Headers': 'Range, Origin, Accept, Content-Type',
            'Cache-Control': 'public, max-age=31536000',
        }

        response = web.StreamResponse(status=206, headers=headers)
        await response.prepare(request)

        start_chunk = start // CHUNK_SIZE
        end_chunk = end // CHUNK_SIZE
        first_chunk_offset = start % CHUNK_SIZE

        bytes_sent = 0
        try:
            for c_idx in range(start_chunk, end_chunk + 1):
                if bytes_sent >= req_length:
                    break

                # Prefetch beberapa chunk berikutnya secara paralel di background
                for p_offset in range(1, PREFETCH_CHUNKS + 1):
                    prefetch_chunk(msg_id, message, c_idx + p_offset, total_chunks)

                chunk = await fetch_chunk(msg_id, message, c_idx)
                if not chunk:
                    break

                # Potong awal chunk jika start bukan di kelipatan 1MB
                if c_idx == start_chunk:
                    chunk = chunk[first_chunk_offset:]

                # Potong akhir chunk jika melebihi panjang yang diminta
                needed = req_length - bytes_sent
                if len(chunk) > needed:
                    chunk = chunk[:needed]

                await response.write(chunk)
                bytes_sent += len(chunk)

        except (ConnectionResetError, asyncio.CancelledError):
            pass

        return response

    else:
        # Permintaan penuh tanpa header Range
        headers = {
            'Content-Type': mime_type,
            'Content-Length': str(file_size),
            'Accept-Ranges': 'bytes',
            'Access-Control-Allow-Origin': cors_origin,
            'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
            'Access-Control-Allow-Headers': 'Range, Origin, Accept, Content-Type',
            'Cache-Control': 'public, max-age=31536000',
        }

        response = web.StreamResponse(status=200, headers=headers)
        await response.prepare(request)

        bytes_sent = 0
        try:
            for c_idx in range(total_chunks):
                # Prefetch beberapa chunk berikutnya secara paralel di background
                for p_offset in range(1, PREFETCH_CHUNKS + 1):
                    prefetch_chunk(msg_id, message, c_idx + p_offset, total_chunks)

                chunk = await fetch_chunk(msg_id, message, c_idx)
                if not chunk:
                    break

                await response.write(chunk)
                bytes_sent += len(chunk)

        except (ConnectionResetError, asyncio.CancelledError):
            pass

        return response


PREFETCH_CHUNKS = int(os.getenv('TELEGRAM_PREFETCH_CHUNKS', '6'))
CACHE_MAX_GB = float(os.getenv('TELEGRAM_CACHE_MAX_GB', '35.0'))
CACHE_TTL_HOURS = float(os.getenv('TELEGRAM_CACHE_TTL_HOURS', '72.0'))


def purge_old_cache():
    """Hapus file cache yang sudah kadaluarsa (TTL) atau jika total ukuran melebihi batas."""
    try:
        now = time.time()
        ttl_seconds = CACHE_TTL_HOURS * 3600
        max_bytes = CACHE_MAX_GB * 1024 * 1024 * 1024

        parts = list(CACHE_DIR.glob("*.part"))
        if not parts:
            return

        deleted = 0
        freed_bytes = 0

        # 1. Hapus partisi yang umurnya lebih dari TTL (misal 6 jam)
        remaining_parts = []
        for p in parts:
            try:
                st = p.stat()
                if (now - st.st_mtime) > ttl_seconds:
                    freed_bytes += st.st_size
                    p.unlink()
                    deleted += 1
                else:
                    remaining_parts.append((p, st.st_size, st.st_mtime))
            except Exception:
                pass

        # 2. Jika total ukuran masih melebihi kuota (misal 3 GB), buang yang paling lama (LRU)
        total_size = sum(size for _, size, _ in remaining_parts)
        if total_size > max_bytes:
            # Urutkan berdasarkan waktu modifikasi (tertua duluan)
            remaining_parts.sort(key=lambda item: item[2])
            target_size = max_bytes * 0.6  # Turunkan sampai 60% kuota
            for p, size, _ in remaining_parts:
                try:
                    p.unlink()
                    deleted += 1
                    freed_bytes += size
                    total_size -= size
                    if total_size <= target_size:
                        break
                except Exception:
                    pass

        if deleted > 0:
            logger.info(f"[Cache Cleaner] Dibersihkan: {deleted} part ({freed_bytes / (1024*1024):.1f} MB). Sisa cache: {total_size / (1024*1024):.1f} MB (Maks: {CACHE_MAX_GB} GB)")

    except Exception as e:
        logger.error(f"Error di purge_old_cache: {e}")


async def clean_cache_loop():
    """Loop otomatis pembersih cache setiap 10 menit agar storage server selalu hemat dan aman."""
    while True:
        try:
            purge_old_cache()
        except Exception as e:
            logger.error(f"Error di clean_cache_loop: {e}")
        await asyncio.sleep(600)  # Cek setiap 10 menit


async def start_server():
    if not API_ID or not BOT_TOKEN or not CHANNEL_ID:
        print("\033[91m[ERROR] Konfigurasi Telegram (.env) belum diisi!\033[0m")
        print("\033[93mIsi TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID di .env\033[0m")
        sys.exit(1)

    print("\033[96m[*] Menghubungkan bot ke server Telegram MTProto...\033[0m")
    await tg_client.start()
    me = await tg_client.get_me()
    print(f"\033[92m[✓] Bot terhubung: @{me.username}\033[0m")

    # Jalankan background cleaner
    asyncio.create_task(clean_cache_loop())

    app = web.Application()
    app.add_routes(routes)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

    print("\n\033[92m====================================================\033[0m")
    print("\033[92m   NIPNIME FASTSTREAM PROXY (RANGE 206 + DISK CACHE)!\033[0m")
    print(f"\033[97m   Listening: http://0.0.0.0:{PORT}\033[0m")
    print(f"\033[97m   Cache Dir: {CACHE_DIR}\033[0m")
    print("\033[92m====================================================\033[0m\n")

    while True:
        await asyncio.sleep(3600)


if __name__ == '__main__':
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        print("\n[!] Stream Proxy dihentikan.")
