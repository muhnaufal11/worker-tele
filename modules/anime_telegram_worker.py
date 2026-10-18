#!/usr/bin/env python3
"""
Nipnime Ongoing Anime Multi-Source First-Release & Resolution Backfill Worker
=============================================================================
Konsep Utama & Alur Kerja:
1. Pemantau Feed Rilisan Baru Otomatis (Ongoing Anime Release Watcher):
   - Memantau halaman update/terbaru dari 3 sumber anime:
     * AnimeSail (https://v1.animesail.xyz)
     * Kuramanime (https://v20.kuramanime.ing)
     * NontonAnimeID (https://s13.nontonanimeid.boats)
2. Siapa Cepat Dia Dapat (First-to-Release Fast Ingest):
   - Ketiga sumber tidak merilis episode di menit yang sama.
   - Begitu suatu anime ongoing merilis episode baru di salah satu sumber (yang rilis tercepat/duluan):
   - Sistem LANGSUNG mendeteksi dan mengambil episode tersebut tanpa menunggu sumber lain.
   - Mengunduh resolusi yang sudah tersedia saat itu (misal baru ada 720p).
   - Langsung upload ke Telegram MTProto (streaming player hingga 2GB) dan disetor ke website Nipnime,
     sehingga pengunjung Nipnime bisa langsung menonton secepat mungkin!
3. Cek Ulang & Lengkapi Resolusi Lain (Resolution Backfiller):
   - Episode yang baru memiliki resolusi sebagian (misal 720p saja) akan dipantau terus secara aktif.
   - Sistem secara berkala mengecek ulang ke sumber awal maupun sumber lain yang menyusul rilis
     apakah resolusi lain (1080p, 480p, 360p) sudah tersedia.
   - Begitu resolusi susulan (misal 1080p) muncul di salah satu sumber, sistem otomatis
     mengunduh resolusi tersebut dan mengunggahnya ke Telegram CDN hingga semua resolusi lengkap!
"""

import os
import sys
import re
import time
import json
import html
import asyncio
import threading
import signal
import atexit

# Pastikan MainThread selalu memiliki event loop aktif (Fix Pyrogram sync di Python 3.12 - 3.14)
try:
    asyncio.get_running_loop()
except RuntimeError:
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass
import difflib
import argparse
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
import base64
import socket
import ssl
import uuid
import urllib.request
from urllib.parse import urlparse, quote, unquote, urljoin, urlencode, parse_qs, urlunparse

# Modul Pendukung Batch Ingestion Kusonime, Kuramanime, AnimeSail & Archive Manager
try:
    from modules.kusonime_scraper import search_kusonime, match_kusonime_result, parse_kusonime_batch_page, resolve_kusonime_download_link
    from modules.batch_archive_manager import get_7z_binary, disk_space_guard, list_archive_contents, extract_single_episode, stream_compatibility_guard, cleanup_file, set_archive_logger, format_bytes
    from modules.batch_source_aggregator import resolve_batch_direct_url, resolve_desustream_full, parse_otakudesu_batch_page, resolve_gdrive_to_direct
except ImportError:
    try:
        from kusonime_scraper import search_kusonime, match_kusonime_result, parse_kusonime_batch_page, resolve_kusonime_download_link
        from batch_archive_manager import get_7z_binary, disk_space_guard, list_archive_contents, extract_single_episode, stream_compatibility_guard, cleanup_file, set_archive_logger, format_bytes
        from batch_source_aggregator import resolve_batch_direct_url, resolve_desustream_full, parse_otakudesu_batch_page, resolve_gdrive_to_direct
    except ImportError:
        search_kusonime = None
        match_kusonime_result = None
        parse_kusonime_batch_page = None
        resolve_kusonime_download_link = None
        get_7z_binary = None
        disk_space_guard = None
        list_archive_contents = None
        extract_single_episode = None
        stream_compatibility_guard = None
        cleanup_file = None
        set_archive_logger = None
        format_bytes = lambda b: f"{b} B"
        extract_single_episode = None
        stream_compatibility_guard = None
        cleanup_file = None
        resolve_batch_direct_url = None
        resolve_desustream_full = None
        parse_otakudesu_batch_page = None
        resolve_gdrive_to_direct = None

# Modul Smart Watchdog & Auto-Debug Engine (Zero-Delta Tracking)
try:
    from modules.worker_smart_debugger import SmartWorkerDebugger
except ImportError:
    try:
        from worker_smart_debugger import SmartWorkerDebugger
    except ImportError:
        SmartWorkerDebugger = None

SMART_DEBUGGER = None

# Pastikan output konsol Windows mendukung Unicode / UTF-8
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Pastikan timezone sistem & log selalu menggunakan WIB (Asia/Jakarta / UTC+7)
os.environ['TZ'] = 'Asia/Jakarta'
if hasattr(time, 'tzset'):
    try:
        time.tzset()
    except Exception:
        pass

try:
    from zoneinfo import ZoneInfo
    WIB_TZ = ZoneInfo("Asia/Jakarta")
except Exception:
    from datetime import timezone, timedelta
    WIB_TZ = timezone(timedelta(hours=7))

def now_wib():
    return datetime.now(WIB_TZ)

# Auto-install paket yang dibutuhkan jika berjalan di Google Colab / runtime baru
REQUIRED_PKGS = {
    'pyrogram': 'pyrogram',
    'cryptography': 'cryptography',
    'aiohttp': 'aiohttp',
    'dotenv': 'python-dotenv',
}

def _pip_install(pkg: str) -> bool:
    import subprocess
    for cmd in (
        [sys.executable, "-m", "pip", "install", "-q", "--break-system-packages", pkg],
        [sys.executable, "-m", "pip", "install", "-q", pkg]
    ):
        try:
            r = subprocess.run(cmd)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    return False

_missing = []
for _mod, _pkg in REQUIRED_PKGS.items():
    try:
        __import__(_mod)
    except ImportError:
        _missing.append(_pkg)

if _missing:
    print(f"[SETUP] Paket {_missing} belum terpasang. Memasang otomatis melalui pip...")
    for _pkg in _missing:
        if _pip_install(_pkg):
            print(f"[SETUP] ✓ Berhasil memasang paket: {_pkg}!")
        else:
            print(f"[SETUP] Peringatan saat memasang paket otomatis {_pkg}")

# Refresh sys.path agar paket yang baru dipasang ke ~/.local langsung terbaca di proses ini
import site
try:
    _u_site = site.getusersitepackages()
    if _u_site and _u_site not in sys.path:
        sys.path.insert(0, _u_site)
        site.addsitedir(_u_site)
except Exception:
    pass

# Akselerasi Hardware MTProto Telegram (TgCrypto)
# SANGAT KRUSIAL: Tanpa TgCrypto, Pyrogram fallback ke pure-Python PyAES yang membatasi kecepatan upload hanya ~0.3 MB/s!
# Dengan TgCrypto, enkripsi AES-IGE diakselerasi via C/Assembly AES-NI, tembus 20 - 40+ MB/s di Google Colab & Laptop!
HAS_TGCRYPTO = False
try:
    import tgcrypto
    HAS_TGCRYPTO = True
except ImportError:
    if os.path.exists('/content') or 'google.colab' in sys.modules:
        for _pkg in ('TgCrypto-pyrofork', 'tgcrypto'):
            if _pip_install(_pkg):
                try:
                    import tgcrypto
                    HAS_TGCRYPTO = True
                    break
                except Exception:
                    pass

# Akselerasi Event Loop Linux (uvloop untuk Google Colab, Azure & AWS)
if sys.platform != 'win32':
    try:
        import uvloop
        uvloop.install()
        asyncio.set_event_loop(asyncio.new_event_loop())
    except ImportError:
        if os.path.exists('/content') or 'google.colab' in sys.modules:
            if _pip_install("uvloop"):
                try:
                    import uvloop
                    uvloop.install()
                    asyncio.set_event_loop(asyncio.new_event_loop())
                except Exception:
                    pass

# Pastikan MainThread memiliki active event loop sebelum import Pyrogram (Fix Pyrogram sync di Python 3.12 - 3.14 / uvloop Colab)
try:
    _main_loop = asyncio.get_event_loop()
    if _main_loop is None or _main_loop.is_closed():
        asyncio.set_event_loop(asyncio.new_event_loop())
except Exception:
    asyncio.set_event_loop(asyncio.new_event_loop())

try:
    from dotenv import load_dotenv
    load_dotenv()
    if 'SCRIPT_DIR' in globals():
        load_dotenv(SCRIPT_DIR / '.env')
except ImportError:
    pass

import math
import inspect
import functools
from pathlib import PurePath
from typing import Union, Callable, BinaryIO
import aiohttp

# Pastikan lagi sebelum import pyrogram
try:
    asyncio.get_event_loop()
except Exception:
    asyncio.set_event_loop(asyncio.new_event_loop())

from pyrogram import Client, utils, raw, StopTransmission
from pyrogram.session import Session, Auth
from pyrogram.session.internals.data_center import DataCenter
from pyrogram.connection.connection import Connection
from pyrogram.connection.transport import TCPAbridgedO, TCPAbridged, TCPIntermediateO

_CURRENT_TG_PORT = int(os.getenv('TG_PORT', '443'))
_CURRENT_TG_IP = os.getenv('TG_IP', '91.108.56.130')
_orig_dc_new = DataCenter.__new__

def _smart_dc_new(cls, dc_id: int, test_mode: bool, ipv6: bool, media: bool):
    global _CURRENT_TG_IP, _CURRENT_TG_PORT
    if _CURRENT_TG_IP:
        return _CURRENT_TG_IP, _CURRENT_TG_PORT
    ip, _ = _orig_dc_new(cls, dc_id, test_mode, ipv6, media)
    return ip, _CURRENT_TG_PORT

DataCenter.__new__ = _smart_dc_new

def set_telegram_dc_port(port: int):
    global _CURRENT_TG_PORT
    _CURRENT_TG_PORT = int(port)

def set_telegram_dc_target(ip, port: int):
    global _CURRENT_TG_IP, _CURRENT_TG_PORT
    _CURRENT_TG_IP = str(ip) if ip else None
    _CURRENT_TG_PORT = int(port)

_orig_conn_connect = Connection.connect

async def _smart_conn_connect(self):
    """
    Koneksi pintar multi-protokol MTProto:
    Utamakan TCPAbridgedO (Obfuscated MTProto) yang mengenkripsi handshake awal 64-byte acak
    sehingga kebal dari pemblokiran Deep Packet Inspection (DPI) Mikrotik/ISP warnet!
    Jika gagal, fallback ke TCPIntermediateO atau TCPAbridged biasa.
    """
    protocols_to_try = [TCPAbridgedO, TCPIntermediateO, TCPAbridged]
    last_err = None
    for proto_cls in protocols_to_try:
        self.protocol = proto_cls(self.ipv6, self.proxy)
        try:
            await self.protocol.connect(self.address)
            return
        except OSError as e:
            last_err = e
            try:
                await self.protocol.close()
            except Exception:
                pass
            await asyncio.sleep(0.5)
    raise last_err or ConnectionError("Semua protokol MTProto gagal terhubung")

Connection.connect = _smart_conn_connect
from pyrogram.file_id import FileId
from pyrogram.methods.advanced.save_file import SaveFile

try:
    from curl_cffi import requests as c_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

# Fix Pyrogram 64-bit channel ID support (Telegram channel ID > 2 miliar)
utils.MIN_CHANNEL_ID = -10099999999999

# Root direktori terop-worker
current_file = Path(__file__).resolve()
if current_file.parent.name == 'modules':
    SCRIPT_DIR = current_file.parent.parent
else:
    SCRIPT_DIR = current_file.parent

MODULES_DIR = Path(__file__).resolve().parent
if str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Load .env
try:
    if 'load_dotenv' in globals():
        ENV_PATH = SCRIPT_DIR / '.env'
        if ENV_PATH.exists():
            load_dotenv(dotenv_path=ENV_PATH)
        else:
            load_dotenv()
except Exception:
    pass

def _sec_dec(cipher_b64: str, key: str = "nipnime_shield_2026") -> str:
    try:
        raw = base64.b64decode(cipher_b64.encode('utf-8'))
        key_bytes = key.encode('utf-8')
        dec = bytes([b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(raw)])
        return dec.decode('utf-8', errors='ignore')
    except Exception:
        return ""

# Konfigurasi Nipnime API (Terenkripsi secara in-memory, tanpa butuh file .env di disk!)
API_URL = (os.getenv('API_URL') or _sec_dec('Bh0EHhpXSnAdARkLBQk6HFNdW0EIAAdGGQAtHBg=')).rstrip('/')
WORKER_TOKEN = (os.getenv('WORKER_TOKEN') or _sec_dec('AAAAAAAAAAAHDRsKHDssV1NAUxo2GwsQMldvQV4=')).strip()

# Konfigurasi Telegram (Terenkripsi secara in-memory)
API_ID = (os.getenv('TELEGRAM_API_ID') or _sec_dec('XV5AXlBZV2s=')).strip()
API_HASH = (os.getenv('TELEGRAM_API_HASH') or _sec_dec('VwxBWw9VVWYSCl4DVF1qUFNWBllRRg1aW11nQl1QXAg=')).strip()
BOT_TOKEN = (os.getenv('TELEGRAM_BOT_TOKEN') or _sec_dec('Vl9BXVxdU2dBWVMkLSwbBQRaTwUqRD0iJTA7By4YDB4wBWZTSAEjIwFZAlUGFg==')).strip()
CHANNEL_ID = (os.getenv('TELEGRAM_CHANNEL_ID') or _sec_dec('Q1hAXl1ZV2dLX1pRXFQ=')).strip()
STREAM_BASE_URL = (os.getenv('TELEGRAM_STREAM_BASE_URL') or _sec_dec('Bh0EHhpXSnAdARkLBQk6HFNdW0EdF0MaGRc6EgU=')).rstrip('/')

def sync_request_nipnime_api(method: str, endpoint_or_url: str, json_data: dict = None, headers: dict = None, timeout: int = 15) -> tuple[int, dict | None]:
    """Mengirim HTTP request ke API Nipnime dengan bypass otomatis Cloudflare WAF (curl_cffi Chrome TLS)
    dan fallback urllib jika curl_cffi tidak tersedia."""
    url = endpoint_or_url if endpoint_or_url.startswith('http') else f"{API_URL.rstrip('/')}/{endpoint_or_url.lstrip('/')}"
    req_headers = {
        'X-Terop-Token': WORKER_TOKEN,
        'Authorization': f"Bearer {WORKER_TOKEN}",
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': DEFAULT_UA
    }
    try:
        if 'get_worker_id' in globals():
            w_id = get_worker_id()
            if w_id:
                req_headers['X-Worker-Id'] = str(w_id)
        if '_CURRENT_SCRIPT_HASH' in globals() and _CURRENT_SCRIPT_HASH:
            req_headers['X-Script-Hash'] = str(_CURRENT_SCRIPT_HASH)
        elif 'get_current_script_hash' in globals():
            s_h = get_current_script_hash()
            if s_h:
                req_headers['X-Script-Hash'] = str(s_h)
    except Exception:
        pass

    if headers:
        req_headers.update(headers)

    def _check_upgrade_guard(status_code: int, resp_payload: any):
        if status_code == 426 or (isinstance(resp_payload, dict) and (resp_payload.get('upgrade_required') or resp_payload.get('error') == 'upgrade_required')):
            if 'activate_update_quarantine' in globals():
                activate_update_quarantine("Respon Server: HTTP 426 Upgrade Required / Versi Script Kadaluarsa")
            if isinstance(resp_payload, dict) and resp_payload.get('download_url') and not globals().get('_AUTO_UPDATE_IN_PROGRESS', False):
                if 'schedule_or_run_auto_update' in globals():
                    schedule_or_run_auto_update(resp_payload.get('download_url'), resp_payload.get('script_hash'))

    if HAS_CURL_CFFI:
        try:
            fn = c_requests.post if method.upper() == 'POST' else c_requests.get
            c_resp = fn(
                url,
                json=json_data if method.upper() == 'POST' else None,
                params=json_data if method.upper() == 'GET' else None,
                headers=req_headers,
                impersonate="chrome",
                timeout=timeout,
                verify=False
            )
            data = None
            try:
                data = c_resp.json()
            except Exception:
                pass
            _check_upgrade_guard(c_resp.status_code, data)
            return c_resp.status_code, data
        except Exception:
            pass

    try:
        import urllib.request
        data_bytes = json.dumps(json_data).encode('utf-8') if (json_data and method.upper() == 'POST') else None
        req = urllib.request.Request(url, data=data_bytes, headers=req_headers, method=method.upper())
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = None
            try:
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))
            except Exception:
                pass
            _check_upgrade_guard(resp.status, data)
            return resp.status, data
    except Exception as e:
        data = None
        code = getattr(e, 'code', 0)
        try:
            if hasattr(e, 'read'):
                data = json.loads(e.read().decode('utf-8', errors='ignore'))
        except Exception:
            pass
        _check_upgrade_guard(code, data)
        return code, data

async def async_request_nipnime_api(method: str, endpoint_or_url: str, json_data: dict = None, headers: dict = None, timeout: int = 15) -> tuple[int, dict | None]:
    """Versi asinkron dari sync_request_nipnime_api (dijalankan via asyncio.to_thread)."""
    return await asyncio.to_thread(sync_request_nipnime_api, method, endpoint_or_url, json_data, headers, timeout)

def _probe_local_port(port, host="127.0.0.1"):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)
        res = s.connect_ex((host, int(port)))
        s.close()
        return res == 0
    except Exception:
        return False

def _is_socks5_proxy(host, port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4)
        s.connect((host, int(port)))
        s.sendall(b"\x05\x01\x00")
        resp = s.recv(2)
        s.close()
        return resp.startswith(b"\x05")
    except Exception:
        return False

def _get_windows_system_proxy():
    if sys.platform != 'win32':
        return None
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        try:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if enabled:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
                if server:
                    return str(server).strip()
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass
    return None

def _find_psiphon_ports():
    if sys.platform != 'win32':
        return []
    try:
        import subprocess
        pid_res = subprocess.run(
            ['tasklist', '/fi', 'imagename eq psiphon*', '/fo', 'csv', '/nh'],
            capture_output=True, text=True, timeout=2
        )
        pids = []
        for line in pid_res.stdout.strip().splitlines():
            parts = line.split(',')
            if len(parts) >= 2:
                pid_clean = parts[1].strip('"').strip()
                if pid_clean.isdigit():
                    pids.append(pid_clean)
        if not pids:
            return []
        
        ns_res = subprocess.run(
            ['netstat', '-ano', '-p', 'tcp'],
            capture_output=True, text=True, timeout=3
        )
        found_ports = []
        for line in ns_res.stdout.splitlines():
            line = line.strip()
            if 'LISTENING' in line:
                for pid in pids:
                    if line.endswith(pid):
                        tokens = line.split()
                        if len(tokens) >= 2:
                            local_addr = tokens[1]
                            if ':' in local_addr:
                                port_str = local_addr.rsplit(':', 1)[1]
                                if port_str.isdigit():
                                    p = int(port_str)
                                    if p not in found_ports:
                                        found_ports.append(p)
        return found_ports
    except Exception:
        return []

def _test_proxy_to_telegram(scheme, host, port):
    targets = [("91.108.56.130", 443), ("149.154.167.51", 443)]
    for tip, tport in targets:
        try:
            import socks
            s = socks.socksocket(socket.AF_INET, socket.SOCK_STREAM)
            s.set_proxy(proxy_type=getattr(socks, scheme.upper()), addr=host, port=int(port))
            s.settimeout(2.5)
            s.connect((tip, int(tport)))
            s.close()
            return True
        except Exception:
            pass
    return False

def get_all_available_proxies():
    """Mengumpulkan semua kandidat proxy lokal yang sedang aktif."""
    proxies = []
    
    # Env manual
    p_str = os.getenv('TG_PROXY') or os.getenv('TELEGRAM_PROXY') or os.getenv('ALL_PROXY') or os.getenv('HTTPS_PROXY')
    if p_str:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(p_str)
            scheme = (parsed.scheme or 'socks5').lower()
            if scheme in ('http', 'https', 'socks4', 'socks5'):
                proxies.append({
                    'scheme': scheme,
                    'hostname': parsed.hostname or '127.0.0.1',
                    'port': parsed.port or (1080 if 'socks' in scheme else 8080),
                    '_label': f'Env Proxy ({parsed.hostname}:{parsed.port})'
                })
        except Exception:
            pass

    # Windows Registry Proxy (Psiphon, sistem)
    win_proxy_str = _get_windows_system_proxy()
    if win_proxy_str:
        try:
            candidates = {}
            if '=' in win_proxy_str:
                for part in win_proxy_str.split(';'):
                    if '=' in part:
                        proto, addr = part.split('=', 1)
                        if ':' in addr:
                            h, p = addr.split(':', 1)
                            candidates[proto.strip().lower()] = (h.strip(), int(p.strip()))
            elif ':' in win_proxy_str:
                h, p = win_proxy_str.split(':', 1)
                candidates['http'] = (h.strip(), int(p.strip()))

            # Utamakan HTTP CONNECT untuk Psiphon karena jauh lebih kompatibel dengan raw IP Telegram MTProto
            if 'http' in candidates:
                hh, hp = candidates['http']
                if _probe_local_port(hp, hh):
                    proxies.append({'scheme': 'http', 'hostname': hh, 'port': hp, '_label': f'Windows HTTP Proxy ({hh}:{hp})'})
            if 'socks' in candidates:
                sh, sp = candidates['socks']
                if _probe_local_port(sp, sh):
                    proxies.append({'scheme': 'socks5', 'hostname': sh, 'port': sp, '_label': f'Windows SOCKS5 Proxy ({sh}:{sp})'})
        except Exception:
            pass

    # Port dari proses Psiphon
    for p in _find_psiphon_ports():
        if _probe_local_port(p):
            proxies.append({'scheme': 'http', 'hostname': '127.0.0.1', 'port': p, '_label': f'Psiphon HTTP Proxy ({p})'})
            proxies.append({'scheme': 'socks5', 'hostname': '127.0.0.1', 'port': p, '_label': f'Psiphon SOCKS5 Proxy ({p})'})

    # Static ports
    for p, sch, lbl in [(40000, 'socks5', 'WARP Proxy'), (1080, 'socks5', 'SOCKS5 Proxy'), (8080, 'http', 'HTTP Proxy')]:
        if _probe_local_port(p):
            proxies.append({'scheme': sch, 'hostname': '127.0.0.1', 'port': p, '_label': lbl})

    seen = set()
    unique_proxies = []
    for px in proxies:
        key = (px['scheme'], px['hostname'], px['port'])
        if key not in seen:
            seen.add(key)
            unique_proxies.append(px)

    return unique_proxies

def get_telegram_proxy_config(attempt: int = 1):
    """Membaca proxy terbaik yang terbukti lolos uji koneksi ke Telegram."""
    avail = get_all_available_proxies()
    if not avail:
        return None
    
    # Cek apakah ada yang sudah lolos uji koneksi ke Telegram
    for px in avail:
        if _test_proxy_to_telegram(px['scheme'], px['hostname'], px['port']):
            return px

    # JANGAN PERNAH kembalikan proxy yang belum lolos tes agar Pyrogram tidak macet/freeze di thread!
    return None

def check_telegram_dc_reachable(timeout=3.5):
    """Cek apakah IP Data Center Telegram MTProto dapat dijangkau dari jaringan ini."""
    test_targets = [
        ("149.154.167.51", 443),  # DC 2 (Eropa/Utama)
        ("149.154.167.91", 443),  # DC 4
        ("91.108.56.130", 443),   # DC 5 (Singapura/Asia)
    ]
    for ip, port in test_targets:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            res = s.connect_ex((ip, port))
            s.close()
            if res == 0:
                return True
        except Exception:
            pass
    return False

_DOH_CACHE = {}

def resolve_doh(hostname):
    """Resolve domain name using Cloudflare DoH (DNS-over-HTTPS) to bypass ISP DNS hijacking / blocking."""
    if not hostname or not isinstance(hostname, str):
        return hostname
    if hostname in _DOH_CACHE:
        return _DOH_CACHE[hostname]
    if re.match(r'^\d+\.\d+\.\d+\.\d+$', hostname) or ':' in hostname or hostname in ('localhost', '127.0.0.1'):
        return hostname
    for doh_url in [
        f"https://1.1.1.1/dns-query?name={quote(hostname)}&type=A",
        f"https://dns.google/resolve?name={quote(hostname)}&type=A"
    ]:
        try:
            req = urllib.request.Request(
                doh_url,
                headers={"accept": "application/dns-json", "User-Agent": "curl/8.0"}
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for ans in data.get("Answer", []):
                    if ans.get("type") == 1:
                        ip = ans.get("data")
                        if ip and re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                            _DOH_CACHE[hostname] = ip
                            return ip
        except Exception:
            pass
    return hostname

_orig_getaddrinfo = socket.getaddrinfo

def _smart_getaddrinfo(host, port, *args, **kwargs):
    try:
        res = _orig_getaddrinfo(host, port, *args, **kwargs)
        if res and isinstance(host, str) and not host.startswith(('127.', '10.', '192.168.', 'localhost')):
            first_ip = res[0][4][0]
            if first_ip in ('127.0.0.1', '0.0.0.0', '118.98.96.126', '36.86.63.181', '36.86.63.182'):
                doh_ip = resolve_doh(host)
                if doh_ip != host:
                    return _orig_getaddrinfo(doh_ip, port, *args, **kwargs)
        return res
    except socket.gaierror:
        doh_ip = resolve_doh(host)
        if doh_ip != host:
            return _orig_getaddrinfo(doh_ip, port, *args, **kwargs)
        raise

socket.getaddrinfo = _smart_getaddrinfo


# Direktori unduhan sementara & penyimpanan status pelacak kualitas

# Direktori unduhan sementara & penyimpanan status pelacak kualitas
TEMP_DOWNLOAD_DIR = SCRIPT_DIR / 'temp_videos'
TEMP_DOWNLOAD_DIR.mkdir(exist_ok=True)
ONGOING_STATE_FILE = SCRIPT_DIR / '.ongoing_quality_state.json'

def get_disk_free_mb(target_dir=None) -> float:
    """Mengembalikan sisa kapasitas disk kosong dalam MB pada direktori target."""
    try:
        d = Path(target_dir or TEMP_DOWNLOAD_DIR).resolve()
        while not d.exists() and d.parent != d:
            d = d.parent
        total, used, free = shutil.disk_usage(str(d))
        return free / (1024 * 1024)
    except Exception:
        return 99999.0

def clean_stale_temp_files(max_age_sec: int = 1800, force_emergency: bool = False) -> int:
    """
    Sistem Pembersih & Proteksi Disk Otomatis (Disk Guard & Auto-Prune):
    1. Menghapus semua file .tmp, .part, .crdownload, .temp tanpa terkecuali.
    2. Menghapus file .mp4 di temp_videos yang sudah berumur > max_age_sec dan tidak sedang aktif di-upload/render.
    3. Jika force_emergency=True (sisa disk < 2.5 GB), memangkas file video tertua hingga sisa disk >= 3.5 GB.
    """
    deleted_count = 0
    freed_bytes = 0
    try:
        now_ts = time.time()
        dirs_to_clean = [TEMP_DOWNLOAD_DIR, SCRIPT_DIR / '.update_tmp']

        active_file_names = set()
        if 'PROGRESS_MGR' in globals():
            try:
                with PROGRESS_MGR.lock:
                    for k, t in list(PROGRESS_MGR.tasks.items()):
                        lbl = t.get('label', '')
                        for part in lbl.split():
                            if part.endswith('.mp4'):
                                active_file_names.add(part)
            except Exception:
                pass

        all_files = []
        for d in dirs_to_clean:
            if d.exists() and d.is_dir():
                for f in d.glob('*'):
                    if f.is_file():
                        all_files.append(f)

        # 1. Hapus file sampah sementara (.tmp, .part, .crdownload)
        for f in all_files:
            if f.suffix.lower() in ('.tmp', '.part', '.crdownload', '.temp') or f.name.startswith('.update_'):
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    deleted_count += 1
                    freed_bytes += sz
                except Exception:
                    pass

        # 2. Periksa file video (.mp4, .mkv, .avi, .ts, .webm) dan file arsip batch (.rar, .zip, .7z, .r00) yang usang
        STALE_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.ts', '.webm', '.rar', '.zip', '.7z', '.r00')
        candidate_files = [f for f in all_files if f.is_file() and f.suffix.lower() in STALE_EXTENSIONS and f.name not in active_file_names]
        candidate_files.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0)

        for f in candidate_files:
            if not f.exists():
                continue
            try:
                f_age = now_ts - f.stat().st_mtime
                sz = f.stat().st_size
                if f_age > max_age_sec or force_emergency:
                    f.unlink()
                    deleted_count += 1
                    freed_bytes += sz
                    if force_emergency and get_disk_free_mb() >= 3500:
                        break
            except Exception:
                pass

        # 3. Di Linux, bersihkan file sementara di /tmp jika nipnime_
        if sys.platform != 'win32' and force_emergency:
            try:
                for tmp_nip in Path('/tmp').glob('nipnime_*'):
                    try:
                        if tmp_nip.is_dir(): shutil.rmtree(tmp_nip, ignore_errors=True)
                        elif tmp_nip.is_file(): tmp_nip.unlink()
                    except Exception:
                        pass
            except Exception:
                pass

        if deleted_count > 0:
            mb_freed = freed_bytes / (1024 * 1024)
            if 'log' in globals() and 'GREEN' in globals():
                log("DISK_CLEAN", f"🧹 [AUTO CLEANUP] Berhasil membersihkan {deleted_count} file sementara ({mb_freed:.1f} MB ruang disk dibebaskan).", GREEN)
    except Exception:
        pass
    return deleted_count

def ensure_safe_disk_space(required_mb: float = 1200) -> bool:
    """
    Memastikan tersisa ruang disk yang cukup sebelum mengunduh atau mengekstrak file.
    Jika ruang disk < required_mb, otomatis menjalankan pembersihan darurat.
    """
    free_mb = get_disk_free_mb()
    if free_mb < required_mb:
        clean_stale_temp_files(max_age_sec=600, force_emergency=True)
        free_mb = get_disk_free_mb()

    if free_mb < 600:
        if 'log' in globals() and 'RED' in globals():
            log("DISK_CRITICAL", f"🚨 [RUANG DISK KRITIS] Sisa disk hanya {free_mb:.1f} MB (dibutuhkan {required_mb} MB)! Menunda operasi agar disk tidak crash.", RED)
        return False
    return True

_is_shutting_down = False

def cleanup_cancelled_or_shutdown_files():
    """Membersihkan seluruh file sementara, unduhan setengah jalan (.tmp/.part), dan sisa render saat proses dibatalkan atau dimatikan."""
    global _is_shutting_down
    if _is_shutting_down:
        return
    _is_shutting_down = True
    try:
        clean_stale_temp_files(max_age_sec=0, force_emergency=True)
    except Exception:
        pass

def _sig_shutdown_handler(signum, frame):
    try:
        if 'log' in globals() and 'YELLOW' in globals():
            log("SHUTDOWN", f"🛑 Worker dihentikan (Sinyal {signum}). Membersihkan berkas sementara...", YELLOW)
    except Exception:
        pass
    cleanup_cancelled_or_shutdown_files()
    sys.exit(0)

atexit.register(cleanup_cancelled_or_shutdown_files)
try:
    signal.signal(signal.SIGINT, _sig_shutdown_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, _sig_shutdown_handler)
except Exception:
    pass

if sys.platform.startswith('win'):
    LOCAL_FFMPEG = SCRIPT_DIR.parent / 'bin' / 'ffmpeg.exe'
    if not LOCAL_FFMPEG.exists():
        LOCAL_FFMPEG = SCRIPT_DIR / 'bin' / 'ffmpeg.exe'
    FFMPEG_PATH = str(LOCAL_FFMPEG) if LOCAL_FFMPEG.exists() else 'ffmpeg'
else:
    FFMPEG_PATH = shutil.which('ffmpeg') or '/usr/bin/ffmpeg' or 'ffmpeg'

# Konfigurasi Watermark Nipnime & 2K Upscaling
ENABLE_WATERMARK = os.getenv('ENABLE_WATERMARK', 'true').lower() in ('true', '1', 'yes')
ENABLE_2K_UPSCALE = os.getenv('ENABLE_2K_UPSCALE', 'true').lower() in ('true', '1', 'yes')
FAST_RELEASE_FIRST = os.getenv('FAST_RELEASE_FIRST', 'true').lower() in ('true', '1', 'yes')  # Rilis kilat: upload video mentah dulu agar web langsung tayang, lalu render & ganti susulan
ENABLE_DELOGO = os.getenv('ENABLE_DELOGO', 'false').lower() in ('true', '1', 'yes')  # Default FALSE: Tanpa blur/delogo (100% crystal sharp raw tanpa efek buram)
ENABLE_CROP = False  # Dinonaktifkan: Sesuai instruksi pengguna, DILARANG CROP (100% Full Frame Raw utuh)
WATERMARK_SINGLE_TEST = os.getenv('WATERMARK_SINGLE_TEST', '0').strip() in ('1', 'true', 'yes')
MAX_TEST_COUNT = int(os.getenv('TEST_LIMIT', '0'))
_watermark_test_count = 0

FONT_DIR = SCRIPT_DIR / 'bin' / 'fonts'
FONT_DIR.mkdir(parents=True, exist_ok=True)
MONTSERRAT_BLACK_PATH = FONT_DIR / 'Montserrat-Black.ttf'

DEFAULT_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)

def get_device_role() -> str:
    custom_role = os.getenv('WORKER_ROLE')
    if custom_role:
        return custom_role.lower()
    # Auto-detect GitHub Codespaces
    if os.getenv('CODESPACES') == 'true' or os.getenv('CODESPACE_NAME'):
        return 'codespace'
    if os.path.exists('/content') or 'google.colab' in sys.modules or os.path.exists('/work') or 'deepnote' in sys.modules or os.getenv('DEEPNOTE_PROJECT_ID'):
        return 'colab'
    # Auto-detect AWS EC2
    if os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION'):
        return 'aws'
    try:
        uuid_f = Path('/sys/hypervisor/uuid')
        if uuid_f.exists() and uuid_f.read_text(errors='ignore').strip().lower().startswith('ec2'):
            return 'aws'
    except Exception:
        pass
    cur_str = str(SCRIPT_DIR).lower()
    if 'systemcache' in cur_str or '.nipnime-worker' in cur_str or 'warnet' in cur_str:
        return 'warnet'
    return 'laptop' if sys.platform == 'win32' else 'server'

REMOTE_ROLES = ("laptop", "colab", "warnet", "azure", "aws", "oracle", "vps", "codespace")
CLOUD_ROLES = ("colab", "azure", "aws", "oracle", "vps", "codespace")

# Konfigurasi Microservice Puppeteer & FlareSolverr
# ATURAN KETAT: Microservice CasaOS (192.168.100.65 / port 3000 & 8191) HANYA untuk role == 'server'.
# Semua remote worker (Laptop, PC, Colab, Warnet, VPS dll) DILARANG KERAS melempar scraping/browser ke server CasaOS!
# Masing-masing remote worker memproses pekerjaannya secara mandiri.
if get_device_role() == 'server':
    PUPPETEER_URL = os.getenv('PUPPETEER_SERVICE_URL', 'http://127.0.0.1:3000').rstrip('/')
    FLARESOLVERR_URL = os.getenv('FLARESOLVERR_URL', 'http://127.0.0.1:8191/v1').rstrip('/')
else:
    # Remote worker hanya memakai jika menjalankan Puppeteer/FlareSolverr lokal di mesinnya sendiri (bukan CasaOS)
    _p_env = os.getenv('PUPPETEER_SERVICE_URL', '').rstrip('/')
    _f_env = os.getenv('FLARESOLVERR_URL', '').rstrip('/')
    PUPPETEER_URL = _p_env if (_p_env and '192.168.' not in _p_env and 'nipnime' not in _p_env) else ''
    FLARESOLVERR_URL = _f_env if (_f_env and '192.168.' not in _f_env and 'nipnime' not in _f_env) else ''

# Konfigurasi Multi-Worker Gotong Royong (Tanpa Partisi Shard Ganjil/Genap)
# Semua worker memantau dan memproses seluruh episode, dicegah tabrakan via Distributed Claim Lock
WORKER_SHARD = 'all'

def is_episode_in_shard(ep_num: any) -> bool:
    """Semua episode terbuka untuk seluruh worker (anti-tabrakan diatur via claim_episode_lock)."""
    return True

def get_shard_description() -> str:
    return "Semua Episode (Gotong Royong & Anti-Tabrakan)"


def is_2k_required() -> bool:
    """2K wajib diproses untuk semua video JIKA Colab, Laptop, atau Warnet (GPU) aktif."""
    if not ENABLE_2K_UPSCALE:
        return False
    role = get_device_role()
    force_server = os.getenv('FORCE_SERVER_WATERMARK', 'false').lower() in ('true', '1', 'yes')
    if role in ('colab', 'laptop', 'warnet') or check_has_nvenc() or force_server:
        return True
    return False

def get_target_qualities() -> list:
    """Daftar resolusi target: menyertakan 2k jika Colab/Laptop aktif."""
    if is_2k_required():
        return ['2k', '1080p', '720p', '480p', '360p']
    return ['1080p', '720p', '480p', '360p']

def check_has_nvenc() -> bool:
    global FFMPEG_PATH
    # Pastikan driver dan perangkat keras GPU NVIDIA benar-benar tersedia
    if not shutil.which('nvidia-smi'):
        return False
    try:
        chk = subprocess.run(['nvidia-smi'], capture_output=True, timeout=3)
        if chk.returncode != 0:
            return False
    except Exception:
        return False

    candidates = [
        '/tmp/btbn/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
        '/content/ffmpeg',
        '/usr/bin/ffmpeg',
        shutil.which('ffmpeg') or 'ffmpeg',
        FFMPEG_PATH
    ]
    if sys.platform.startswith('win'):
        candidates = [FFMPEG_PATH, str(SCRIPT_DIR / 'bin' / 'ffmpeg.exe'), shutil.which('ffmpeg') or 'ffmpeg']
    seen = set()
    uniq_cands = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            uniq_cands.append(c)

    best_cand = None
    for cand in uniq_cands:
        try:
            res = subprocess.run([cand, '-encoders'], capture_output=True, text=True, timeout=5)
            if 'h264_nvenc' in res.stdout:
                filt_res = subprocess.run([cand, '-filters'], capture_output=True, text=True, timeout=5)
                f_out = filt_res.stdout.lower()
                if 'overlay_cuda' in f_out and 'scale_cuda' in f_out:
                    FFMPEG_PATH = cand
                    _HAS_CUDA_OVERLAY_CACHE = True
                    return True
                if best_cand is None:
                    best_cand = cand
        except Exception:
            continue

    if best_cand:
        FFMPEG_PATH = best_cand
        return True
    return False

_HAS_CUDA_OVERLAY_CACHE = None

def check_has_cuda_overlay() -> bool:
    """Mengecek apakah FFmpeg mendukung filter hardware CUDA (overlay_cuda, scale_cuda, hwupload_cuda)."""
    global _HAS_CUDA_OVERLAY_CACHE, FFMPEG_PATH
    if _HAS_CUDA_OVERLAY_CACHE is not None:
        return _HAS_CUDA_OVERLAY_CACHE
    try:
        cand = FFMPEG_PATH or shutil.which('ffmpeg') or 'ffmpeg'
        res = subprocess.run([cand, '-filters'], capture_output=True, text=True, timeout=5)
        out = res.stdout.lower()
        has_it = ('overlay_cuda' in out and 'scale_cuda' in out and 'hwupload_cuda' in out)
        _HAS_CUDA_OVERLAY_CACHE = has_it
        return has_it
    except Exception:
        _HAS_CUDA_OVERLAY_CACHE = False
        return False

def ensure_gpu_and_ffmpeg_ready():
    """Mengecek & mengaktifkan GPU NVIDIA (RTX Laptop / Colab T4/L4/A100) serta FFmpeg NVENC Pure-CUDA acceleration."""
    global FFMPEG_PATH, _HAS_CUDA_OVERLAY_CACHE
    role = get_device_role()
    has_nvidia_gpu = shutil.which('nvidia-smi') is not None

    if has_nvidia_gpu:
        gpu_name = "NVIDIA GPU"
        try:
            res = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], capture_output=True, text=True, timeout=3)
            if res.stdout.strip():
                gpu_name = res.stdout.strip().splitlines()[0]
        except Exception:
            pass

        # Jika di Colab dan belum ada overlay_cuda, pasang binary BtbN Full-CUDA resmi (overlay_cuda + NVENC + scale_cuda)
        if role == 'colab' and not check_has_cuda_overlay():
            log("GPU_SETUP", f"⚡ {gpu_name} terdeteksi! Memasang FFmpeg Pure-CUDA (overlay_cuda + NVENC + scale_cuda) untuk Google Colab...", BOLD + CYAN)
            try:
                btbn_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
                cmd = (
                    "mkdir -p /tmp/btbn && "
                    f"curl -sL '{btbn_url}' | tar -xJ -C /tmp/btbn --strip-components=1 && "
                    "cp /tmp/btbn/bin/ffmpeg /usr/local/bin/ffmpeg 2>/dev/null || true"
                )
                subprocess.run(cmd, shell=True, timeout=120)
                _HAS_CUDA_OVERLAY_CACHE = None
                check_has_nvenc()
            except Exception as ce:
                log("GPU_SETUP_WARN", f"Pemasangan FFmpeg CUDA Colab kendala: {ce}", YELLOW)

        # Pastikan p7zip-full & unrar terpasang di Colab untuk ekstraksi batch archive RAR / ZIP
        if role == 'colab':
            try:
                if not shutil.which('7z') and not shutil.which('7zz'):
                    subprocess.run("apt-get update -qq && apt-get install -y -qq p7zip-full unrar >/dev/null 2>&1", shell=True, timeout=60)
            except Exception:
                pass

        if check_has_nvenc():
            mode_tag = "Pure-CUDA (overlay_cuda + NVENC)" if check_has_cuda_overlay() else "Hybrid GPU (NVENC Encode)"
            log("GPU_READY", f"🚀 [HARDWARE DETECTED] {gpu_name} & FFmpeg NVENC AKTIF! [{mode_tag}] ({role.upper()})", BOLD + GREEN)
            return

        # Fallback jika belum terpasang
        if role == 'colab':
            log("GPU_SETUP", f"⚡ Memasang FFmpeg NVENC standar untuk Google Colab...", BOLD + CYAN)
            try:
                cmd = "curl -sL https://raw.githubusercontent.com/XniceCraft/ffmpeg-colab/master/install | bash"
                subprocess.run(cmd, shell=True, timeout=60)
                _HAS_CUDA_OVERLAY_CACHE = None
                if check_has_nvenc():
                    log("GPU_SETUP", f"✓ Berhasil! FFmpeg NVENC aktif untuk {gpu_name}.", BOLD + GREEN)
                    return
            except Exception:
                pass
    else:
        if role == 'colab':
            log("GPU_WARN", "⚠️ GOOGLE COLAB BERJALAN PADA MODE CPU! GPU NVIDIA tidak terdeteksi.", BOLD + RED)
            log("GPU_WARN", "👉 Buka menu Colab: Runtime -> Change runtime type -> Hardware accelerator -> T4 GPU -> Save!", YELLOW)
        elif role == 'codespace':
            log("GPU_INFO", "ℹ️ GitHub Codespaces berjalan pada mode CPU Cloud (Gigabit Network Aktif).", CYAN)
        elif role == 'laptop':
            log("GPU_INFO", "ℹ️ GPU NVIDIA tidak terdeteksi via nvidia-smi. Menggunakan CPU fallback.", YELLOW)

def ensure_montserrat_font() -> str:
    """Memastikan font Montserrat-Black.ttf valid dan tersedia, mengunduh otomatis jika belum ada."""
    if MONTSERRAT_BLACK_PATH.exists() and MONTSERRAT_BLACK_PATH.stat().st_size > 50000:
        try:
            from PIL import ImageFont
            ImageFont.truetype(str(MONTSERRAT_BLACK_PATH), 20)
            return str(MONTSERRAT_BLACK_PATH)
        except Exception:
            try: MONTSERRAT_BLACK_PATH.unlink()
            except Exception: pass

    urls = [
        "https://nipnime.com/fonts/Montserrat-Black.ttf?v=2",
        "https://github.com/googlefonts/montserrat/raw/master/fonts/ttf/Montserrat-Black.ttf"
    ]
    import ssl, urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for u in urls:
        try:
            log("FONT", "Mengunduh font studio Montserrat-Black...", CYAN)
            req = urllib.request.Request(u, headers={'User-Agent': DEFAULT_UA})
            with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                data = r.read()
                if len(data) > 50000 and (data[:4] in (b'\x00\x01\x00\x00', b'OTTO', b'true')):
                    with open(MONTSERRAT_BLACK_PATH, 'wb') as f:
                        f.write(data)
                    log("FONT", "✓ Font Montserrat-Black siap digunakan!", GREEN)
                    return str(MONTSERRAT_BLACK_PATH)
        except Exception as fe:
            log("FONT_WARN", f"Gagal mengunduh font dari {u}: {fe}", YELLOW)

    # Fallback ke sistem font TrueType tebal jika download internet gagal
    system_fallbacks = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/seguisb.ttf"
    ]
    for sys_font in system_fallbacks:
        p = Path(sys_font)
        if p.exists() and p.stat().st_size > 10000:
            return str(p)

    return ""

def check_has_drawtext() -> bool:
    try:
        res = subprocess.run([FFMPEG_PATH, '-filters'], capture_output=True, text=True, timeout=5)
        return 'drawtext' in res.stdout
    except Exception:
        return False

def generate_watermark_png(quality: str, target_dir: Path, source_type: str = "clean") -> Path:
    """Menghasilkan file PNG transparan murni watermark studio NIPNIME.COM TANPA BACKGROUND BOX."""
    out_png = target_dir / f"wm_v3_{source_type}_{quality.lower().replace(' ', '_')}.png"
    if out_png.exists() and out_png.stat().st_size > 500:
        return out_png

    from PIL import Image, ImageDraw, ImageFont

    scale_map = {
        '360p': 0.5,
        '480p': 0.667,
        '720p': 1.0,
        '1080p': 1.5,
        '1440p': 2.0,
        '2k': 2.0,
        '2k qhd': 2.0
    }
    s = scale_map.get(quality.lower(), 1.0)
    sup = 2

    # Ukuran proporsional studio Montserrat-Black
    f_base = 22.0
    if source_type in ("nontonanimeid", "kuramanime"):
        stroke_base = 3.5  # Kontur tegas untuk menutupi logo luar secara bersih
    else:
        stroke_base = 2.2  # Kontur studio halus elegan

    f_size = int(f_base * s * sup)
    font_path = ensure_montserrat_font()
    font = None
    if font_path:
        try:
            font = ImageFont.truetype(font_path, f_size)
        except Exception:
            font = None

    if not font:
        try:
            font = ImageFont.load_default(size=f_size)
        except Exception:
            font = ImageFont.load_default()

    is_2k = quality.lower() in ('2k', '2k qhd', '1440p')
    if is_2k:
        text = "NIPNIME.COM • 2K ULTRA HD"
    else:
        text = "NIPNIME.COM"
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad = int(40 * s * sup)

    canvas = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    stroke_w = int(stroke_base * s * sup)

    # 1. Bayangan halus di bawah huruf (soft drop-shadow) untuk kedalaman 3D & kontras tinggi
    s_offset = int(2.5 * s * sup)
    d.text((pad - bbox[0] + s_offset, pad - bbox[1] + s_offset), text, font=font,
           fill=(0, 0, 0, 180), stroke_width=stroke_w, stroke_fill=(0, 0, 0, 180))

    # 2. Gambar outline hitam kontur tajam dan teks putih murni solid di atasnya
    d.text((pad - bbox[0], pad - bbox[1]), text, font=font,
           fill=(255, 255, 255, 255), stroke_width=stroke_w, stroke_fill=(0, 0, 0, 240))

    # 3. Trim rapat tepat di batas terluar teks (anti padding berlebih)
    cbox = canvas.split()[-1].getbbox()
    trimmed = canvas.crop(cbox)
    img_final = trimmed.resize((trimmed.width // sup, trimmed.height // sup), Image.Resampling.LANCZOS)

    img_final.save(out_png, "PNG")
    return out_png

def auto_detect_watermark(input_file: Path, source_info: str = "") -> tuple:
    """
    Auto-Detect Watermark Engine:
    Mendeteksi secara otomatis keberadaan dan tipe watermark dari sumber luar
    menggunakan analisis signature multi-sumber dan visual frame scanning.
    Mengembalikan (tipe_watermark, delogo_rect, deskripsi_mode).
    delogo_rect adalah dict koordinat relatif {'x': float, 'y': float, 'w': float, 'h': float} atau None jika video raw bersih.
    100% Full Frame Raw preserved (Dilarang Crop).
    """
    s_info = (source_info or '').lower()
    f_name = input_file.name.lower()

    # 1. Deteksi Cepat via Signature Sumber & Metadata
    is_na = any(k in s_info for k in ['nontonanime', 'kotakanime', 'nonton anime', 'naid']) or any(k in f_name for k in ['nontonanime', 'kotakanime'])
    if is_na:
        delogo_box = {'x': 0.022, 'y': 0.032, 'w': 0.152, 'h': 0.052}
        return "nontonanimeid", delogo_box, "NontonAnimeID Logo Erased (Top-Left Delogo Raw 100%)"

    is_km = any(k in s_info for k in ['kuramanime', 'kurama', 'kdrive', 'kuramadrive', 'k-drive']) or any(k in f_name for k in ['kuramanime', 'kurama', 'kdrive'])
    if is_km:
        delogo_box = {'x': 0.840, 'y': 0.020, 'w': 0.150, 'h': 0.050}
        return "kuramanime", delogo_box, "Kuramanime Logo Erased (Top-Right Delogo Raw 100%)"

    is_sm = any(k in s_info for k in ['samehadaku', 'samehadakucare', 'samehada']) or any(k in f_name for k in ['samehadaku', 'samehadakucare', 'samehada'])
    if is_sm:
        delogo_box = {'x': 0.001, 'y': 0.001, 'w': 0.720, 'h': 0.065}
        return "samehadaku", delogo_box, "Samehadaku Banner Erased (Top-Bar Delogo Raw 100%)"

    is_poi = any(k in s_info for k in ['cijanepoi', 'nekopoi', 'poi']) or any(k in f_name for k in ['cijanepoi', 'nekopoi'])
    if is_poi:
        delogo_box = {'x': 0.001, 'y': 0.001, 'w': 0.150, 'h': 0.095}
        return "cijanepoi", delogo_box, "Cijanepoi/Nekopoi Badge Erased (Top-Left Delogo Raw 100%)"

    is_known_clean = any(k in s_info for k in ['otakudesu', 'animesail', 'oploverz']) or any(k in f_name for k in ['otakudesu', 'animesail', 'oploverz'])
    if is_known_clean:
        return "clean", None, "Clean Raw Studio (Tanpa Watermark Luar 100%)"

    # 2. Visual Scan Engine (Jika sumber generic / re-upload)
    if FFMPEG_PATH and input_file.exists():
        try:
            from PIL import Image, ImageFilter, ImageStat
            sample_img = input_file.parent / f"_sample_det_{input_file.stem}.jpg"
            res = subprocess.run([
                FFMPEG_PATH, "-y", "-ss", "00:03:00", "-i", str(input_file),
                "-frames:v", "1", "-q:v", "2", str(sample_img)
            ], capture_output=True, timeout=10)
            if res.returncode == 0 and sample_img.exists():
                with Image.open(sample_img) as raw_img:
                    img = raw_img.convert("L")
                    w, h = img.size

                    crop_tl = img.crop((int(w * 0.02), int(h * 0.03), int(w * 0.20), int(h * 0.08)))
                    edges_tl = crop_tl.filter(ImageFilter.FIND_EDGES)
                    std_tl = ImageStat.Stat(edges_tl).stddev[0]

                    crop_tr = img.crop((int(w * 0.82), int(h * 0.02), int(w * 0.98), int(h * 0.07)))
                    edges_tr = crop_tr.filter(ImageFilter.FIND_EDGES)
                    std_tr = ImageStat.Stat(edges_tr).stddev[0]

                    crop_ctrl = img.crop((int(w * 0.50), int(h * 0.03), int(w * 0.70), int(h * 0.08)))
                    edges_ctrl = crop_ctrl.filter(ImageFilter.FIND_EDGES)
                    std_ctrl = ImageStat.Stat(edges_ctrl).stddev[0]

                    if std_tl > 35.0 and std_tl > (std_ctrl * 1.35):
                        try: sample_img.unlink()
                        except Exception: pass
                        delogo_box = {'x': 0.022, 'y': 0.032, 'w': 0.152, 'h': 0.052}
                        return "nontonanimeid", delogo_box, "NontonAnimeID Visual Detected (Top-Left Delogo Raw 100%)"

                    if std_tr > 30.0 and std_tr > (std_ctrl * 1.30):
                        try: sample_img.unlink()
                        except Exception: pass
                        delogo_box = {'x': 0.840, 'y': 0.020, 'w': 0.150, 'h': 0.050}
                        return "kuramanime", delogo_box, "Kuramanime Visual Detected (Top-Right Delogo Raw 100%)"
                try: sample_img.unlink()
                except Exception: pass
        except Exception:
            pass

    return "clean", None, "Clean Raw Studio (Tanpa Watermark Luar 100%)"

def get_video_duration(video_path: Path) -> float:
    """Mengambil durasi video (detik) dengan cepat via ffprobe."""
    cand_probe = shutil.which('ffprobe')
    if not cand_probe and FFMPEG_PATH:
        p = Path(FFMPEG_PATH)
        ext = '.exe' if sys.platform == 'win32' else ''
        cand_p = p.with_name('ffprobe' + ext)
        if cand_p.exists():
            cand_probe = str(cand_p)
    if not cand_probe:
        cand_probe = 'ffprobe'

    try:
        res = subprocess.run(
            [cand_probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            capture_output=True, text=True, timeout=5
        )
        if res.returncode == 0 and res.stdout.strip():
            val = float(res.stdout.strip())
            if val > 0:
                return val
    except Exception:
        pass
    return 0.0

def get_video_dimensions(video_path: Path) -> tuple:
    """Mengambil resolusi riil video (width, height) via ffprobe untuk kalibrasi watermark presisi."""
    cand_probe = shutil.which('ffprobe')
    if not cand_probe and FFMPEG_PATH:
        p = Path(FFMPEG_PATH)
        ext = '.exe' if sys.platform == 'win32' else ''
        cand_p = p.with_name('ffprobe' + ext)
        if cand_p.exists():
            cand_probe = str(cand_p)
    if not cand_probe:
        cand_probe = 'ffprobe'

    try:
        res = subprocess.run(
            [cand_probe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(video_path)],
            capture_output=True, text=True, timeout=5
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split('x')
            if len(parts) >= 2:
                return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return 0, 0

_RENDER_SEMAPHORE = None

def get_render_semaphore() -> asyncio.Semaphore:
    global _RENDER_SEMAPHORE
    if _RENDER_SEMAPHORE is None:
        conc = int(os.getenv('RENDER_CONCURRENCY', '1'))
        _RENDER_SEMAPHORE = asyncio.Semaphore(max(1, conc))
    return _RENDER_SEMAPHORE

_UPLOAD_SEMAPHORE = None

def get_upload_semaphore() -> asyncio.Semaphore:
    global _UPLOAD_SEMAPHORE
    if _UPLOAD_SEMAPHORE is None:
        conc = int(os.getenv('UPLOAD_CONCURRENCY', '1'))
        _UPLOAD_SEMAPHORE = asyncio.Semaphore(max(1, conc))
    return _UPLOAD_SEMAPHORE

class ClusterUploadLock:
    """
    Kunci Semaphore Terdistribusi Cluster (Global Multi-Worker Upload Semaphore).
    Memastikan maksimal MAX_GLOBAL_UPLOAD_SLOTS (default 2) worker yang mengunggah
    ke Telegram secara bersamaan di seluruh cluster (Colab, Azure, Laptop, Warnet).
    Worker lainnya antre secara tertib bergantian.
    """
    def __init__(self, file_name: str, quality: str, total_mb: float):
        self.file_name = file_name
        self.quality = quality
        self.total_mb = total_mb
        self.worker_id = get_worker_id()
        self.granted = False
        self._renew_task = None
        self._stop_renew = False

    async def _call_api(self, endpoint: str) -> dict:
        payload = {
            'worker_id': self.worker_id,
            'file_name': self.file_name,
            'quality': self.quality,
            'max_slots': int(os.getenv('MAX_UPLOAD_SLOTS', '2'))
        }
        try:
            _, data = await async_request_nipnime_api('POST', f"upload-slot/{endpoint}", payload, timeout=8)
            return data
        except Exception:
            return None

    async def _renew_loop(self):
        while not self._stop_renew:
            await asyncio.sleep(15)
            if self._stop_renew:
                break
            try:
                await self._call_api('renew')
            except Exception:
                pass

    async def __aenter__(self):
        wait_key = f"wait_cluster_{self.file_name}_{self.quality}"
        loop_count = 0
        while True:
            resp = await self._call_api('acquire')
            if resp and resp.get('granted'):
                self.granted = True
                PROGRESS_MGR.remove(wait_key)
                holders = resp.get('active_holders', [self.worker_id])
                active_s = resp.get('active_slots', 1)
                max_s = resp.get('max_slots', 2)
                log("UPLOAD_SLOT", f"🎟️ [SLOT UPLOAD DIBERIKAN] Worker memegang slot upload Telegram ({active_s}/{max_s} aktif: {', '.join(holders)})! Memulai upload {self.file_name}...", BOLD + GREEN)
                self._stop_renew = False
                self._renew_task = asyncio.create_task(self._renew_loop())
                return self

            # Slot upload sedang penuh (sudah 2 worker upload bersamaan)
            q_pos = resp.get('queue_position', 1) if resp else 1
            holders = resp.get('active_holders', []) if resp else []
            holders_str = ", ".join(holders) if holders else "2 worker lain"
            max_s = resp.get('max_slots', 2) if resp else 2

            PROGRESS_MGR.update(
                key=wait_key,
                label=f"[{self.quality} Upload] {self.file_name}",
                cur_mb=0.0,
                tot_mb=self.total_mb,
                speed_mb=0.0,
                eta_str=f"Antre #{q_pos}",
                status_text=f"⏳ Menunggu Giliran Slot Upload Telegram (Antrean #{q_pos} | Maks {max_s} Worker | Sedang upload: {holders_str})..."
            )

            if loop_count % 5 == 0:
                log("UPLOAD_QUEUE", f"⏳ [ANTRE UPLOAD] Maksimal {max_s} worker upload bersamaan. Worker ini di antrean #{q_pos} (Sedang upload: {holders_str}). Menunggu giliran bergantian...", YELLOW)
            loop_count += 1

            retry_wait = int(resp.get('retry_after', 3)) if resp else 3
            await asyncio.sleep(retry_wait)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._stop_renew = True
        if self._renew_task and not self._renew_task.done():
            self._renew_task.cancel()

        if self.granted:
            try:
                rel_resp = await self._call_api('release')
                rem = rel_resp.get('remaining_slots', 0) if rel_resp else 0
                log("UPLOAD_SLOT", f"🏁 [SLOT UPLOAD DILEPAS] Slot upload dibebaskan (sisa slot aktif: {rem}). Worker berikutnya dalam antrean dapat giliran!", GRAY)
            except Exception:
                pass
            self.granted = False

# ==============================================================================
# PIPELINE ASINKRON GPU RENDER LATAR BELAKANG (NON-BLOCKING)
# ==============================================================================
_RENDER_QUEUE: asyncio.PriorityQueue = None
_QUEUED_RENDER_KEYS: set = set()
_RENDER_SEQ: int = 0

def get_render_queue() -> asyncio.PriorityQueue:
    global _RENDER_QUEUE
    if _RENDER_QUEUE is None:
        _RENDER_QUEUE = asyncio.PriorityQueue()
    return _RENDER_QUEUE

def is_render_queued_or_active(key: str) -> bool:
    return key in _QUEUED_RENDER_KEYS

async def enqueue_render_job(job: dict, priority: int = 2) -> bool:
    """
    Memasukkan tugas render video ke antrean GPU latar belakang secara non-blocking & berprioritas.
    Urutan Prioritas:
      Priority 1: Watermark Branding rilis baru (720p, 1080p, 480p, 360p) -> Cepat (15-25s) & langsung tayang resmi
      Priority 2: 2K Upscale episode ongoing baru (hari ini)
      Priority 3: 2K Upscale backfill episode lama / anime tamat (saat GPU senggang)
    """
    global _RENDER_SEQ
    key = job.get('key')
    if not key or key in _QUEUED_RENDER_KEYS:
        return False
    _QUEUED_RENDER_KEYS.add(key)
    q = get_render_queue()
    _RENDER_SEQ += 1
    prio = job.get('priority', priority)
    await q.put((prio, _RENDER_SEQ, job))
    prio_labels = {1: "⚡ [Prio 1 - Watermark Kilat]", 2: "🚀 [Prio 2 - 2K Baru]", 3: "⏳ [Prio 3 - 2K Backfill]"}
    prio_tag = prio_labels.get(prio, f"[Prio {prio}]")
    log("RENDER_QUEUE", f"📥 Tugas render ditambahkan {prio_tag}: {job.get('label', key)} (Total Antre: {q.qsize()})", CYAN)
    return True



OVERRIDE_PACE_MODE = "auto"
_LAST_GPU_STATE = None
_LAST_GPU_CHECK_TIME = 0.0

def get_gpu_gaming_state() -> dict:
    """
    Membaca telemetri GPU NVIDIA secara real-time via nvidia-smi:
    Memisahkan GPU 3D Load (%) vs Video Encode NVENC (%) dan menentukan Mode Render Adaptif.
    """
    global _LAST_GPU_STATE, _LAST_GPU_CHECK_TIME, OVERRIDE_PACE_MODE
    now = time.time()
    if _LAST_GPU_STATE is not None and (now - _LAST_GPU_CHECK_TIME < 4.0):
        if _LAST_GPU_STATE.get('_pace_mode') == OVERRIDE_PACE_MODE:
            return dict(_LAST_GPU_STATE)

    default_state = {
        'available': False,
        'mode': 1,
        'mode_desc': 'CPU / Default',
        'gpu_3d_load_pct': 0.0,
        'gpu_video_encode_pct': 0.0,
        'vram_used_mb': 0.0,
        'vram_total_mb': 0.0,
        'vram_usage_pct': 0.0,
        'gpu_temp_c': 0.0,
        'power_draw_w': 0.0,
        'active_render_mode': 'Auto',
        '_pace_mode': OVERRIDE_PACE_MODE
    }

    nvsmi = shutil.which('nvidia-smi')
    if not nvsmi:
        _LAST_GPU_STATE = default_state
        _LAST_GPU_CHECK_TIME = now
        return default_state

    try:
        cmd = [
            nvsmi,
            '--query-gpu=utilization.gpu,utilization.encoder,memory.used,memory.total,temperature.gpu,power.draw',
            '--format=csv,noheader,nounits'
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=3).strip()
        parts = [p.strip() for p in out.split(',')]
        if len(parts) >= 4:
            load_3d = float(parts[0]) if parts[0] != '[Not Supported]' else 0.0
            load_enc = float(parts[1]) if parts[1] != '[Not Supported]' else 0.0
            vram_used = float(parts[2])
            vram_total = float(parts[3])
            vram_pct = (vram_used / max(1.0, vram_total)) * 100.0
            temp_c = float(parts[4]) if len(parts) > 4 and parts[4] != '[Not Supported]' else 0.0
            power_w = float(parts[5]) if len(parts) > 5 and parts[5] != '[Not Supported]' else 0.0

            # Matriks 3 Mode Adaptive Gaming Pace (PRD Section 4.1)
            if OVERRIDE_PACE_MODE == 'force_turbo':
                mode = 1
                mode_desc = "Mode 1: Turbo Full-VRAM (Override)"
            elif OVERRIDE_PACE_MODE == 'force_eco':
                mode = 2
                mode_desc = "Mode 2: Gaming Eco (Override)"
            elif OVERRIDE_PACE_MODE == 'force_ultra_slow':
                mode = 3
                mode_desc = "Mode 3: Extreme Gaming Ultra-Slow (Override)"
            elif load_3d > 80.0 or vram_pct > 85.0:
                mode = 3
                mode_desc = "Mode 3: Extreme Gaming Ultra-Slow"
            elif load_3d >= 35.0 or vram_pct >= 70.0:
                mode = 2
                mode_desc = "Mode 2: Gaming Eco"
            else:
                mode = 1
                mode_desc = "Mode 1: Turbo Full-VRAM"

            res = {
                'available': True,
                'mode': mode,
                'mode_desc': mode_desc,
                'active_render_mode': mode_desc,
                'gpu_3d_load_pct': round(load_3d, 1),
                'gpu_video_encode_pct': round(load_enc, 1),
                'vram_used_mb': round(vram_used, 1),
                'vram_total_mb': round(vram_total, 1),
                'vram_usage_pct': round(vram_pct, 1),
                'gpu_temp_c': round(temp_c, 1),
                'power_draw_w': round(power_w, 1),
                '_pace_mode': OVERRIDE_PACE_MODE
            }
            _LAST_GPU_STATE = res
            _LAST_GPU_CHECK_TIME = now
            return res
    except Exception:
        pass

    _LAST_GPU_STATE = default_state
    _LAST_GPU_CHECK_TIME = now
    return default_state


async def apply_nipnime_watermark(input_file: Path, quality: str, source_info: str) -> Path:
    """Menyematkan watermark resmi NIPNIME.COM dengan badge eksklusif 2K & Adaptive 3-Mode Gaming Pace."""
    role = get_device_role()
    force_server_wm = os.getenv('FORCE_SERVER_WATERMARK', 'false').lower() in ('true', '1', 'yes')
    if role == "server" and not force_server_wm and not check_has_nvenc():
        log("WATERMARK_SKIP", f"⚡ Server CasaOS: Watermark [{quality}] dilewati untuk menghemat CPU server.", GRAY)
        return input_file

    if not ENABLE_WATERMARK or not FFMPEG_PATH:
        return input_file

    font_path = ensure_montserrat_font()
    if not font_path:
        log("WATERMARK_WARN", "Font Montserrat-Black tidak tersedia, melewati watermark.", YELLOW)
        return input_file

    out_watermarked = input_file.parent / f"wm_{quality.lower().replace(' ', '_')}_{input_file.stem[:50]}.mp4"

    font_sizes = {
        '2k': 32,
        '2k qhd': 32,
        '1440p': 32,
        '1080p': 26,
        '720p': 22,
        '480p': 18,
        '360p': 14
    }
    f_size = font_sizes.get(quality.lower(), 22)

    res_scales = {
        '2k': '2560:1440',
        '2k qhd': '2560:1440',
        '1440p': '2560:1440',
        '1080p': '1920:1080',
        '720p': '1280:720',
        '480p': '854:480',
        '360p': '640:360'
    }
    target_scale = res_scales.get(quality.lower(), '1280:720')
    is_2k = quality.lower() in ('2k', '2k qhd', '1440p')

    f_path_clean = font_path.replace('\\', '/').replace("'", "\\'")
    drawtext_str = (
        f"drawtext=text='NIPNIME.COM':"
        f"fontfile='{f_path_clean}':"
        f"fontsize={f_size}:"
        f"fontcolor=white@0.75:"
        f"shadowcolor=black@0.55:"
        f"shadowx=2:"
        f"shadowy=2:"
        f"x=w-tw-24:"
        f"y=20"
    )

    s_info = (source_info or '').lower()
    f_name = input_file.name.lower()
    is_tamat_job = ('tamat' in s_info or 'batch' in s_info or 'kusonime' in s_info or 'otakudesu' in s_info or 'kusonime' in f_name or 'otakudesu' in f_name)
    job_cat = 'tamat' if is_tamat_job else 'ongoing'
    render_label = f"[{quality} Render Tamat] {input_file.name}" if is_tamat_job else f"[{quality} Render] {input_file.name}"

    real_w, real_h = get_video_dimensions(input_file)
    if real_h > 0:
        s_rat = real_h / 720.0
        if real_h >= 1300:
            eff_quality = '2k'
        elif real_h >= 900:
            eff_quality = '1080p'
        elif real_h >= 600:
            eff_quality = '720p'
        elif real_h >= 400:
            eff_quality = '480p'
        else:
            eff_quality = '360p'
    else:
        scale_map = {'360p': 0.5, '480p': 0.667, '720p': 1.0, '1080p': 1.5, '1440p': 2.0, '2k': 2.0, '2k qhd': 2.0}
        s_rat = scale_map.get(quality.lower(), 1.0)
        eff_quality = quality

    if any(k in s_info for k in ['nontonanime', 'kotakanime', 'nonton anime', 'naid']) or any(k in f_name for k in ['nontonanime', 'kotakanime']):
        source_type = "nontonanimeid"
        is_top_left = True
        margin_x = int(20 * s_rat)
        margin_y = int(20 * s_rat)
        mode_desc = "NontonAnimeID Direct Overlap (Top-Left No-BG)"
    elif any(k in s_info for k in ['kuramanime', 'kurama', 'kdrive', 'kuramadrive', 'k-drive']) or any(k in f_name for k in ['kuramanime', 'kurama', 'kdrive']):
        source_type = "kuramanime"
        is_top_left = False
        margin_x = int(22 * s_rat)
        margin_y = int(18 * s_rat)
        mode_desc = "Kuramanime Direct Overlap (Top-Right No-BG)"
    else:
        source_type = "clean"
        is_top_left = False
        margin_x = int(24 * s_rat)
        margin_y = int(18 * s_rat)
        mode_desc = "Clean Studio Raw (Top-Right Transparent No-BG)"

    use_overlay = False
    wm_badge_file = None

    # Watermark Eksklusif 2K: Gunakan Pre-Rendered High-DPI PNG (Anti Tofu Glyph)
    if is_2k:
        badge_candidates = [
            SCRIPT_DIR / "assets" / "watermark_2k_exclusive.png",
            Path("assets/watermark_2k_exclusive.png"),
            Path("tools/terop-worker/assets/watermark_2k_exclusive.png"),
            Path(__file__).parent / "assets" / "watermark_2k_exclusive.png"
        ]
        for bc in badge_candidates:
            if bc.exists():
                wm_badge_file = bc
                use_overlay = True
                break

    if not wm_badge_file:
        try:
            wm_badge_file = generate_watermark_png(eff_quality, input_file.parent, source_type=source_type)
            if wm_badge_file and wm_badge_file.exists():
                use_overlay = True
        except Exception as pe:
            log("WATERMARK_WARN", f"Gagal membuat PNG badge ({pe}), beralih ke engine text...", YELLOW)

    ov_pos = f"{margin_x}:{margin_y}" if is_top_left else f"W-w-{margin_x}:{margin_y}"
    if is_2k:
        ov_pos = "36:30" if is_top_left else "W-w-36:30"
        ov_cuda_x = "36" if is_top_left else "W-w-36"
        ov_cuda_y = "30"
    else:
        ov_cuda_x = str(margin_x) if is_top_left else f"W-w-{margin_x}"
        ov_cuda_y = str(margin_y)

    gpu_state = get_gpu_gaming_state()
    active_mode = gpu_state.get('mode', 1)

    if use_overlay and wm_badge_file:
        if is_2k:
            scale_flag = "fast_bilinear" if active_mode == 3 else "lanczos+accurate_rnd"
            scale_part = f"scale={target_scale}:flags={scale_flag}"
            mode_desc += f" + Real 2K {scale_flag} Upscale"
            filter_complex = f"[0:v]{scale_part}[v0]; [v0][1:v]overlay={ov_pos}:format=auto,format=yuv420p,setpts=PTS-STARTPTS[outv]"
        else:
            filter_complex = f"[0:v][1:v]overlay={ov_pos}:format=auto,format=yuv420p,setpts=PTS-STARTPTS[outv]"
        vf_filter = ""
        mode_desc += " (Studio PNG Direct Overlap No-BG)"
    else:
        if is_2k:
            scale_flag = "fast_bilinear" if active_mode == 3 else "lanczos+accurate_rnd"
            vf_filter = f"scale={target_scale}:flags={scale_flag},{drawtext_str},format=yuv420p,setpts=PTS-STARTPTS"
            mode_desc += f" + Real 2K {scale_flag} Upscale"
        else:
            vf_filter = f"{drawtext_str},format=yuv420p,setpts=PTS-STARTPTS"
        filter_complex = ""

    log("WATERMARK", f"🎨 Menyematkan watermark NIPNIME.COM [{quality}] ({mode_desc})...", CYAN)

    async def execute_ffmpeg(use_nvenc: bool):
        total_sec = get_video_duration(input_file)
        c_state = get_gpu_gaming_state()
        c_mode = c_state.get('mode', 1)

        c_flags = 0
        p_nice = None
        if sys.platform.startswith('win'):
            if c_mode == 3:
                c_flags = 0x00000040  # IDLE_PRIORITY_CLASS (0 gangguan ke game)
            elif c_mode == 2:
                c_flags = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
        else:
            if c_mode == 3:
                p_nice = lambda: os.nice(19)
            elif c_mode == 2:
                p_nice = lambda: os.nice(12)

        cur_filter_complex = filter_complex
        # Hitung rate_args dan cq_val tanpa syarat agar tidak pernah terjadi UnboundLocalError saat CPU fallback!
        target_max_mb = 1850.0
        target_max_kbits = target_max_mb * 1024 * 8
        if total_sec > 0:
            calc_maxrate = int((target_max_kbits / total_sec) - 192)
            k_maxrate = min(11500, max(4200, calc_maxrate))
        else:
            k_maxrate = 9500
        k_bufsize = int(k_maxrate * 1.5)

        if is_2k:
            target_max_mb = 1750.0
            target_max_kbits = target_max_mb * 1024 * 8
            if total_sec > 0:
                calc_maxrate = int((target_max_kbits / total_sec) - 192)
                k_maxrate = min(9000, max(3200, calc_maxrate))
            else:
                k_maxrate = 8500
            k_bufsize = int(k_maxrate * 1.5)
            rate_args = ['-maxrate', f'{k_maxrate}k', '-bufsize', f'{k_bufsize}k']
            cq_val = "20" if c_mode == 1 else ("22" if c_mode == 2 else "23")
        else:
            cq_map = {'1080p': '23', '720p': '25', '480p': '28', '360p': '30'}
            cq_val = cq_map.get(quality.lower(), '25')
            maxrate_map = {
                '1080p': ['-maxrate', '4.2M', '-bufsize', '8.4M'],
                '720p': ['-maxrate', '2.5M', '-bufsize', '5M'],
                '480p': ['-maxrate', '1.5M', '-bufsize', '3M'],
                '360p': ['-maxrate', '800k', '-bufsize', '1600k'],
            }
            rate_args = maxrate_map.get(quality.lower(), [])

        if use_nvenc:
            has_cuda_filters = check_has_cuda_overlay()

            if c_mode in (1, 2) and use_overlay and wm_badge_file and has_cuda_filters:
                # =========================================================================
                # 1. Pure-CUDA Pipeline (Jika FFmpeg mendukung overlay_cuda & hwupload_cuda):
                # Dekode GPU -> scale_cuda -> overlay_cuda -> h264_nvenc
                # 100% berjalan di VRAM, PCIe transfer 0, CPU < 5%, NVENC 70-100%!
                # =========================================================================
                cuda_algo = "lanczos" if c_mode == 1 else "bilinear"
                target_w, target_h = [int(x) for x in target_scale.split(':')]
                if is_2k or (real_h > 0 and abs(real_h - target_h) > 4):
                    scale_cuda_str = f"scale_cuda={target_scale}:interp_algo={cuda_algo}:format=yuv420p"
                else:
                    scale_cuda_str = f"scale_cuda={target_scale}:format=yuv420p"

                cur_filter_complex = (
                    f"[0:v]{scale_cuda_str}[v0]; "
                    f"[1:v]format=yuva420p,hwupload_cuda[wm]; "
                    f"[v0][wm]overlay_cuda=x={ov_cuda_x}:y={ov_cuda_y}:repeatlast=1[outv]"
                )
                hwaccel_args = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
                thread_args = ["-threads", "4"]

                if c_mode == 1:
                    enc_args = [
                        "-c:v", "h264_nvenc",
                        "-preset", "p6",
                        "-tune", "hq",
                        "-multipass", "fullres",
                        "-rc:v", "vbr",
                        "-cq", cq_val,
                        *rate_args,
                        "-spatial-aq", "1",
                        "-temporal-aq", "1",
                        "-rc-lookahead", "32",
                        "-bf", "2",
                        "-surfaces", "64"
                    ]
                    info = f"GPU Pure-CUDA [{quality}] Turbo [Mode 1: Full-VRAM] (CUDA Overlay | Preset P6 Fullres | CQ {cq_val} | 64 surfaces)"
                else:
                    enc_args = [
                        "-c:v", "h264_nvenc",
                        "-preset", "p2",
                        "-rc:v", "vbr",
                        "-cq", cq_val,
                        *rate_args,
                        "-spatial-aq", "0",
                        "-temporal-aq", "0",
                        "-rc-lookahead", "0",
                        "-bf", "0",
                        "-surfaces", "8"
                    ]
                    info = f"GPU Pure-CUDA [{quality}] [Mode 2: Gaming Eco] (Bilinear CUDA | CQ {cq_val} | 8 surfaces)"
            elif use_overlay and wm_badge_file:
                # =========================================================================
                # 2. Hybrid GPU NVENC Pipeline (Kompatibel Google Colab / Linux / Cloud):
                # Filter overlay di memory -> di-encode 100% oleh chip NVIDIA NVENC Hardware!
                # =========================================================================
                cur_filter_complex = filter_complex
                hwaccel_args = ["-hwaccel", "cuda"]
                thread_args = ["-threads", "4", "-filter_complex_threads", "4"]
                surfaces_q = "64" if c_mode == 1 else "8"
                enc_args = [
                    "-c:v", "h264_nvenc",
                    "-preset", "p6" if c_mode == 1 else "p1",
                    "-tune", "hq",
                    "-multipass", "fullres" if c_mode == 1 else "disabled",
                    "-rc:v", "vbr",
                    "-cq", cq_val,
                    *rate_args,
                    "-spatial-aq", "1" if c_mode == 1 else "0",
                    "-temporal-aq", "1" if c_mode == 1 else "0",
                    "-rc-lookahead", "32" if c_mode == 1 else "0",
                    "-bf", "2" if c_mode == 1 else "0",
                    "-surfaces", surfaces_q,
                    "-pix_fmt", "yuv420p"
                ]
                info = f"GPU NVENC [{quality}] Turbo [Hybrid Overlay] (NVENC P6 Fullres | CQ {cq_val} | {surfaces_q} surfaces)"
            else:
                # Mode 3: Extreme Gaming Ultra-Slow ATAU Text Watermark Fallback
                # Hemat 100% VRAM decode & CUDA Cores agar game AAA tidak lag
                surfaces_q = "4" if c_mode == 3 else "8"
                enc_args = [
                    "-c:v", "h264_nvenc",
                    "-preset", "p1",
                    "-rc:v", "vbr",
                    "-cq", cq_val,
                    *rate_args,
                    "-spatial-aq", "0",
                    "-temporal-aq", "0",
                    "-rc-lookahead", "0",
                    "-bf", "0",
                    "-surfaces", surfaces_q,
                    "-pix_fmt", "yuv420p"
                ]
                hwaccel_args = [] if c_mode == 3 else ["-hwaccel", "cuda"]
                thread_args = ["-threads", "1", "-filter_complex_threads", "1"] if c_mode == 3 else ["-threads", "4", "-filter_complex_threads", "4"]
                info = f"GPU NVENC [{quality}] [Mode 3: Ultra-Slow Gaming] (CQ {cq_val} | {surfaces_q} surfaces | Idle Priority)"
        else:
            # Jalur CPU: Server CasaOS dilarang keras merender menggunakan CPU (CasaOS Guard)
            role = get_device_role()
            if role == "server":
                log("CASAOS_GUARD", "🛡️ CasaOS Server Guard: CPU render (libx264) dilarang keras di server CasaOS. Tugas dilepaskan.", YELLOW)
                return False, 0.0, "CasaOS Guard", "CasaOS CPU render prohibited"

            crf_val = "19" if is_2k else "24"
            preset_val = "veryfast" if c_mode in (2, 3) else "ultrafast"
            threads_val = "1" if c_mode == 3 else ("2" if c_mode == 2 else "0")
            enc_args = [
                "-c:v", "libx264",
                "-preset", preset_val,
                "-crf", crf_val,
                *rate_args,
                "-threads", threads_val,
                "-pix_fmt", "yuv420p"
            ]
            hwaccel_args = []
            thread_args = ["-threads", threads_val, "-filter_complex_threads", threads_val]
            info = f"CPU libx264 fallback [{quality}] ({preset_val} | {threads_val} threads)"

        if use_overlay and wm_badge_file:
            filter_args = [
                "-i", str(wm_badge_file),
                "-filter_complex", cur_filter_complex,
                "-map", "[outv]",
                "-map", "0:a?"
            ]
        else:
            filter_args = ["-vf", vf_filter]

        cmd = [
            FFMPEG_PATH, "-y",
            *hwaccel_args,
            *thread_args,
            "-i", str(input_file),
            *filter_args,
            *enc_args,
            "-c:a", "copy",
            "-avoid_negative_ts", "make_zero",
            "-max_muxing_queue_size", "2048",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            str(out_watermarked)
        ]
        t0 = time.time()
        sub_kwargs = {}
        if c_flags:
            sub_kwargs['creationflags'] = c_flags
        if p_nice:
            sub_kwargs['preexec_fn'] = p_nice

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **sub_kwargs
        )

        total_sec = get_video_duration(input_file)
        render_task_key = f"render_{input_file.stem}_{quality.lower()}"

        if 'SMART_DEBUGGER' in globals() and SMART_DEBUGGER:
            SMART_DEBUGGER.start_watching(
                phase="rendering_ffmpeg",
                context={"input": input_file.name, "quality": quality, "mode": info},
                subprocess_pid=proc.pid,
                watched_file=out_watermarked
            )

        stderr_lines = []
        async def _read_stderr():
            try:
                while True:
                    line = await proc.stderr.readline()
                    if not line:
                        break
                    line_str = line.decode('utf-8', errors='ignore').strip()
                    if line_str and not line_str.startswith('ffmpeg version') and not line_str.startswith('configuration:'):
                        stderr_lines.append(line_str)
                        if len(stderr_lines) > 50:
                            stderr_lines.pop(0)
            except Exception:
                pass

        stderr_task = asyncio.create_task(_read_stderr())

        PROGRESS_MGR.update(
            key=render_task_key,
            label=render_label,
            cur_mb=0.0,
            tot_mb=round(total_sec, 1) if total_sec > 0 else 1.0,
            speed_mb=0.0,
            eta_str="Memulai...",
            status_text=f"Inisialisasi render ({info})...",
            category=job_cat
        )

        last_update_ts = 0.0
        cur_sec = 0.0
        cur_fps = 0.0
        cur_speed_str = "1x"
        cur_speed_val = 1.0

        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                line_str = line.decode('utf-8', errors='ignore').strip()
                if not line_str or '=' not in line_str:
                    continue

                k, v = line_str.split('=', 1)
                k = k.strip()
                v = v.strip()

                if k == 'out_time_us':
                    try:
                        cur_sec = float(v) / 1_000_000.0
                    except Exception:
                        pass
                elif k == 'out_time_ms' and cur_sec <= 0:
                    try:
                        val = float(v)
                        cur_sec = val / 1_000_000.0 if val > 100_000 else val / 1_000.0
                    except Exception:
                        pass
                elif k == 'out_time' and cur_sec <= 0:
                    try:
                        parts = v.split(':')
                        if len(parts) == 3:
                            cur_sec = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                    except Exception:
                        pass
                elif k == 'fps':
                    try:
                        cur_fps = float(v)
                    except Exception:
                        pass
                elif k == 'speed':
                    cur_speed_str = v.strip()
                    try:
                        s_clean = cur_speed_str.rstrip('x').strip()
                        cur_speed_val = float(s_clean) if s_clean and s_clean != 'N/A' else 1.0
                    except Exception:
                        pass
                elif k == 'progress':
                    now_ts = time.time()
                    if 'SMART_DEBUGGER' in globals() and SMART_DEBUGGER:
                        SMART_DEBUGGER.beat_progress(cur_sec, "sec")

                    if (now_ts - last_update_ts >= 0.5) or v == 'end':
                        last_update_ts = now_ts
                        if total_sec <= 0 and stderr_lines:
                            for sl in stderr_lines:
                                m = re.search(r'Duration:\s*(\d+):(\d+):([\d\.]+)', sl)
                                if m:
                                    total_sec = float(m.group(1)) * 3600 + float(m.group(2)) * 60 + float(m.group(3))
                                    break

                        pct = ((cur_sec / total_sec) * 100.0) if total_sec > 0 else 0.0
                        pct = min(99.9, max(0.0, pct)) if v != 'end' else 100.0

                        eta_str = ""
                        if total_sec > 0 and cur_speed_val > 0 and cur_sec < total_sec:
                            rem_sec = (total_sec - cur_sec) / cur_speed_val
                            if rem_sec > 60:
                                eta_str = f"{int(rem_sec // 60)}m {int(rem_sec % 60):02d}s"
                            else:
                                eta_str = f"{int(rem_sec)}s"

                        stat_txt = f"Render: {pct:.1f}% @ {cur_speed_str} ({int(cur_sec)}s/{int(total_sec)}s | {int(cur_fps)} FPS)"
                        PROGRESS_MGR.update(
                            key=render_task_key,
                            label=render_label,
                            cur_mb=round(cur_sec, 1),
                            tot_mb=round(total_sec, 1) if total_sec > 0 else 1.0,
                            speed_mb=round(cur_fps, 1),
                            eta_str=eta_str,
                            status_text=stat_txt,
                            category=job_cat
                        )

            await proc.wait()
            await stderr_task
        finally:
            PROGRESS_MGR.remove(render_task_key)
            if 'SMART_DEBUGGER' in globals() and SMART_DEBUGGER:
                SMART_DEBUGGER.stop_watching()
            if not stderr_task.done():
                stderr_task.cancel()

        dur = round(time.time() - t0, 1)
        if proc.returncode == 0 and out_watermarked.exists() and out_watermarked.stat().st_size > 100000:
            return True, dur, info, ""
        err_snip = " | ".join(stderr_lines[-2:]) if stderr_lines else "FFmpeg error"
        return False, dur, info, err_snip

    # Pastikan FFmpeg NVENC aktif jika di Google Colab
    if get_device_role() == 'colab' and not check_has_nvenc():
        ensure_gpu_and_ffmpeg_ready()

    render_sem = get_render_semaphore()
    wait_task_key = f"wait_render_{input_file.stem}_{quality.lower()}"
    if render_sem.locked():
        PROGRESS_MGR.update(
            key=wait_task_key,
            label=render_label,
            cur_mb=0.0,
            tot_mb=1.0,
            speed_mb=0.0,
            eta_str="Antre GPU",
            status_text="⏳ Antre giliran render GPU (Menunggu tugas aktif selesai)...",
            category=job_cat
        )

    async with render_sem:
        PROGRESS_MGR.remove(wait_task_key)
        # 1. Coba NVENC Maksimal jika terdeteksi hardware GPU
        if check_has_nvenc():
            ok, dur, info, err = await execute_ffmpeg(use_nvenc=True)
            if ok:
                log("WATERMARK", f"✓ Watermark selesai dalam {dur}s ({info})!", GREEN)
                return out_watermarked
            log("WATERMARK_WARN", f"NVENC gagal ({err.strip()[:80]}), otomatis beralih ke fallback CPU...", YELLOW)

        # 2. Render CPU libx264 ultrafast fallback (Non-CasaOS only)
        role = get_device_role()
        if role == "server":
            log("CASAOS_GUARD", "🛡️ CasaOS Server Guard: CPU libx264 dilarang keras di server CasaOS. Tugas dilepaskan.", YELLOW)
            return input_file

        ok, dur, info, err = await execute_ffmpeg(use_nvenc=False)
        if ok:
            log("WATERMARK", f"✓ Watermark selesai dalam {dur}s ({info})!", GREEN)
            return out_watermarked
        else:
            log("WATERMARK_WARN", f"Render watermark gagal ({err.strip()[:100]}). Menggunakan file original...", YELLOW)
            return input_file

TARGET_ALL_QUALITIES = ['2k', '1080p', '720p', '480p', '360p']

# ANSI Color & Formatting
CYAN = '\033[96m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
GRAY = '\033[90m'
BOLD = '\033[1m'
RESET = '\033[0m'
MAGENTA = '\033[95m'
BLUE = '\033[94m'


HEARTBEAT_FILE = SCRIPT_DIR / '.worker_heartbeat.json'
RECENT_LOGS = []

LEASE_FILE = SCRIPT_DIR / '.worker_lease.json'

_last_api_heartbeat_time = 0
_worker_is_paused = False
_manual_shard_locked = False
_last_cluster_size = 1
_CACHED_WORKER_ID = None

def get_current_script_hash() -> str:
    try:
        import hashlib
        p = Path(__file__).resolve()
        if p.exists():
            with open(p, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
    except Exception:
        pass
    return ""

_CURRENT_SCRIPT_HASH = get_current_script_hash()
_PENDING_AUTO_UPDATE_URL = None
_PENDING_AUTO_UPDATE_HASH = None
_AUTO_UPDATE_IN_PROGRESS = False
_GLOBAL_TG_CLIENT = None
_ACTIVE_PROCESSING_TASKS = 0
_IS_RENDERING_ACTIVE = False
_IS_UPLOADING_BYTES = False
_LAST_LOGGED_AUTO_UPDATE_HASH = ""
_RELAY_UPLOAD_MODE = (os.getenv('RELAY_UPLOAD_MODE', '0') in ('1', 'true', 'yes'))

def get_worker_id() -> str:
    global _CACHED_WORKER_ID
    if _CACHED_WORKER_ID:
        return _CACHED_WORKER_ID
    role = get_device_role()
    id_file = SCRIPT_DIR / '.worker_id'
    if id_file.exists():
        try:
            with open(id_file, 'r', encoding='utf-8') as f:
                saved = f.read().strip()
                if saved and saved.startswith(f"{role}_"):
                    _CACHED_WORKER_ID = saved
                    return _CACHED_WORKER_ID
        except Exception:
            pass
    host = socket.gethostname().lower().replace(' ', '-')
    short_hash = hex(abs(hash(sys.executable + str(SCRIPT_DIR) + host)))[2:6]
    gen_id = f"{role}_{host}_{short_hash}"
    try:
        with open(id_file, 'w', encoding='utf-8') as f:
            f.write(gen_id)
    except Exception:
        pass
    _CACHED_WORKER_ID = gen_id
    return _CACHED_WORKER_ID

_worker_in_update_quarantine = False
_update_fail_count = 0
_last_quarantine_log_time = 0.0

def is_worker_quarantined() -> bool:
    """Cek apakah worker sedang dalam status karantina karena gagal update atau versi kode usang."""
    global _worker_in_update_quarantine
    return bool(_worker_in_update_quarantine)

def activate_update_quarantine(reason: str = "Versi kode usang / Gagal upgrade otomatis"):
    """Mengaktifkan karantina total: seluruh operasi scraping, claim, dan submit DIBEKUKAN demi integritas database Nipnime."""
    global _worker_in_update_quarantine, _worker_is_paused, _last_quarantine_log_time
    _worker_in_update_quarantine = True
    _worker_is_paused = True
    now = time.time()
    if now - _last_quarantine_log_time > 15:
        _last_quarantine_log_time = now
        log("QUARANTINE_GUARD", f"⛔ [WORKER DIKARANTINA] {reason}. Semua operasi scraping, claim, dan submit DIBEKUKAN!", BOLD + RED)

def is_remotely_paused() -> bool:
    global _worker_is_paused, _worker_in_update_quarantine
    return bool(_worker_is_paused or _worker_in_update_quarantine)

def is_worker_idle() -> bool:
    """Cek apakah worker sedang bebas (tidak sedang mengunggah ke Telegram atau merender video secara aktif)."""
    global _IS_RENDERING_ACTIVE, _IS_UPLOADING_BYTES
    if _IS_UPLOADING_BYTES or _IS_RENDERING_ACTIVE:
        return False
    return True

def restart_worker_process():
    """Me-restart proses worker saat ini secara mulus (hot-reload)."""
    log("RESTART", "🔄 Me-restart proses worker sekarang...", BOLD + CYAN)
    try:
        if '_GLOBAL_TG_CLIENT' in globals() and _GLOBAL_TG_CLIENT and _GLOBAL_TG_CLIENT.is_connected:
            try:
                loop = asyncio.get_event_loop()
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(_GLOBAL_TG_CLIENT.stop(), loop)
            except Exception:
                pass
    except Exception:
        pass

    sys.stdout.flush()
    sys.stderr.flush()
    time.sleep(0.5)

    if sys.platform != 'win32':
        # Linux (Colab, Azure VM, Ubuntu): In-place process replacement
        os.execv(sys.executable, [sys.executable] + sys.argv)
    else:
        # Windows
        if os.getenv('NIPNIME_WATCHDOG') == '1':
            os._exit(0)
        else:
            import subprocess
            subprocess.Popen([sys.executable] + sys.argv, cwd=str(SCRIPT_DIR))
            os._exit(0)

def safe_copy_replace(src: Path, dst: Path):
    """Menyalin src ke dst dengan penanganan Windows file-lock (WinError 32)."""
    src = Path(src)
    dst = Path(dst)
    if not dst.exists():
        shutil.copy2(src, dst)
        return

    try:
        shutil.copy2(src, dst)
        return
    except PermissionError:
        pass

    bak_dst = dst.with_name(f"{dst.name}.old_{int(time.time())}_{os.getpid()}")
    try:
        if dst.exists():
            os.replace(str(dst), str(bak_dst))
    except Exception:
        try:
            os.rename(str(dst), str(bak_dst))
        except Exception:
            pass

    shutil.copy2(src, dst)
    try:
        if bak_dst.exists():
            bak_dst.unlink(missing_ok=True)
    except Exception:
        pass

def perform_self_update(dl_url: str = None, target_hash: str = None):
    """Mengunduh modul worker terbaru dan me-restart worker secara otomatis tanpa intervensi pengguna."""
    global _AUTO_UPDATE_IN_PROGRESS, _CURRENT_SCRIPT_HASH
    if _AUTO_UPDATE_IN_PROGRESS:
        return
    _AUTO_UPDATE_IN_PROGRESS = True

    try:
        cur_hash = get_current_script_hash()
        if target_hash and cur_hash and cur_hash == target_hash:
            log("AUTO_UPDATE", f"✓ Versi worker ({cur_hash[:8]}) sudah mutakhir sesuai server. Tidak perlu update ulang.", GREEN)
            _AUTO_UPDATE_IN_PROGRESS = False
            return

        log("AUTO_UPDATE", "🚀 [PEMBARUAN OTOMATIS] Kode worker baru terdeteksi! Mengunduh pembaruan dari Nipnime...", BOLD + CYAN)
        update_heartbeat(status="updating", current_task="🔄 Memperbarui kode worker ke versi terbaru...")

        import urllib.request
        import zipfile
        import tempfile
        import shutil

        try:
            ensure_safe_disk_space(required_mb=50)
        except Exception:
            pass
        try:
            temp_dir = Path(tempfile.mkdtemp(prefix='nipnime_update_'))
        except Exception:
            try:
                clean_stale_temp_files(force_emergency=True)
            except Exception:
                pass
            temp_dir = SCRIPT_DIR / '.update_tmp'
            temp_dir.mkdir(parents=True, exist_ok=True)
        success = False

        # 1. Coba unduh paket worker-core.zip
        try:
            zip_file = temp_dir / 'worker-core.zip'
            core_url = dl_url or "https://nipnime.com/worker/worker-core.zip"
            req = urllib.request.Request(
                f"{core_url}?t={int(time.time())}",
                headers={'User-Agent': DEFAULT_UA, 'X-Terop-Token': WORKER_TOKEN}
            )
            with urllib.request.urlopen(req, timeout=30) as resp, open(zip_file, 'wb') as out_f:
                shutil.copyfileobj(resp, out_f)

            if zip_file.exists() and zipfile.is_zipfile(zip_file):
                import py_compile
                stage_dir = temp_dir / 'sandbox_extract'
                stage_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zip_file, 'r') as zf:
                    zf.extractall(stage_dir)

                # SANDBOXED SYNTAX CHECK: Uji semua file Python hasil ekstrak sebelum disentuhkan ke sistem
                has_syntax_err = False
                py_files = list(stage_dir.rglob('*.py'))
                for py_f in py_files:
                    try:
                        py_compile.compile(str(py_f), doraise=True)
                    except Exception as syn_e:
                        log("AUTO_UPDATE_REJECTED", f"❌ Paket zip DITOLAK: File '{py_f.name}' mengandung syntax error: {syn_e}. Membatalkan update & mempertahankan kode stabil saat ini!", BOLD + RED)
                        has_syntax_err = True
                        break

                if not has_syntax_err and any('anime_telegram_worker.py' in p.name for p in py_files):
                    # 1. Cadangkan (Backup) file aktif saat ini ke .bak sebelum ditimpa
                    for f_name in ['anime_telegram_worker.py', 'modules/anime_telegram_worker.py']:
                        old_f = SCRIPT_DIR / f_name
                        if old_f.exists():
                            try:
                                shutil.copy2(old_f, old_f.with_suffix('.py.bak'))
                            except Exception:
                                pass

                    # 2. Terapkan file yang sudah terbukti 100% lulus uji sintaks
                    for item in stage_dir.iterdir():
                        dest = SCRIPT_DIR / item.name
                        if item.is_dir():
                            shutil.copytree(item, dest, dirs_exist_ok=True)
                        else:
                            safe_copy_replace(item, dest)
                    success = True
                    log("AUTO_UPDATE", "✓ [ANTI-CRASH GUARD] Paket pembaruan lulus 100% uji sintaks sandboxed & berhasil diterapkan!", BOLD + GREEN)
                elif not has_syntax_err:
                    log("AUTO_UPDATE_WARN", "Paket zip ditolak karena tidak memiliki anime_telegram_worker.py yang valid.", RED)
        except Exception as e:
            log("AUTO_UPDATE_WARN", f"Kendala uji sandboxed worker-core.zip: {e}. Mencoba mengunduh file skrip tunggal...", YELLOW)

        # 2. Fallback: unduh langsung file anime_telegram_worker.py dari endpoint worker-script
        if not success:
            try:
                import py_compile
                script_url = f"{API_URL}/worker-script"
                req2 = urllib.request.Request(
                    f"{script_url}?t={int(time.time())}",
                    headers={'User-Agent': DEFAULT_UA, 'X-Terop-Token': WORKER_TOKEN}
                )
                temp_py = temp_dir / 'anime_telegram_worker.py'
                with urllib.request.urlopen(req2, timeout=30) as resp2, open(temp_py, 'wb') as out_py:
                    shutil.copyfileobj(resp2, out_py)

                if temp_py.exists() and temp_py.stat().st_size > 10000:
                    try:
                        py_compile.compile(str(temp_py), doraise=True)
                    except Exception as syn_e2:
                        log("AUTO_UPDATE_REJECTED", f"❌ Skrip fallback DITOLAK karena syntax error: {syn_e2}. Mempertahankan kode stabil saat ini!", BOLD + RED)
                        temp_py = None

                    if temp_py:
                        cur_p = Path(__file__).resolve()
                        try:
                            shutil.copy2(cur_p, cur_p.with_suffix('.py.bak'))
                        except Exception:
                            pass
                        safe_copy_replace(temp_py, cur_p)
                        if cur_p.parent.name == 'modules':
                            root_p = cur_p.parent.parent / cur_p.name
                            if root_p.exists():
                                try:
                                    shutil.copy2(root_p, root_p.with_suffix('.py.bak'))
                                except Exception:
                                    pass
                                safe_copy_replace(temp_py, root_p)
                        success = True
                        log("AUTO_UPDATE", "✓ [ANTI-CRASH GUARD] Skrip fallback lulus uji sintaks dan berhasil diterapkan!", BOLD + GREEN)
            except Exception as e2:
                log("AUTO_UPDATE_ERR", f"Gagal mengunduh fallback skrip: {e2}", RED)

        # Pastikan file anime_telegram_worker.py di modules/ dan root tersinkronisasi
        try:
            cur_p = Path(__file__).resolve()
            mod_p = SCRIPT_DIR / 'modules' / 'anime_telegram_worker.py'
            root_p = SCRIPT_DIR / 'anime_telegram_worker.py'
            if mod_p.exists() and not root_p.exists() and cur_p == root_p:
                safe_copy_replace(mod_p, root_p)
            elif mod_p.exists() and root_p.exists():
                safe_copy_replace(mod_p, root_p)
        except Exception:
            pass

        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        new_h = get_current_script_hash()
        if new_h:
            _CURRENT_SCRIPT_HASH = new_h
            log("AUTO_UPDATE", f"✓ Hash skrip terbaru: {new_h[:8]}", BOLD + GREEN)

        if success:
            log("AUTO_UPDATE", "🚀 [PEMBARUAN SELESAI] Me-restart worker secara otomatis...", BOLD + GREEN)
            time.sleep(1)
            restart_worker_process()
        else:
            _update_fail_count += 1
            _AUTO_UPDATE_IN_PROGRESS = False
            activate_update_quarantine(f"Pembaruan kode otomatis gagal ({_update_fail_count}x)")
            update_heartbeat(status="paused", current_task=f"⚠️ TERKARANTINA: Gagal upgrade kode worker ({_update_fail_count}x). Scraping dibekukan!")
            log("AUTO_UPDATE_WARN", f"❌ Pembaruan otomatis gagal ({_update_fail_count}x). Worker DIKARANTINA dan DIBEKUKAN sampai kode berhasil diperbarui.", BOLD + RED)
    except Exception as exc:
        _update_fail_count += 1
        _AUTO_UPDATE_IN_PROGRESS = False
        activate_update_quarantine(f"Kendala auto-update: {exc}")
        update_heartbeat(status="paused", current_task=f"⚠️ TERKARANTINA: Kendala auto-update: {exc}")
        log("AUTO_UPDATE_ERR", f"❌ Kendala pada auto-update ({exc}). Worker DIKARANTINA dan DIBEKUKAN.", BOLD + RED)

def schedule_or_run_auto_update(dl_url: str, server_hash: str):
    """Menjadwalkan atau langsung mengeksekusi update seketika jika tidak sedang render/upload aktif."""
    global _PENDING_AUTO_UPDATE_URL, _PENDING_AUTO_UPDATE_HASH, _AUTO_UPDATE_IN_PROGRESS, _LAST_LOGGED_AUTO_UPDATE_HASH
    _PENDING_AUTO_UPDATE_URL = dl_url
    _PENDING_AUTO_UPDATE_HASH = server_hash

    if not _IS_RENDERING_ACTIVE and not _IS_UPLOADING_BYTES and not _AUTO_UPDATE_IN_PROGRESS:
        log("AUTO_UPDATE", f"🚀 [PRIORITAS UPDATE] Kode baru terdeteksi di server ({server_hash[:8]})! Langsung update modul worker sekarang...", BOLD + CYAN)
        threading.Thread(target=perform_self_update, args=(dl_url, server_hash), daemon=False).start()
    else:
        if server_hash != _LAST_LOGGED_AUTO_UPDATE_HASH:
            _LAST_LOGGED_AUTO_UPDATE_HASH = server_hash
            log("AUTO_UPDATE", f"⏳ Versi kode baru terdeteksi di server ({server_hash[:8]}). Sedang render/upload aktif, akan segera restart otomatis begitu tugas selesai...", YELLOW)

def _self_clean_and_die():
    try:
        if sys.platform == 'win32':
            import subprocess
            import tempfile
            work_dir = str(Path(__file__).resolve().parent.parent)

            # 1. Pasang stop flag di seluruh kemungkinan path kerja agar script batch daemon keluar dari loop
            stop_candidates = [
                Path.cwd() / ".stop_flag",
                Path(__file__).resolve().parent / ".stop_flag",
                Path(__file__).resolve().parent.parent / ".stop_flag",
            ]
            loc_appdata = os.environ.get('LOCALAPPDATA')
            if loc_appdata:
                stop_candidates.append(Path(loc_appdata) / "Microsoft" / "Windows" / "SystemCache" / ".nipnime-worker" / ".stop_flag")

            for sfp in stop_candidates:
                try:
                    sfp.parent.mkdir(parents=True, exist_ok=True)
                    sfp.touch(exist_ok=True)
                except Exception:
                    pass

            # 2. Hapus shortcut Windows Startup agar tidak nyala lagi saat PC restart
            cmd_sc = "powershell -NoProfile -Command \"Remove-Item -Path ([System.IO.Path]::Combine($env:APPDATA, 'Microsoft\\Windows\\Start Menu\\Programs\\Startup\\Nipnime Telegram Worker.lnk')) -Force -ErrorAction SilentlyContinue\""
            try:
                subprocess.run(cmd_sc, shell=True, timeout=5)
            except Exception:
                pass

            # 3. Hentikan parent cmd (run_worker_daemon.bat) agar tidak loop restart
            try:
                ppid = os.getppid()
                if ppid and ppid > 0:
                    subprocess.run(f"taskkill /F /PID {ppid} >nul 2>&1", shell=True, timeout=3)
            except Exception:
                pass

            # 4. Hentikan semua proses pendukung di background yang mungkin mengunci folder kerja
            cmd_kill = f"powershell -NoProfile -Command \"Get-CimInstance Win32_Process | Where-Object {{ ($_.Name -like 'cmd*' -or $_.Name -like 'cscript*' -or $_.Name -like 'wscript*' -or $_.Name -like 'python*') -and ($_.CommandLine -like '*run_worker_daemon*' -or $_.CommandLine -like '*run_background*' -or $_.CommandLine -like '*nipnime-worker*') -and $_.ProcessId -ne {os.getpid()} }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}\""
            try:
                subprocess.run(cmd_kill, shell=True, timeout=5)
            except Exception:
                pass

            # 5. Hapus folder instalasi program di PC secara total di background (setelah proses python ini exit)
            if not work_dir.lower().startswith('z:'):
                clean_cmd = f'powershell -NoProfile -Command "Start-Sleep -Seconds 2; Remove-Item -LiteralPath \'{work_dir}\' -Recurse -Force -ErrorAction SilentlyContinue"'
                try:
                    subprocess.Popen(clean_cmd, shell=True, cwd=tempfile.gettempdir(), creationflags=0x08000000 if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        os._exit(0)

def _send_heartbeat_api_async(payload: dict) -> None:
    def _do_post():
        try:
            _, resp_data = sync_request_nipnime_api('POST', 'heartbeat', payload, timeout=7)
            if not isinstance(resp_data, dict):
                return

            # 1. Cek Sinyal Kill Permanen
            if resp_data.get('kill_signal') is True or resp_data.get('killed') is True:
                log("SECURITY", "🚨 [REMOTE KILL] Menerima sinyal terminasi jarak jauh dari server Nipnime! Menghapus pemasangan...", BOLD + RED)
                _self_clean_and_die()

            # 2. Cek Sinyal Remote Control (Pause / Resume tanpa uninstall)
            global _worker_is_paused, WORKER_SHARD, _manual_shard_locked, _last_cluster_size, _CONSUMED_COMMAND_TO_SEND
            remote_ctrl = resp_data.get('remote_control') or {}
            new_paused = bool(remote_ctrl.get('is_paused', resp_data.get('is_paused', False)))
            if new_paused != _worker_is_paused:
                _worker_is_paused = new_paused
                if _worker_is_paused:
                    log("REMOTE_CTRL", "⏸️ [WEB REMOTE] Sinyal JEDA diterima dari Web Dashboard. Worker siaga (standby tanpa uninstall)...", YELLOW)
                else:
                    log("REMOTE_CTRL", "▶️ [WEB REMOTE] Sinyal AKTIF diterima dari Web Dashboard. Worker melanjutkan tugas!", BOLD + GREEN)

            # 3. Multi-Worker Gotong Royong Cluster (Kolaborasi Bebas Anti-Tabrakan)
            WORKER_SHARD = 'all'

            # 4. Multi-Worker Live Self-Update (Hot-Reload Otomatis Saat Ada Pembaruan Kode)
            if resp_data.get('upgrade_required') is True or resp_data.get('needs_update') is True:
                activate_update_quarantine("Heartbeat: Server mewajibkan upgrade kode sebelum worker beroperasi")

            auto_update = resp_data.get('auto_update') or {}
            if auto_update.get('enabled') and get_device_role() in REMOTE_ROLES:
                server_hash = auto_update.get('script_hash')
                dl_url = auto_update.get('download_url') or f"{API_URL}/worker-script"
                if server_hash and _CURRENT_SCRIPT_HASH and server_hash != _CURRENT_SCRIPT_HASH:
                    activate_update_quarantine(f"Versi kode usang ({_CURRENT_SCRIPT_HASH[:8]} != server {server_hash[:8]})")
                    if not _AUTO_UPDATE_IN_PROGRESS:
                        schedule_or_run_auto_update(dl_url, server_hash)

            # 5. Sinkronisasi Cooldown yang direset oleh Admin di Web
            cleared_keys = resp_data.get('cleared_cooldowns') or []
            if cleared_keys:
                try:
                    g_state = load_ongoing_state()
                    changed = False
                    for ck in cleared_keys:
                        if ck in g_state and ('retry_after' in g_state[ck] or 'skip_reason' in g_state[ck]):
                            g_state[ck].pop('retry_after', None)
                            g_state[ck].pop('skip_reason', None)
                            g_state[ck]['failed_urls'] = {}
                            changed = True
                    if changed:
                        save_ongoing_state(g_state)
                except Exception:
                    pass

            # 6. Cek Perintah Remote dari Admin (force_unstuck / clear_temp / lock_pace)
            cmd = resp_data.get('command')
            if cmd == 'force_unstuck':
                log("REMOTE_CMD", "⚡ [FORCE UNSTUCK] Menerima sinyal force unstuck dari Admin! Membatalkan tugas macet...", BOLD + YELLOW)
                if 'SMART_DEBUGGER' in globals() and SMART_DEBUGGER:
                    if SMART_DEBUGGER.active_task and not SMART_DEBUGGER.active_task.done():
                        SMART_DEBUGGER.active_task.cancel()
                    if SMART_DEBUGGER.active_subprocess_pid:
                        SMART_DEBUGGER._kill_hung_process_tree(SMART_DEBUGGER.active_subprocess_pid)
                    SMART_DEBUGGER.stop_watching()
                _CONSUMED_COMMAND_TO_SEND = 'force_unstuck'
            elif cmd == 'clear_temp':
                log("REMOTE_CMD", "🧹 [CLEAR TEMP] Menerima sinyal pembersihan folder temporary dari Admin...", CYAN)
                clean_stale_temp_files(max_age_sec=0, force_emergency=True)
                _CONSUMED_COMMAND_TO_SEND = 'clear_temp'
            elif cmd == 'update_now':
                s_h = (resp_data.get('auto_update') or {}).get('script_hash')
                cur_h = get_current_script_hash()
                if s_h and cur_h and cur_h == s_h:
                    log("REMOTE_CMD", f"✓ Versi worker ({cur_h[:8]}) sudah cocok dengan server. Selesai.", GREEN)
                    _CONSUMED_COMMAND_TO_SEND = 'update_now'
                else:
                    log("REMOTE_CMD", "🚀 [UPDATE NOW] Menerima sinyal pembaruan langsung dari server! Memperbarui worker sekarang...", BOLD + CYAN)
                    dl_u = (resp_data.get('auto_update') or {}).get('download_url') or f"{API_URL}/worker-script"
                    threading.Thread(target=perform_self_update, args=(dl_u, s_h), daemon=False).start()

            pace = resp_data.get('pace_mode')
            if pace:
                global OVERRIDE_PACE_MODE
                OVERRIDE_PACE_MODE = pace

        except Exception:
            pass
    threading.Thread(target=_do_post, daemon=True).start()

def safe_write_json(filepath, data) -> bool:
    """Tulis file JSON dengan aman, unhide file Windows jika tersembunyi agar tidak terjadi PermissionError."""
    try:
        p = Path(filepath)
        if sys.platform == "win32" and p.exists():
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(str(p), 0x80)  # FILE_ATTRIBUTE_NORMAL
            except Exception:
                pass
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False

def update_worker_lease(role: str) -> None:
    try:
        data = {
            'holder': role,
            'worker_id': get_worker_id(),
            'shard': WORKER_SHARD,
            'platform': sys.platform,
            'hostname': socket.gethostname(),
            'pid': os.getpid(),
            'status': 'paused' if is_remotely_paused() else 'running',
            'timestamp': int(time.time()),
            'last_active': now_wib().strftime('%Y-%m-%d %H:%M:%S') + ' WIB'
        }
        safe_write_json(LEASE_FILE, data)

        # Jika di Windows dan drive Z:\ ada (Samba ke CasaOS), sinkronkan juga langsung ke Z:\
        if sys.platform == "win32" and not str(SCRIPT_DIR).lower().startswith('z:'):
            z_lease = Path("Z:/tools/terop-worker/.worker_lease.json")
            if z_lease.parent.exists():
                safe_write_json(z_lease, data)
    except Exception:
        pass

_lease_keeper_started = False

def start_lease_keeper(role: str = "laptop"):
    """Background daemon thread di Laptop/Colab/Warnet yang memperbarui lease setiap 10 detik."""
    global _lease_keeper_started
    if _lease_keeper_started:
        return
    _lease_keeper_started = True

    try:
        update_worker_lease(role)
        if role in REMOTE_ROLES:
            effective_status = "paused" if is_remotely_paused() else "running"
            update_heartbeat(status=effective_status, current_task="Memulai...")
    except Exception:
        pass

    def _keeper():
        _clean_tick = 0
        while True:
            time.sleep(10)
            _clean_tick += 1
            # Setiap 3 menit atau jika disk rendah, jalankan pembersihan file sementara otomatis
            if _clean_tick % 18 == 0 or get_disk_free_mb() < 2500:
                try:
                    is_emerg = get_disk_free_mb() < 2500
                    clean_stale_temp_files(max_age_sec=1800 if not is_emerg else 600, force_emergency=is_emerg)
                except Exception:
                    pass
            try:
                update_worker_lease(role)
                if role in REMOTE_ROLES:
                    effective_status = "paused" if is_remotely_paused() else "running"
                    update_heartbeat(status=effective_status, current_task=None)
            except Exception:
                pass
    t = threading.Thread(target=_keeper, daemon=True, name="LeaseKeeper")
    t.start()

def has_active_remote_workers() -> bool:
    """Mengecek apakah ada remote worker (Laptop, Colab, Warnet, Azure, AWS, VPS, dll)
    yang sedang aktif di cluster Nipnime. Jika ada minimal 1 remote worker aktif,
    server CasaOS WAJIB 100% STANDBY SIAGA dan TIDAK MELAKUKAN APAPUN."""
    now = time.time()

    # 1. Cek registry .active_workers.json (sumber utama real-time cluster)
    active_files = [
        SCRIPT_DIR / '.active_workers.json',
        SCRIPT_DIR.parent / '.active_workers.json',
    ]
    if sys.platform == "win32":
        active_files.append(Path("Z:/tools/terop-worker/.active_workers.json"))

    for af in active_files:
        try:
            if af.exists() and af.stat().st_size > 5:
                with open(af, 'r', encoding='utf-8') as f:
                    workers_map = json.load(f)
                if isinstance(workers_map, dict):
                    for wid, wdata in workers_map.items():
                        if not isinstance(wdata, dict):
                            continue
                        w_role = str(wdata.get('role', '')).lower()
                        # Lewati server lokal itu sendiri
                        if w_role == 'server' or 'casaos' in wid.lower() or 'casaos' in str(wdata.get('hostname', '')).lower():
                            continue
                        # Cek apakah status paused atau killed
                        if wdata.get('is_paused') or wdata.get('status') in ('paused', 'killed', 'stopped'):
                            continue
                        # Cek keaktifan timestamp (aktif dalam 180 detik terakhir)
                        last_act = wdata.get('last_active', 0)
                        if isinstance(last_act, (int, float)) and (now - last_act) < 180:
                            return True
        except Exception:
            pass

    # 2. Cek .worker_lease.json
    lease_files = [
        LEASE_FILE,
        SCRIPT_DIR / '.worker_lease.json',
        SCRIPT_DIR.parent / '.worker_lease.json',
    ]
    if sys.platform == "win32":
        lease_files.append(Path("Z:/tools/terop-worker/.worker_lease.json"))

    for lf in lease_files:
        try:
            if lf.exists() and lf.stat().st_size > 5:
                with open(lf, 'r', encoding='utf-8') as f:
                    ldata = json.load(f)
                if isinstance(ldata, dict):
                    holder = str(ldata.get('holder', '')).lower()
                    if holder in REMOTE_ROLES and holder != 'server':
                        if ldata.get('status') != 'paused':
                            diff = now - ldata.get('timestamp', 0)
                            if diff < 180:
                                return True
        except Exception:
            pass

    # 3. Cek .remote_worker_heartbeat.json
    rw_hb_files = [
        SCRIPT_DIR / '.remote_worker_heartbeat.json',
        SCRIPT_DIR.parent / '.remote_worker_heartbeat.json',
    ]
    if sys.platform == "win32":
        rw_hb_files.append(Path("Z:/tools/terop-worker/.remote_worker_heartbeat.json"))

    for rwf in rw_hb_files:
        try:
            if rwf.exists() and rwf.stat().st_size > 5:
                with open(rwf, 'r', encoding='utf-8') as f:
                    hb_data = json.load(f)
                if isinstance(hb_data, dict):
                    r_role = str(hb_data.get('role', '')).lower()
                    if r_role in REMOTE_ROLES and r_role != 'server':
                        if hb_data.get('status') != 'paused':
                            diff = now - hb_data.get('timestamp', 0)
                            if diff < 180:
                                return True
        except Exception:
            pass

    return False

def is_laptop_active() -> bool:
    """Mengecek apakah ada worker di Laptop Windows, Warnet, Azure, atau Google Colab yang sedang aktif memproses."""
    return has_active_remote_workers()

_last_current_task = "Standby"

def update_heartbeat(status="running", current_task=None):
    global _last_api_heartbeat_time, _last_current_task
    try:
        role = get_device_role()
        remote_active = has_active_remote_workers()
        if role == "server" and remote_active:
            status = "standby"
            if current_task is None:
                current_task = "💤 Standby Siaga (Cluster Remote Worker Aktif)"

        if is_remotely_paused():
            status = "paused"

        if current_task is not None:
            _last_current_task = current_task
        else:
            current_task = _last_current_task

        if role in REMOTE_ROLES:
            update_worker_lease(role)

        active_tasks = []
        if 'PROGRESS_MGR' in globals():
            try:
                PROGRESS_MGR.prune_stale_tasks(max_idle_sec=60)
                with PROGRESS_MGR.lock:
                    for k, t in list(PROGRESS_MGR.tasks.items()):
                        active_tasks.append({
                            'key': k,
                            'label': t.get('label', ''),
                            'pct': round(float(t.get('pct', 0)), 1),
                            'cur_mb': round(float(t.get('cur_mb', 0)), 1),
                            'tot_mb': round(float(t.get('tot_mb', 0)), 1),
                            'speed_mb': round(float(t.get('speed_mb', 0)), 1),
                            'eta_str': t.get('eta_str', ''),
                            'status_text': t.get('status_text', ''),
                            'category': t.get('category', 'ongoing')
                        })
            except Exception:
                pass

        render_q_count = 0
        try:
            if '_RENDER_QUEUE' in globals() and _RENDER_QUEUE is not None:
                render_q_count = _RENDER_QUEUE.qsize()
        except Exception:
            pass

        hw_payload = {}
        try:
            import psutil
            cpu_pct = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory()
            disk = shutil.disk_usage(str(TEMP_DOWNLOAD_DIR))
            staging_2k_dir = TEMP_DOWNLOAD_DIR / "staging_2k"
            staging_2k_mb = 0.0
            staged_count = 0
            if staging_2k_dir.exists():
                staged_files = [f for f in staging_2k_dir.iterdir() if f.is_file()]
                staged_count = len(staged_files)
                staging_2k_mb = sum(f.stat().st_size for f in staged_files) / (1024 * 1024)

            hw_payload = {
                'cpu_usage_pct': round(cpu_pct, 1),
                'ram_used_gb': round(ram.used / (1024**3), 1),
                'ram_total_gb': round(ram.total / (1024**3), 1),
                'ram_usage_pct': round(ram.percent, 1),
                'disk_free_gb': round(disk.free / (1024**3), 1),
                'disk_total_gb': round(disk.total / (1024**3), 1),
                'disk_staging_2k_mb': round(staging_2k_mb, 1),
                'disk_staged_files_count': staged_count,
                'gpu': get_gpu_gaming_state()
            }
        except Exception:
            pass

        data = {
            'last_heartbeat': now_wib().strftime('%Y-%m-%d %H:%M:%S') + ' WIB',
            'timestamp': int(time.time()),
            'status': status,
            'is_paused': is_remotely_paused(),
            'current_task': current_task,
            'active_tasks': active_tasks,
            'render_queue_count': render_q_count,
            'recent_logs': RECENT_LOGS[-40:],
            'pid': os.getpid(),
            'platform': sys.platform,
            'hostname': socket.gethostname(),
            'role': role,
            'worker_id': get_worker_id(),
            'script_hash': _CURRENT_SCRIPT_HASH,
            'shard': WORKER_SHARD if _manual_shard_locked else 'auto',
            'shard_desc': get_shard_description() if _manual_shard_locked else None,
            'manual_shard': bool(_manual_shard_locked),
            'hardware': hw_payload,
            'pipeline_activity': SMART_DEBUGGER.get_status_summary() if ('SMART_DEBUGGER' in globals() and SMART_DEBUGGER) else {},
            'stuck_incidents': SMART_DEBUGGER.stuck_incidents_log[-5:] if ('SMART_DEBUGGER' in globals() and SMART_DEBUGGER) else []
        }

        global _CONSUMED_COMMAND_TO_SEND
        if '_CONSUMED_COMMAND_TO_SEND' in globals() and _CONSUMED_COMMAND_TO_SEND:
            data['command_consumed'] = _CONSUMED_COMMAND_TO_SEND
            _CONSUMED_COMMAND_TO_SEND = None

        # 1. Tulis ke file heartbeat lokal
        if role != "server" or not remote_active:
            safe_write_json(HEARTBEAT_FILE, data)
        if role == "server":
            safe_write_json(SCRIPT_DIR / '.server_worker_heartbeat.json', data)

        # 2. Jika di Windows dan drive Z:\ ada (Samba ke CasaOS), sinkronkan juga langsung ke Z:\
        if sys.platform == "win32" and not str(SCRIPT_DIR).lower().startswith('z:'):
            z_dir = Path("Z:/tools/terop-worker")
            if z_dir.exists():
                safe_write_json(z_dir / '.remote_worker_heartbeat.json', data)
                safe_write_json(z_dir / '.worker_heartbeat.json', data)

        # 3. Kirim ke API Nipnime (rate-limited tiap 2 detik agar tidak membebani)
        now_ts = time.time()
        if role in REMOTE_ROLES and (now_ts - _last_api_heartbeat_time >= 2):
            _last_api_heartbeat_time = now_ts
            # Kirim full state hanya tiap 30 detik agar tidak membaca file disk berukuran besar tiap 2 detik di tengah upload
            global _last_full_state_sync_time
            if '_last_full_state_sync_time' not in globals():
                _last_full_state_sync_time = 0.0
            if (now_ts - _last_full_state_sync_time >= 30):
                _last_full_state_sync_time = now_ts
                try:
                    if ONGOING_STATE_FILE.exists():
                        with open(ONGOING_STATE_FILE, 'r', encoding='utf-8') as sf:
                            data['ongoing_state'] = json.load(sf)
                except Exception:
                    pass
                try:
                    comp_file = None
                    for cp in (SCRIPT_DIR / '.completed_anime_state.json', Path('.completed_anime_state.json'), Path('/app/.completed_anime_state.json')):
                        if cp.exists():
                            comp_file = cp
                            break
                    if comp_file:
                        with open(comp_file, 'r', encoding='utf-8') as cf:
                            data['completed_state'] = json.load(cf)
                except Exception:
                    pass
            _send_heartbeat_api_async(data)

    except Exception:
        pass

if sys.platform == 'win32':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        h_out = kernel32.GetStdHandle(-11)
        cmode = ctypes.c_ulong()
        kernel32.GetConsoleMode(h_out, ctypes.byref(cmode))
        kernel32.SetConsoleMode(h_out, cmode.value | 0x0004)
    except Exception:
        pass

class LiveProgressManager:
    """Manajer visual progress bar multi-task dinamis yang tampil rapi di tempat tanpa scrolling spam."""
    def __init__(self):
        self.tasks = {}
        self.last_rendered_count = 0
        self.lock = threading.RLock()
        self.last_render_time = 0
        is_cloud_notebook = os.path.exists('/content') or 'google.colab' in sys.modules or os.path.exists('/work') or 'deepnote' in sys.modules
        self.is_interactive = (sys.stdout.isatty() or sys.platform == 'win32') and not is_cloud_notebook
        self._last_non_interactive_log = {}

    def update(self, key, label, cur_mb=0.0, tot_mb=1.0, speed_mb=0.0, eta_str="", status_text="", pct=None, category=None, **kwargs):
        with self.lock:
            cur_mb = float(cur_mb or 0.0)
            tot_mb = float(tot_mb or 1.0)
            if pct is not None:
                calc_pct = float(pct)
            else:
                calc_pct = (cur_mb / tot_mb * 100) if tot_mb > 0 else 0
            calc_pct = min(100.0, max(0.0, calc_pct))

            existing_cat = self.tasks.get(key, {}).get('category')
            cat = category or existing_cat
            if not cat:
                combined_low = (label or '').lower() + ' ' + (key or '').lower()
                cat = 'tamat' if any(w in combined_low for w in ['tamat', 'batch', 'kusonime', 'otakudesu', 'extract_']) else 'ongoing'

            self.tasks[key] = {
                'label': label,
                'cur_mb': cur_mb,
                'tot_mb': tot_mb,
                'pct': calc_pct,
                'speed_mb': float(speed_mb or 0.0),
                'eta_str': str(eta_str or ""),
                'status_text': str(status_text or ""),
                'category': cat,
                'updated_at': time.time()
            }
            self._sync_heartbeat(key)

            if self.is_interactive:
                self._render_interactive()
            else:
                self._render_non_interactive(key)

    def remove(self, key):
        with self.lock:
            self.tasks.pop(key, None)
            self._last_non_interactive_log.pop(key, None)
            self._sync_heartbeat()
            if self.is_interactive:
                self._clear_rendered()
                self._render_interactive(force=True)

    def prune_stale_tasks(self, max_idle_sec: int = 60):
        with self.lock:
            now = time.time()
            stale_keys = []
            for k, t in list(self.tasks.items()):
                age = now - t.get('updated_at', now)
                # Task tanpa progres (0% dan 0 MB) dipangkas setelah 30 detik
                max_age = 30 if (t.get('pct', 0) == 0 and t.get('cur_mb', 0) == 0) else max_idle_sec
                if age > max_age:
                    stale_keys.append(k)
            for k in stale_keys:
                self.tasks.pop(k, None)
                self._last_non_interactive_log.pop(k, None)
            if stale_keys:
                if self.is_interactive:
                    self._clear_rendered()
                    self._render_interactive(force=True)

    def _safe_write(self, text):
        try:
            if sys.stdout is not None and hasattr(sys.stdout, 'write'):
                sys.stdout.write(text)
                if hasattr(sys.stdout, 'flush'):
                    sys.stdout.flush()
        except Exception:
            pass

    def print_log(self, text):
        with self.lock:
            if not self.is_interactive:
                self._safe_write(f"{text}\n")
                return

            self._clear_rendered()
            self._safe_write(f"\r\033[2K{text}\n")
            self._render_interactive(force=True)

    def _clear_rendered(self):
        if self.last_rendered_count > 0:
            self._safe_write(f"\033[{self.last_rendered_count}A")
            for _ in range(self.last_rendered_count):
                self._safe_write("\r\033[2K\n")
            self._safe_write(f"\033[{self.last_rendered_count}A")
            self.last_rendered_count = 0

    def _render_interactive(self, force=False):
        now = time.time()
        if not force and (now - self.last_render_time < 0.2):
            return
        self.last_render_time = now

        if self.last_rendered_count > 0:
            self._safe_write(f"\033[{self.last_rendered_count}A")

        if not self.tasks:
            for _ in range(self.last_rendered_count):
                self._safe_write("\r\033[2K\n")
            if self.last_rendered_count > 0:
                self._safe_write(f"\033[{self.last_rendered_count}A")
            self.last_rendered_count = 0
            return

        term_width = shutil.get_terminal_size((80, 24)).columns
        lines = []
        bar_len = 14
        for k, t in list(self.tasks.items()):
            pct = t['pct']
            filled = int(bar_len * (pct / 100))
            is_rnd = 'render' in t['label'].lower() or 'watermark' in t['label'].lower()
            if is_rnd:
                bar_visual = f"{MAGENTA}{'█' * filled}{GRAY}{'░' * (bar_len - filled)}{RESET}"
                spd = f"@{t['speed_mb']:.0f}FPS" if t['speed_mb'] > 0 else ""
                stat = t['status_text'] or f"{t['cur_mb']:.0f}s/{t['tot_mb']:.0f}s"
                lbl_color = MAGENTA
            else:
                bar_visual = f"{GREEN}{'█' * filled}{GRAY}{'░' * (bar_len - filled)}{RESET}"
                spd = f"@{t['speed_mb']:.1f}MB/s" if t['speed_mb'] > 0 else ""
                stat = t['status_text'] or f"{t['cur_mb']:.1f}/{t['tot_mb']:.1f}MB"
                lbl_color = CYAN

            eta = f"ETA:{t['eta_str']}" if t['eta_str'] else ""
            details = " ".join(filter(None, [stat, spd, eta]))

            # Hitung alokasi label agar tidak terjadi line wrapping di terminal apapun
            fixed_len = 3 + 2 + bar_len + 2 + 7 + 3 + len(details)
            avail_label = max(15, term_width - fixed_len - 2)
            lbl = t['label']
            if len(lbl) > avail_label:
                lbl = lbl[:max(1, avail_label - 3)] + '...'
            lbl_pad = f"{lbl:<{avail_label}}"

            line = f" ► {lbl_color}{lbl_pad}{RESET} [{bar_visual}] {BOLD}{pct:5.1f}%{RESET} | {details}"
            lines.append(line)

        for l in lines:
            self._safe_write(f"\r\033[2K{l}\n")
        self.last_rendered_count = len(lines)

    def _render_non_interactive(self, key):
        t = self.tasks.get(key)
        if not t: return
        pct = int(t['pct'])
        last_logged = self._last_non_interactive_log.get(key, -1)
        prev_m = last_logged // 20 if last_logged >= 0 else -1
        curr_m = pct // 20
        if curr_m > prev_m or (pct == 100 and last_logged < 100):
            self._last_non_interactive_log[key] = pct
            t_now = now_wib().strftime('%H:%M:%S')
            is_rnd = 'render' in t['label'].lower() or 'watermark' in t['label'].lower()
            if is_rnd:
                spd_str = f" @ {t['speed_mb']:.0f} FPS" if t['speed_mb'] > 0 else ""
                self._safe_write(f"[{t_now}] [PROGRESS] {t['label']}: {pct}% ({t['cur_mb']:.0f}s/{t['tot_mb']:.0f}s){spd_str}\n")
            else:
                spd_str = f" @ {t['speed_mb']:.1f}MB/s" if t['speed_mb'] > 0 else ""
                self._safe_write(f"[{t_now}] [PROGRESS] {t['label']}: {pct}% ({t['cur_mb']:.1f}/{t['tot_mb']:.1f}MB){spd_str}\n")

    def _sync_heartbeat(self, active_key=None):
        n = len(self.tasks)
        if n == 1:
            t = list(self.tasks.values())[0]
            lbl_low = t.get('label', '').lower()
            is_tamat_t = (t.get('category') == 'tamat' or any(w in lbl_low for w in ['batch', 'tamat', 'kusonime', 'otakudesu', 'extract_']))
            cat_tag = "[TAMAT] " if is_tamat_t else "[ONGOING] "
            is_rnd = 'render' in lbl_low or 'watermark' in lbl_low
            if is_rnd:
                spd_str = f" @ {t['speed_mb']:.0f} FPS" if t['speed_mb'] > 0 else ""
                summary = f"{cat_tag}{t['label']}: {t['pct']:.0f}% ({t['cur_mb']:.0f}s/{t['tot_mb']:.0f}s{spd_str})"
            else:
                summary = f"{cat_tag}{t['label']}: {t['pct']:.0f}% ({t['cur_mb']:.1f}/{t['tot_mb']:.1f} MB)"
        elif n > 1:
            parts = []
            for t in list(self.tasks.values())[:3]:
                lbl_low = t.get('label', '').lower()
                is_tamat_t = (t.get('category') == 'tamat' or any(w in lbl_low for w in ['batch', 'tamat', 'kusonime', 'otakudesu', 'extract_']))
                cat_tag = "[TAMAT] " if is_tamat_t else "[ONGOING] "
                parts.append(f"{cat_tag}{t['label']} ({t['pct']:.0f}%)")
            summary = f"⚡ Paralel ({n} Task): " + " | ".join(parts)
        else:
            summary = "Standby"

        update_heartbeat(status="running", current_task=summary)

PROGRESS_MGR = LiveProgressManager()

def update_task_progress(task_key: str, desc: str, pct: int = 0):
    pass

def finish_task_progress(task_key: str):
    PROGRESS_MGR.remove(task_key)

def log(tag: str, msg: str, color=CYAN):
    t = now_wib().strftime('%H:%M:%S')
    clean_line = f"[{t}] [{tag}] {msg}"
    formatted = f"{GRAY}[{t}]{RESET} {color}{BOLD}[{tag}]{RESET} {msg}"
    PROGRESS_MGR.print_log(formatted)
    RECENT_LOGS.append(clean_line)
    if len(RECENT_LOGS) > 60:
        RECENT_LOGS.pop(0)
    update_heartbeat(status="running", current_task=f"[{tag}] {msg}")

if set_archive_logger:
    try:
        set_archive_logger(log)
    except Exception:
        pass

def check_credentials():
    missing = []
    if not API_ID: missing.append("TELEGRAM_API_ID")
    if not API_HASH: missing.append("TELEGRAM_API_HASH")
    if not BOT_TOKEN: missing.append("TELEGRAM_BOT_TOKEN")
    if not CHANNEL_ID: missing.append("TELEGRAM_CHANNEL_ID")

    if missing:
        log("ERROR", f"Kredensial Telegram belum lengkap di .env: {', '.join(missing)}", RED)
        return False
    return True

def load_ongoing_state() -> dict:
    if not ONGOING_STATE_FILE.exists():
        if get_device_role() in ('colab', 'laptop', 'warnet', 'azure'):
            sync_state_from_server()
        if not ONGOING_STATE_FILE.exists():
            return {}
    try:
        with open(ONGOING_STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict) and not isinstance(v.get('failed_urls'), dict):
                        v['failed_urls'] = {}
            return data
    except Exception:
        return {}

def save_ongoing_state(state: dict):
    try:
        # Pangkas riwayat lama agar state tidak membengkak tanpa batas:
        # Pertahankan maksimal 15 episode terbaru, prioritaskan yang masih berstatus 'partial'
        if len(state) > 15:
            sorted_keys = sorted(
                state.keys(),
                key=lambda k: (state[k].get('status') != 'complete', state[k].get('last_checked_at', 0)),
                reverse=True
            )
            state = {k: state[k] for k in sorted_keys[:15]}

        with open(ONGOING_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass

def sync_state_from_server() -> dict:
    """Mengunduh state antrian anime tamat & ongoing dari server Nipnime jika lokal masih kosong (misal di Colab)."""
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{API_URL}/state",
            headers={
                'Accept': 'application/json',
                'X-Terop-Token': WORKER_TOKEN,
                'User-Agent': DEFAULT_UA
            }
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('success'):
                    comp = data.get('completed_state')
                    if isinstance(comp, list):
                        comp = {'otakudesu_page': 1, 'queue': comp, 'history': {}}
                    if isinstance(comp, dict) and comp.get('queue'):
                        hist = comp.get('history') or {}
                        for it in comp['queue']:
                            it.pop('retry_after', None)
                            norm = normalize_title(it.get('title', ''))
                            if it.get('status') in ('in_progress', 'pending'):
                                hist.pop(norm, None)
                            elif hist.get(norm) == 'complete':
                                it['status'] = 'complete'
                            elif it.get('status') == 'not_in_db':
                                it['status'] = 'pending'
                        comp['history'] = hist
                        save_completed_state(comp)
                        log("SYNC", f"✓ Berhasil sinkronisasi {len(comp.get('queue', []))} antrian anime tamat dari server CasaOS!", GREEN)
                    ong = data.get('ongoing_state')
                    if ong:
                        save_ongoing_state(ong)
                        log("SYNC", f"✓ Berhasil sinkronisasi {len(ong)} status episode ongoing dari server CasaOS!", GREEN)
                    ace_cookies = data.get('acefile_cookies')
                    if ace_cookies:
                        for cp in [Path.cwd() / '.acefile_cookies.json', Path('/content/.acefile_cookies.json')]:
                            try:
                                with open(cp, 'w', encoding='utf-8') as f:
                                    json.dump(ace_cookies, f, indent=2)
                            except Exception:
                                pass
                    return data
    except Exception as e:
        log("SYNC_WARN", f"Gagal sinkron state dari server: {e}", YELLOW)
    return {}

def normalize_title(title: str) -> str:
    title = re.sub(r'\[[^\]]*\]', ' ', title)
    title = re.sub(r'\([^\)]*\)', ' ', title)
    title = re.sub(r'\b(subtitle indonesia|sub indo)\b', ' ', title, flags=re.IGNORECASE)
    title = re.sub(r'[^a-zA-Z0-9\s]', ' ', title)
    title = re.sub(r'\s+', ' ', title)
    return title.strip().lower()

def safe_file_slug(title: str, max_len: int = 50) -> str:
    """Menghasilkan slug judul aman yang dipotong maksimal 50 karakter agar tidak melebihi batas Linux filesystem (NAME_MAX 255)."""
    norm = normalize_title(title).replace(' ', '-')
    clean = re.sub(r'-+', '-', norm).strip('-')
    if len(clean) > max_len:
        clean = clean[:max_len].rstrip('-')
    return clean or 'anime'

def extract_season_number(text: str) -> int:
    """
    Ekstrak nomor season dari judul anime atau slug URL.
    Mengembalikan integer nomor season (default 1 jika season 1 atau tidak disebutkan).
    """
    text_clean = str(text).lower().replace('_', ' ')
    # 1. Season X / Musim X (misal: Season 2, season-2, musim 3)
    m = re.search(r'\b(?:season|musim)[_\s-]*(\d+)\b', text_clean)
    if m:
        return int(m.group(1))
    # 2. Xth / Xnd / Xrd / Xst Season (misal: 2nd Season, 3rd Season)
    m = re.search(r'\b(\d+)(?:st|nd|rd|th)[_\s-]*(?:season|musim)?\b', text_clean)
    if m:
        return int(m.group(1))
    # 3. s2, s3, -s2 di kata terpisah atau akhir slug
    m = re.search(r'(?:\b|[-_])s(\d+)(?:\b|[-_]|$)', text_clean)
    if m:
        return int(m.group(1))
    # 4. Angka Romawi (diurutkan dari yang terpanjang: viii, vii, iii, vi, iv, ix, ii, x, v)
    roman_pairs = [('viii', 8), ('vii', 7), ('iii', 3), ('vi', 6), ('iv', 4), ('ix', 9), ('ii', 2), ('x', 10), ('v', 5)]
    for r_str, r_val in roman_pairs:
        if re.search(rf'(?:\b|[-_]){r_str}(?:\b|[-_]|$)', text_clean):
            return r_val
    # 5. Angka tunggal 2-15 di akhir judul atau sebelum episode/part/bracket/kata pemisah
    # Contoh: "Da Wang Rao Ming 3", "da-wang-rao-ming-2-episode-5", "Kingdom 5"
    base_text = re.sub(r'\b(?:episode|ep|eps)[_\s-]*\d+\b', '', text_clean)
    base_text = re.sub(r'\b(?:part|cour)[_\s-]*\d+\b', '', base_text)
    m = re.search(r'(?:\b|[-_])([2-9]|1[0-5])(?:\s*\[|\s*\(|[-_\s]*$)', base_text)
    if m:
        return int(m.group(1))
    return 1

def extract_part_number(text: str) -> int:
    """Ekstrak nomor part/cour jika ada (misal Part 2, Cour 2). Default 0 jika tidak ada."""
    text_clean = str(text).lower().replace('_', ' ')
    m = re.search(r'\b(?:part|cour|bagian)[_\s-]*(\d+)\b', text_clean)
    if m:
        return int(m.group(1))
    return 0

def is_season_match(target_title: str, candidate_str: str) -> bool:
    """
    Memastikan season dan part antara judul target dan kandidat sumber benar-benar sama.
    Mencegah salah season (Season 1 nyasar ke Season 2 atau sebaliknya).
    """
    t_season = extract_season_number(target_title)
    c_season = extract_season_number(candidate_str)

    # Deteksi kecocokan subtitle arc spesifik:
    # Contoh: "Tougen Anki S2 Nikko Kegon No Taki Hen" vs "tougen-anki-nikko-kegon-no-taki-hen"
    # Jika kedua string berbagi >= 3 kata unik arc yang sama (bukan stop words),
    # maka ini adalah anime/arc yang sama persis meskipun salah satu menulis S2 dan yang lain tidak.
    t_clean = normalize_title(target_title)
    c_clean = normalize_title(candidate_str)
    stopwords = {'season', 'musim', 'part', 'cour', 'sub', 'indo', 'subtitle', 'indonesia', 'anime', 'episode', 'ep', 's1', 's2', 's3', 's4'}
    t_words = set(w for w in re.findall(r'[a-zA-Z0-9]+', t_clean) if len(w) >= 3 and w not in stopwords)
    c_words = set(w for w in re.findall(r'[a-zA-Z0-9]+', c_clean) if len(w) >= 3 and w not in stopwords)
    common_arc_words = t_words & c_words
    is_strong_arc_match = len(common_arc_words) >= 3

    if t_season != c_season:
        if not (is_strong_arc_match and (t_season == 1 or c_season == 1)):
            return False
    
    t_part = extract_part_number(target_title)
    c_part = extract_part_number(candidate_str)
    # Jika salah satu secara eksplisit Part 2 (atau Part > 1), keduanya WAJIB memiliki nomor Part yang sama!
    # Mencegah anime Part 2 menyedot episode dari Season 1 / Part 1 (atau sebaliknya).
    if (t_part > 1 or c_part > 1) and t_part != c_part:
        return False
    if t_part > 0 and c_part > 0 and t_part != c_part:
        return False
    return True



async def fetch_html_stealth(session: aiohttp.ClientSession, url: str, referer: str = None) -> tuple[int, str]:
    role = get_device_role()

    # 1. curl_cffi dengan Chrome 120 TLS fingerprint
    if HAS_CURL_CFFI:
        try:
            def _run_curl():
                hdrs = {'Referer': referer} if referer else None
                cks = None
                if 'animesail' in url.lower():
                    cks = {'_as_ipin_tz': 'Asia/Jakarta', '_as_ipin_lc': 'id-ID', '_as_ipin_ct': 'ID'}
                return c_requests.get(
                    url,
                    headers=hdrs,
                    cookies=cks,
                    impersonate="chrome120",
                    timeout=15,
                    verify=False
                )
            c_resp = await asyncio.to_thread(_run_curl)
            if c_resp.status_code == 200:
                txt = c_resp.text
                if not any(k in txt.lower() for k in ['turnstile', 'just a moment', 'cf-browser-verification', '<title>loading..</title>']):
                    return 200, txt
        except Exception:
            pass

    # 2. Direct aiohttp GET fallback (Sangat cepat & efektif untuk Otakudesu, Kuramanime, Samehadaku dll)
    try:
        req_headers = {
            'User-Agent': DEFAULT_UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
        }
        if referer:
            req_headers['Referer'] = referer
        req_cookies = None
        if 'animesail' in url.lower():
            req_cookies = {'_as_ipin_tz': 'Asia/Jakarta', '_as_ipin_lc': 'id-ID', '_as_ipin_ct': 'ID'}
        async with session.get(url, headers=req_headers, cookies=req_cookies, ssl=False, timeout=aiohttp.ClientTimeout(total=12)) as d_resp:
            if d_resp.status == 200:
                txt = await d_resp.text()
                if not any(k in txt.lower() for k in ['turnstile', 'just a moment', 'cf-browser-verification']):
                    return 200, txt
    except Exception:
        pass

    # 3. Puppeteer Microservice (HANYA untuk internal server CasaOS / jika worker punya microservice lokal sendiri)
    # Remote worker (Laptop, Colab, Warnet dll) DILARANG KERAS melempar scraping ke server CasaOS.
    if role == 'server' or PUPPETEER_URL:
        p_hosts = []
        if role == 'server':
            p_hosts.extend(['http://nipnime-puppeteer:3000', 'http://localhost:3000', 'http://127.0.0.1:3000'])
            if PUPPETEER_URL:
                p_hosts.append(PUPPETEER_URL)
        elif PUPPETEER_URL and '192.168.' not in PUPPETEER_URL and 'nipnime' not in PUPPETEER_URL:
            p_hosts.append(PUPPETEER_URL)

        for p_url in list(dict.fromkeys(filter(None, p_hosts))):
            try:
                pupp_endpoint = f"{p_url}/fetch-html"
                payload = {'url': url}
                async with session.post(pupp_endpoint, json=payload, timeout=aiohttp.ClientTimeout(total=10, connect=2.0)) as p_resp:
                    if p_resp.status == 200:
                        p_data = await p_resp.json()
                        if p_data.get('success') and p_data.get('html'):
                            return 200, p_data['html']
                        break
            except Exception:
                continue

    # 4. FlareSolverr (HANYA untuk internal server CasaOS / jika worker punya microservice lokal sendiri)
    if role == 'server' or FLARESOLVERR_URL:
        f_hosts = []
        if role == 'server':
            f_hosts.extend(['http://nipnime-flaresolverr:8191/v1', 'http://localhost:8191/v1', 'http://127.0.0.1:8191/v1'])
            if FLARESOLVERR_URL:
                f_hosts.append(FLARESOLVERR_URL)
        elif FLARESOLVERR_URL and '192.168.' not in FLARESOLVERR_URL and 'nipnime' not in FLARESOLVERR_URL:
            f_hosts.append(FLARESOLVERR_URL)

        for f_url in list(dict.fromkeys(filter(None, f_hosts))):
            try:
                payload = {'cmd': 'request.get', 'url': url, 'maxTimeout': 20000}
                async with session.post(f_url, json=payload, timeout=aiohttp.ClientTimeout(total=24, connect=2.0)) as f_resp:
                    if f_resp.status == 200:
                        f_data = await f_resp.json()
                        sol = f_data.get('solution', {})
                        if sol.get('response'):
                            return sol.get('status', 200), sol['response']
            except Exception:
                continue

    # 5. Remote API Fallback ke CasaOS dinonaktifkan permanen agar tidak membebani CPU server CasaOS.
    return 503, ''

# ==============================================================================
# 1. PEMANTAU FEED RILISAN TERBARU (ONGOING WATCHERS)
# ==============================================================================
async def scan_animesail_latest(session: aiohttp.ClientSession) -> list:
    """Membaca episode yang baru saja rilis di halaman utama AnimeSail."""
    if is_worker_quarantined() or is_remotely_paused():
        return []
    url = "https://v1.animesail.xyz/"
    status, html_content = await fetch_html_stealth(session, url)
    if status != 200 or not html_content:
        return []

    episodes = []
    pattern = r'<article[^>]*class="[^"]*bs\s+([^"]*)"[^>]*data-id="(\d+)"[^>]*>(.*?)</article>'
    matches = re.findall(pattern, html_content, flags=re.DOTALL)
    for m in matches:
        content = m[2]
        link_m = re.search(r'<a\s+href="([^"]+)"[^>]*title="([^"]+)"', content)
        if link_m:
            ep_url = link_m.group(1)
            raw_title = html.unescape(link_m.group(2))
            ep_num = 1
            ep_match = re.search(r'episode\s*(\d+)', raw_title, re.I)
            if ep_match:
                ep_num = int(ep_match.group(1))

            clean_anime_title = re.sub(r'\s+episode\s*\d+.*$', '', raw_title, flags=re.I).strip()
            ts_m = re.search(r'data-t="([^"]+)"', content)
            rel_time = ts_m.group(1) if ts_m else datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            episodes.append({
                'source': 'AnimeSail',
                'anime_title': clean_anime_title,
                'episode_number': ep_num,
                'episode_url': f"https://v1.animesail.xyz{ep_url}" if ep_url.startswith('/') else ep_url,
                'released_at': rel_time
            })
    return episodes

async def scan_kuramanime_latest(session: aiohttp.ClientSession) -> list:
    """Membaca episode yang baru saja rilis di feed resmi Ongoing Kuramanime (/quick/ongoing)."""
    if is_worker_quarantined() or is_remotely_paused():
        return []
    # Gunakan endpoint resmi Ongoing terurut dari yang paling baru rilis
    url = "https://v20.kuramanime.ing/quick/ongoing?order_by=updated"
    status, html_content = await fetch_html_stealth(session, url)
    if status != 200 or not html_content:
        url = "https://v20.kuramanime.ing/"
        status, html_content = await fetch_html_stealth(session, url)
        if status != 200 or not html_content:
            return []

    # Bersihkan widget sidebar komentar / diskusi agar anime lawas (seperti Naruto) tidak ikut terbaca
    clean_html = re.sub(r'<div[^>]*class="[^"]*sidebar[^"]*"[^>]*>[\s\S]*?<\/div>', '', html_content, flags=re.I)
    clean_html = re.sub(r'<div[^>]*class="[^"]*comment[^"]*"[^>]*>[\s\S]*?<\/div>', '', clean_html, flags=re.I)

    episodes = []
    pattern = r'href="(?:https?://[^/]+)?/anime/(\d+)/([a-z0-9-]+)/episode/(\d+)"'
    matches = re.findall(pattern, clean_html)
    seen = set()

    for m in matches:
        aid, slug, ep_str = m[0], m[1], m[2]
        key = f"{aid}:{ep_str}"
        if key in seen:
            continue
        seen.add(key)
        ep_num = int(ep_str)

        roman_slug_map = {'-ii': ' II', '-iii': ' III', '-iv': ' IV', '-v': ' V', '-vi': ' VI', '-vii': ' VII', '-viii': ' VIII', '-ix': ' IX', '-x': ' X'}
        clean_slug = slug
        roman_suffix = ""
        for r_slug, r_roman in roman_slug_map.items():
            if clean_slug.endswith(r_slug):
                clean_slug = clean_slug[:-len(r_slug)]
                roman_suffix = r_roman
                break
        clean_anime_title = clean_slug.replace('-', ' ').title() + roman_suffix
        ep_url = f"https://v20.kuramanime.ing/anime/{aid}/{slug}/episode/{ep_num}"

        episodes.append({
            'source': 'Kuramanime',
            'anime_title': clean_anime_title,
            'anime_slug': slug,
            'anime_id': aid,
            'episode_number': ep_num,
            'episode_url': ep_url,
            'released_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    return episodes

async def scan_nontonanimeid_latest(session: aiohttp.ClientSession) -> list:
    """Membaca episode yang baru saja rilis di halaman utama NontonAnimeID."""
    if is_worker_quarantined() or is_remotely_paused():
        return []
    url = "https://s13.nontonanimeid.boats/"
    status, html_content = await fetch_html_stealth(session, url)
    if status != 200 or not html_content:
        return []

    episodes = []
    pattern = r'<article[^>]*>.*?<a\s+href="https?://[^/]+/anime/([^/]+)/".*?<span class="types episodes">.*?(\d+)\s*</span>.*?alt="([^"]*)".*?</article>'
    matches = re.findall(pattern, html_content, flags=re.DOTALL)
    for m in matches:
        slug = m[0]
        ep_num = int(m[1])
        title = html.unescape(m[2]).strip()
        ep_url = f"https://s13.nontonanimeid.boats/{slug}-episode-{ep_num}/"

        episodes.append({
            'source': 'NontonAnimeID',
            'anime_title': title,
            'anime_slug': slug,
            'episode_number': ep_num,
            'episode_url': ep_url,
            'released_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    return episodes

async def scan_samehadaku_latest(session: aiohttp.ClientSession) -> list:
    """Membaca episode yang baru saja rilis di feed beranda Samehadaku (https://v2.samehadaku.how/)."""
    if is_worker_quarantined() or is_remotely_paused():
        return []
    url = "https://v2.samehadaku.how/"
    status, html_content = await fetch_html_stealth(session, url)
    if status != 200 or not html_content:
        return []

    episodes = []
    pattern = r'<div\s+class="animposx">\s*<a[^>]*href="([^"]+-episode-(\d+)/?)"[^>]*title="([^"]*)"'
    matches = re.findall(pattern, html_content)
    if not matches:
        pattern = r'<article[^>]*>[\s\S]*?<a\s+href="([^"]+-episode-(\d+)/?)"[^>]*title="([^"]*)"'
        matches = re.findall(pattern, html_content)

    for m in matches:
        ep_url = m[0]
        ep_num = int(m[1])
        raw_title = html.unescape(m[2]).strip()
        clean_anime_title = re.sub(r'\s+episode\s*\d+.*$', '', raw_title, flags=re.I).strip()
        if not clean_anime_title:
            clean_anime_title = raw_title

        episodes.append({
            'source': 'Samehadaku',
            'anime_title': clean_anime_title,
            'episode_number': ep_num,
            'episode_url': ep_url,
            'released_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    return episodes

async def scan_oploverz_latest(session: aiohttp.ClientSession) -> list:
    """Membaca episode yang baru saja rilis di feed beranda Oploverz (https://oploverz.site/)."""
    if is_worker_quarantined() or is_remotely_paused():
        return []
    url = "https://oploverz.site/"
    status, html_content = await fetch_html_stealth(session, url)
    if status != 200 or not html_content:
        return []

    episodes = []
    pattern = r'href="(?:https?://oploverz\.site)?/series/([a-zA-Z0-9-]+)/episode/(\d+)"'
    matches = re.findall(pattern, html_content)
    seen = set()

    ignored_static = {'black-clover:1', 'one-piece:1', 'bleach:1'}
    for slug, ep_str in matches:
        key = f"{slug}:{ep_str}"
        if key in seen or key in ignored_static:
            continue
        seen.add(key)
        ep_num = int(ep_str)
        clean_anime_title = slug.replace('-', ' ').title()
        ep_url = f"https://oploverz.site/series/{slug}/episode/{ep_num}"

        episodes.append({
            'source': 'Oploverz',
            'anime_title': clean_anime_title,
            'anime_slug': slug,
            'episode_number': ep_num,
            'episode_url': ep_url,
            'released_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    return episodes

async def scan_otakudesu_latest(session: aiohttp.ClientSession) -> list:
    """Membaca episode ongoing terbaru dari Otakudesu (https://otakudesu.blog/ongoing-anime/)."""
    if is_worker_quarantined() or is_remotely_paused():
        return []
    url = "https://otakudesu.blog/ongoing-anime/"
    status, html_content = await fetch_html_stealth(session, url)
    if status != 200 or not html_content:
        return []

    episodes = []
    pattern = r'<div\s+class="detpost">[\s\S]*?<a\s+href="([^"]+)"[\s\S]*?<h2[^>]*>(.*?)</h2>[\s\S]*?<div\s+class="epz"[^>]*>(.*?)</div>'
    matches = re.findall(pattern, html_content)
    for m in matches:
        anime_url = m[0]
        title = html.unescape(m[1]).strip()
        epz = m[2].strip()
        ep_m = re.search(r'(\d+)', epz)
        ep_num = int(ep_m.group(1)) if ep_m else 1

        episodes.append({
            'source': 'Otakudesu',
            'anime_title': title,
            'episode_number': ep_num,
            'episode_url': anime_url,
            'released_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    return episodes

# ==============================================================================
# 2. RESOLVER & EKSTRAKTOR RESOLUSI
# ==============================================================================
def resolve_mp4upload_direct(url_or_id: str) -> str:
    """Mendapatkan link direct MP4 dari Mp4Upload (embed)."""
    m = re.search(r'mp4upload\.com/(?:embed-)?([a-zA-Z0-9_-]+)', str(url_or_id))
    if m:
        file_id = m.group(1).replace('.html', '')
    else:
        file_id = str(url_or_id).replace('.html', '').strip()

    if not file_id:
        return None

    embed_url = f"https://www.mp4upload.com/embed-{file_id}.html"
    try:
        if HAS_CURL_CFFI:
            r = c_requests.get(
                embed_url,
                headers={'Referer': 'https://www.mp4upload.com/'},
                impersonate='chrome120',
                timeout=12,
                verify=False
            )
            if r.status_code == 200:
                v_src = re.findall(r'src:\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']', r.text)
                if v_src:
                    return v_src[0]
    except Exception:
        pass
    return None

def resolve_kotakanime_out(landing_url: str) -> tuple[str, str]:
    """Mengurai landing link s2.kotakanimeid.link/out/... menjadi URL download langsung."""
    try:
        if not HAS_CURL_CFFI:
            return None, None
        s = c_requests.Session(impersonate="chrome120")
        r = s.get(landing_url, verify=False, timeout=12)
        dl_m = re.search(r'window\.DL\s*=\s*(\{.*?\});', r.text, flags=re.DOTALL)
        if not dl_m:
            return None, None

        js_obj_str = dl_m.group(1)
        enc = re.search(r'encrypted:\s*["\']([^"\']+)["\']', js_obj_str).group(1)
        gate = re.search(r'gate:\s*(\d+)', js_obj_str).group(1)
        sig = re.search(r'sig:\s*["\']([^"\']+)["\']', js_obj_str).group(1)

        tok_res = s.post("https://s2.kotakanimeid.link/video/get-token.php", headers={
            "Content-Type": "application/json",
            "X-Fingerprint": "dummy-fingerprint",
            "X-DL-Gate": str(gate),
            "X-DL-Sig": sig,
            "Referer": landing_url
        }, json={"url": enc}, timeout=10)
        tok_data = tok_res.json()
        if not tok_data.get('success'):
            return None, None

        dl_res = s.post("https://s2.kotakanimeid.link/video/get-download.php", headers={
            "Content-Type": "application/json",
            "X-Security-Token": tok_data['token'],
            "X-Timestamp": str(tok_data['timestamp']),
            "X-Fingerprint": "dummy-fingerprint",
            "X-Challenge": tok_data['challenge'],
            "Referer": landing_url
        }, json={"url": enc, "challenge": tok_data['challenge']}, timeout=10)

        dl_data = dl_res.json()
        if dl_data.get('status') == 'success' and dl_data.get('links', {}).get('download'):
            dl_path = dl_data['links']['download'][0]['url']
            final_dl_url = f"https://s2.kotakanimeid.link{dl_path}" if dl_path.startswith('/') else dl_path
            fin_res = s.get(final_dl_url, allow_redirects=False, verify=False, timeout=10)
            target = fin_res.headers.get('location')
            if target:
                if 'mp4upload.com' in target:
                    direct_mp4 = resolve_mp4upload_direct(target)
                    return direct_mp4 or target, 'Mp4Upload'
                if 'pixeldrain.com' in target:
                    pd_m = re.search(r'/(?:u|d)/([a-zA-Z0-9_-]+)', target)
                    if pd_m:
                        return f"https://pixeldrain.com/api/file/{pd_m.group(1)}?download", 'Pixeldrain'
                # Saring landing page iklan / shortener / agregator yang bukan link video langsung
                bad_hosts = ['mir.cr', 'mirrorcreator', 'blogspot.', 'linkbox', 'safelink', 'shorturl', 'ouo.io', 'mega.nz', 'mediafire', 'zippyshare', 'gofile']
                if any(bh in target.lower() for bh in bad_hosts):
                    return None, None
                return target, 'Direct'
    except Exception:
        pass
async def resolve_desustream_link(session: aiohttp.ClientSession, url: str) -> tuple[str, str]:
    """Mengurai tautan https://link.desustream.com/?id=... menjadi direct Google Drive / AceFile / Pixeldrain / Mp4Upload URL."""
    if resolve_desustream_full:
        try:
            d_url, host, hdrs = await asyncio.to_thread(resolve_desustream_full, url)
            if d_url:
                return d_url, host
        except Exception:
            pass

    loc = None
    try:
        req_headers = {
            'User-Agent': DEFAULT_UA,
            'Referer': 'https://otakudesu.blog/'
        }
        async with session.get(url, headers=req_headers, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=6)) as resp:
            loc = resp.headers.get('Location')
    except Exception:
        loc = None

    if not loc and API_URL:
        try:
            api_endpoint = f"{API_URL}/resolve-link"
            api_headers = {
                'Content-Type': 'application/json',
                'X-Terop-Token': WORKER_TOKEN,
                'User-Agent': DEFAULT_UA
            }
            async with session.post(api_endpoint, json={'url': url}, headers=api_headers, timeout=aiohttp.ClientTimeout(total=8)) as a_resp:
                if a_resp.status == 200:
                    a_data = await a_resp.json()
                    loc = a_data.get('location')
        except Exception:
            pass

    if not loc:
        return None, None
    if 'pixeldrain.com' in loc:
        m = re.search(r'/(?:u|d)/([a-zA-Z0-9_-]+)', loc)
        if m:
            return f"https://pixeldrain.com/api/file/{m.group(1)}?download", 'Pixeldrain'
    if 'mp4upload.com' in loc:
        direct = resolve_mp4upload_direct(loc)
        return direct or loc, 'Mp4Upload'
    return loc, 'Direct'

def _is_valid_stream(url: str, cookie: str = None) -> bool:
    """Verifikasi cepat (timeout 4 detik) apakah direct URL benar-benar file video dan bukan halaman login / HTML / quota."""
    if not url or "accounts.google.com" in url or "/signin" in url:
        return False
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': DEFAULT_UA,
                'Range': 'bytes=0-2048',
                'Cookie': cookie or ''
            }
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
            c_type = resp.headers.get('Content-Type', '').lower()
            if any(h in c_type for h in ['text/html', 'text/plain', 'application/json']):
                return False
            data = resp.read(512)
            if b'<html' in data.lower() or b'<!doctype' in data.lower():
                return False
            return resp.status in (200, 206)
    except Exception:
        return False

def resolve_acefile_to_direct(acefile_url: str) -> tuple[str, str]:
    """
    Mengurai tautan Acefile (https://acefile.co/f/... atau /d/...) menjadi direct Google Drive CDN stream super cepat (10-30+ MB/s).
    Mendukung auto-fallback ke Acefile Mirror API (/service/mirror_download/{id}) jika link utama limit kuota / 404 / butuh login.
    """
    try:
        possible_cookie_paths = [
            Path.cwd() / '.acefile_cookies.json',
            Path('/content/.acefile_cookies.json'),
            Path(__file__).resolve().parent / '.acefile_cookies.json',
            Path(__file__).resolve().parent.parent / '.acefile_cookies.json',
            Path('/app/.acefile_cookies.json'),
            Path('/app/tools/terop-worker/.acefile_cookies.json'),
            Path('/home/naufal/Web-Anime/tools/terop-worker/.acefile_cookies.json'),
            Path('Z:/tools/terop-worker/.acefile_cookies.json'),
            Path('D:/tools/terop-worker/.acefile_cookies.json')
        ]
        cookie_file = None
        for cp in possible_cookie_paths:
            if cp.exists():
                cookie_file = cp
                break

        cookies = {}
        if cookie_file:
            try:
                with open(cookie_file, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
            except Exception:
                pass

        cookie_hdr = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        headers = {
            'User-Agent': DEFAULT_UA,
            'Referer': 'https://acefile.co/',
            'Cookie': cookie_hdr
        }

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        import http.cookiejar
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), urllib.request.HTTPSHandler(context=ctx))

        m_fid = re.search(r'/f/(\d+)', acefile_url)
        file_id = m_fid.group(1) if m_fid else None

        # 1. Coba unduh via halaman /f/ -> token /d/
        target_d_url = acefile_url
        if '/f/' in acefile_url:
            try:
                req_f = urllib.request.Request(acefile_url, headers=headers)
                with opener.open(req_f, timeout=8) as r_f:
                    f_html = r_f.read().decode('utf-8', errors='ignore')
                tokens = re.findall(r'https://acefile\.co/d/([a-zA-Z0-9_-]+)', f_html)
                if tokens:
                    target_d_url = f"https://acefile.co/d/{tokens[0]}"
            except Exception:
                pass

        primary_failed = False
        if target_d_url and '/d/' in target_d_url:
            try:
                req_d = urllib.request.Request(target_d_url, headers=headers)
                with opener.open(req_d, timeout=8) as r_d:
                    final_url = r_d.geturl()
                    body = r_d.read().decode('utf-8', errors='ignore')

                if any(q_kw in body.lower() for q_kw in ["quota exceeded", "too many users", "ratelimitexceeded"]) or "accounts.google.com" in final_url:
                    log("ACEFILE", "Link utama terkena limit kuota / butuh login. Mencari mirror alternatif...", YELLOW)
                    primary_failed = True
                elif ("drive.usercontent.google.com" in final_url or "drive.google.com" in final_url) and "accounts.google.com" not in final_url:
                    google_cookies = [f"{c.name}={c.value}" for c in cj if 'google.com' in c.domain]
                    gdrive_cookie = "; ".join(google_cookies) if google_cookies else "; ".join([f"{c.name}={c.value}" for c in cj])
                    form_m = re.search(r'<form[^>]*id="download-form"[^>]*>([\s\S]*?)</form>', body)
                    candidate = None
                    if form_m:
                        inputs = dict(re.findall(r'<input\s+type="hidden"\s+name="([^"]+)"\s+value="([^"]*)"', form_m.group(1)))
                        if inputs:
                            candidate = f"https://drive.usercontent.google.com/download?{urlencode(inputs)}"
                    elif "export=download" in final_url or "/download" in final_url:
                        candidate = final_url

                    if candidate and _is_valid_stream(candidate, gdrive_cookie):
                        return candidate, gdrive_cookie
                    else:
                        log("ACEFILE", "Stream link utama tidak valid (HTML / 404). Mencari mirror...", YELLOW)
                        primary_failed = True
                else:
                    primary_failed = True
            except Exception:
                primary_failed = True

        # 2. Jika link utama limit kuota / gagal / 404, panggil Mirror API: /service/mirror_download/{file_id}
        if (primary_failed or not target_d_url) and file_id:
            try:
                mirror_req = urllib.request.Request(
                    f"https://acefile.co/service/mirror_download/{file_id}",
                    headers={'User-Agent': DEFAULT_UA, 'Referer': acefile_url}
                )
                with opener.open(mirror_req, timeout=8) as m_resp:
                    m_data = json.loads(m_resp.read().decode('utf-8', errors='ignore'))

                items = m_data.get('AceFile', []) if isinstance(m_data, dict) else (m_data if isinstance(m_data, list) else [])
                for item in items:
                    code = item.get('code')
                    if code:
                        try:
                            gdrive_id = base64.b64decode(code).decode('utf-8', errors='ignore').strip()
                            if gdrive_id and len(gdrive_id) > 10:
                                uc_url = f"https://drive.google.com/uc?export=download&id={gdrive_id}"
                                req_uc = urllib.request.Request(uc_url, headers={'User-Agent': DEFAULT_UA})
                                with opener.open(req_uc, timeout=8) as r_uc:
                                    uc_final = r_uc.geturl()
                                    uc_body = r_uc.read().decode('utf-8', errors='ignore')

                                if "accounts.google.com" in uc_final or any(q_kw in uc_body.lower() for q_kw in ["quota exceeded", "too many users", "ratelimitexceeded"]):
                                    continue

                                google_cookies = [f"{c.name}={c.value}" for c in cj if 'google.com' in c.domain]
                                gdrive_cookie = "; ".join(google_cookies) if google_cookies else "; ".join([f"{c.name}={c.value}" for c in cj])
                                form_m = re.search(r'<form[^>]*id="download-form"[^>]*>([\s\S]*?)</form>', uc_body)
                                candidate = None
                                if form_m:
                                    inputs = dict(re.findall(r'<input\s+type="hidden"\s+name="([^"]+)"\s+value="([^"]*)"', form_m.group(1)))
                                    if inputs:
                                        candidate = f"https://drive.usercontent.google.com/download?{urlencode(inputs)}"
                                elif "drive.usercontent.google.com" in uc_final and ("export=download" in uc_final or "/download" in uc_final):
                                    candidate = uc_final

                                if candidate and _is_valid_stream(candidate, gdrive_cookie):
                                    log("ACEFILE_MIRROR", f"✓ Berhasil mengurai stream dari mirror Google Drive ({gdrive_id})!", GREEN)
                                    return candidate, gdrive_cookie
                        except Exception:
                            pass
            except Exception:
                pass

    except Exception as e:
        log("ACEFILE_ERR", f"Error resolve_acefile: {type(e).__name__}: {e}", RED)
    return None, None

def resolve_gofile_to_direct(gofile_url: str) -> tuple[str, str]:
    """Mengurai tautan Gofile (https://gofile.io/d/...) menjadi direct CDN stream + account token cookie via Puppeteer."""
    try:
        req_body = json.dumps({'url': gofile_url}).encode('utf-8')
        
        # 1. Coba hubungi Puppeteer lokal jika ada (HANYA untuk role == 'server' atau Puppeteer lokal)
        role = get_device_role()
        puppeteer_targets = []
        if role == 'server':
            puppeteer_targets.extend([
                'http://nipnime-puppeteer:3000/gofile-link',
                'http://localhost:3000/gofile-link',
                'http://127.0.0.1:3000/gofile-link',
                f"{PUPPETEER_URL}/gofile-link" if PUPPETEER_URL else None
            ])
        elif PUPPETEER_URL and '192.168.' not in PUPPETEER_URL and 'nipnime' not in PUPPETEER_URL:
            puppeteer_targets.append(f"{PUPPETEER_URL}/gofile-link")
        
        for p_target in filter(None, puppeteer_targets):
            try:
                req = urllib.request.Request(
                    p_target,
                    data=req_body,
                    headers={'Content-Type': 'application/json', 'User-Agent': DEFAULT_UA}
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                    if data.get('success') and data.get('directLink'):
                        cookie = data.get('cookieHeader') or (f"accountToken={data['token']}" if data.get('token') else None)
                        return data['directLink'], cookie
            except Exception:
                continue

        # 2. Fallback ke CasaOS API dinonaktifkan untuk melindungi CPU server.
        pass

    except Exception as e:
        log("GOFILE_ERR", f"Error resolve_gofile: {type(e).__name__}: {e}", RED)
    return None, None

async def resolve_kamado_direct(session: aiohttp.ClientSession, embed_url: str) -> str:
    """Mengurai embed player-kturbo / Kamado (AnimeSail) langsung ke Google Drive API URL."""
    try:
        m_id = re.search(r'/play/([a-zA-Z0-9]+)', embed_url)
        if not m_id:
            return ""
        video_id = m_id.group(1)

        pq = parse_qs(urlparse(embed_url).query)
        token = pq.get('token', [''])[0]

        parsed = urlparse(embed_url)
        host = parsed.netloc or 'player-kturbo.154999000.xyz'
        scheme = parsed.scheme or 'https'
        play_url = f"{scheme}://{host}/play/{video_id}" + (f"?token={quote(token)}" if token else "")

        headers = {
            'User-Agent': DEFAULT_UA,
            'Referer': 'https://v1.animesail.xyz/'
        }
        async with session.get(play_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10), ssl=False) as resp:
            if resp.status != 200:
                return ""
            cookie = resp.cookies.get('kturbo_session')
            cookie_val = cookie.value if cookie else ""
            body = await resp.text()

        m_nonce = re.search(r'__NONCE__\s*=\s*[\'"]([^\'"]+)', body)
        if not m_nonce:
            return ""
        nonce = m_nonce.group(1)

        resolve_url = f"{scheme}://{host}/api/resolve/{video_id}?action=init&nonce={quote(nonce)}" + (f"&token={quote(token)}" if token else "")
        req_headers = {
            'User-Agent': DEFAULT_UA,
            'Referer': play_url,
            'Accept': 'application/json'
        }
        if cookie_val:
            req_headers['Cookie'] = f"kturbo_session={cookie_val}"

        async with session.get(resolve_url, headers=req_headers, timeout=aiohttp.ClientTimeout(total=10), ssl=False) as r_resp:
            if r_resp.status != 200:
                return ""
            try:
                raw_text = await r_resp.text()
                r_json = json.loads(raw_text)
                if isinstance(r_json, dict) and r_json.get('status') == 'success' and r_json.get('data', {}).get('sourceUrl'):
                    return r_json['data']['sourceUrl']
            except Exception:
                pass
            return ""
    except Exception as e:
        log("KAMADO_SKIP", f"Kamado direct tidak dapat diurai ({embed_url[:35]}...): {e}", GRAY)
    return ""

async def extract_qualities_from_animesail(session: aiohttp.ClientSession, episode_url: str, extra_info: dict = None) -> dict:
    """Ekstrak semua resolusi dari episode AnimeSail (Pixeldrain, Mp4Upload, dan Kamado/GoogleDrive)."""
    qualities = {}

    # 0. JALUR NIPNIME PLAYER PROXY: Query database videoServers / KamadoExtractor via Nipnime API
    if API_URL:
        try:
            p_payload = {'url': episode_url}
            if extra_info and extra_info.get('episode_id'):
                p_payload['episode_id'] = extra_info['episode_id']
            async with PLAYER_STREAM_SEM:
                async with session.post(
                    f"{API_URL}/player-stream",
                    json=p_payload,
                    headers={'X-Terop-Token': WORKER_TOKEN, 'Content-Type': 'application/json'},
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as p_resp:
                    if p_resp.status == 200:
                        p_data = await p_resp.json()
                        streams = p_data.get('streams') or {}
                        for q, s_info in streams.items():
                            qualities[q] = {
                                'url': s_info.get('direct_url') or s_info['url'],
                                'direct_url': s_info.get('direct_url'),
                                'host': s_info.get('host', 'AnimeSail (KamadoDrive)'),
                                'source': 'AnimeSail',
                                'type': s_info.get('type', 'mp4'),
                                'embed_url': s_info.get('embed_url')
                            }
                    if qualities:
                        log("ANIMESAIL_STREAM", f"⚡ Berhasil mendapatkan {len(qualities)} stream AnimeSail / Kamado dari Nipnime API ({', '.join(qualities.keys())})!", GREEN)
        except Exception as e:
            log("ANIMESAIL_WARN", f"Query player-stream AnimeSail gagal: {e}", YELLOW)

    status, ep_html = await fetch_html_stealth(session, episode_url)
    if status != 200 or not ep_html:
        return qualities

    # 1. AnimeSail sering menaruh tabel download di halaman streaming-download (?id=XXXX)
    dl_page_match = re.search(r'href=["\']([^"\']*streaming-download[^"\']*)["\']', ep_html, re.I)
    dl_html = ""
    if dl_page_match:
        dl_rel = dl_page_match.group(1)
        dl_url = urljoin(episode_url, dl_rel)
        _, dl_html = await fetch_html_stealth(session, dl_url)

    combined_htmls = [dl_html, ep_html] if dl_html else [ep_html]

    for h_content in combined_htmls:
        if not h_content:
            continue

        # A. Parse tabel baris <tr><td>(resolusi)</td><td>(link)</td></tr>
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', h_content, flags=re.DOTALL | re.I)
        for r in rows:
            tds = re.findall(r'<td[^>]*>(.*?)</td>', r, flags=re.DOTALL | re.I)
            if not tds:
                continue
            first_text = re.sub(r'<[^>]+>', '', tds[0]).strip()
            qm = re.search(r'\b(1080|720|480|360)p?\b', first_text, re.I)
            if not qm:
                qm = re.search(r'\b(1080|720|480|360)p?\b', r, re.I)
            if not qm:
                continue

            q_key = f"{qm.group(1)}p"

            # 1. Acefile (Google Drive CDN 10-30+ MB/s, Prioritas Tertinggi)
            af_m = re.findall(r'(?:href|data-href)=["\'](https?://acefile\.co/[fd]/[a-zA-Z0-9_-]+(?:\/[^"\']*)?)["\']', r)
            if af_m and (q_key not in qualities or is_better_source({'host': 'Acefile'}, qualities[q_key])):
                qualities[q_key] = {
                    'url': af_m[0],
                    'host': 'Acefile',
                    'source': 'AnimeSail'
                }

            # 2. Pixeldrain (cek href dan data-href)
            pd_ids = re.findall(r'pixeldrain\.com/(?:u|d)/([a-zA-Z0-9_-]+)', r)
            if pd_ids and (q_key not in qualities or is_better_source({'host': 'Pixeldrain'}, qualities[q_key])):
                qualities[q_key] = {
                    'url': f"https://pixeldrain.com/api/file/{pd_ids[0]}?download",
                    'host': 'Pixeldrain',
                    'source': 'AnimeSail'
                }

            # 3. Mp4Upload (cek href dan data-href)
            mp4_ids = re.findall(r'mp4upload\.com/(?:embed-)?([a-zA-Z0-9_-]+)', r)
            if mp4_ids and q_key not in qualities:
                clean_id = mp4_ids[0].replace('.html', '')
                direct = await asyncio.to_thread(resolve_mp4upload_direct, clean_id)
                if direct:
                    qualities[q_key] = {'url': direct, 'host': 'Mp4Upload', 'source': 'AnimeSail'}

        # B. Fallback blok tag (div/li/p) jika bukan struktur <tr>
        if not qualities:
            blocks = re.findall(r'(<(?:div|li|p)[^>]*>.*?(?:1080|720|480|360).*?<\/(?:div|li|p)>)', h_content, flags=re.DOTALL | re.I)
            for block in blocks:
                qm = re.search(r'\b(1080|720|480|360)p?\b', block, re.I)
                if not qm: continue
                q_key = f"{qm.group(1)}p"
                af_m = re.findall(r'(?:href|data-href)=["\'](https?://acefile\.co/[fd]/[a-zA-Z0-9_-]+(?:\/[^"\']*)?)["\']', block)
                if af_m and (q_key not in qualities or is_better_source({'host': 'Acefile'}, qualities[q_key])):
                    qualities[q_key] = {'url': af_m[0], 'host': 'Acefile', 'source': 'AnimeSail'}
                pd_m = re.findall(r'pixeldrain\.com/(?:u|d)/([a-zA-Z0-9_-]+)', block)
                for file_id in pd_m:
                    if q_key not in qualities or is_better_source({'host': 'Pixeldrain'}, qualities[q_key]):
                        qualities[q_key] = {'url': f"https://pixeldrain.com/api/file/{file_id}?download", 'host': 'Pixeldrain', 'source': 'AnimeSail'}

    # C. Cek base64 embed player (Mp4Upload & Kamado/Kturbo) jika ada resolusi yang belum ketemu
    b64_embeds = re.findall(r'data-(?:default|embed|content)=["\']([a-zA-Z0-9+/=]{20,})["\']', ep_html)
    opt_matches = re.findall(r'<option[^>]*data-em=["\']([a-zA-Z0-9+/=]{20,})["\'][^>]*>(.*?)</option>', ep_html, re.I)
    opt_matches += re.findall(r'<option[^>]*value=["\']([a-zA-Z0-9+/=]{20,})["\'][^>]*>(.*?)</option>', ep_html, re.I)

    all_embed_candidates = [(b, '720p') for b in b64_embeds]
    for b_code, opt_text in opt_matches:
        qm = re.search(r'\b(1080|720|480|360)p?\b', opt_text, re.I)
        target_q = f"{qm.group(1)}p" if qm else "720p"
        all_embed_candidates.append((b_code, target_q))

    for b64, cand_q in all_embed_candidates:
        try:
            decoded = base64.b64decode(b64).decode('utf-8', errors='ignore')
            # Cek Kamado / Kturbo
            if any(k in decoded for k in ['kturbo', '154999000', '/play/', 'kodir']):
                src_m = re.search(r'src=["\']([^"\']+)["\']', decoded)
                kamado_url = src_m.group(1) if src_m else decoded
                if cand_q not in qualities or is_better_source({'host': 'AnimeSail (KamadoDrive)'}, qualities[cand_q]):
                    kamado_direct = await resolve_kamado_direct(session, kamado_url)
                    if kamado_direct:
                        qualities[cand_q] = {
                            'url': kamado_direct,
                            'direct_url': kamado_direct,
                            'host': 'AnimeSail (KamadoDrive)',
                            'source': 'AnimeSail',
                            'type': 'mp4'
                        }
            # Cek Mp4Upload
            mp4_m = re.findall(r'mp4upload\.com/(?:embed-)?([a-zA-Z0-9_-]+)', decoded)
            if mp4_m and cand_q not in qualities:
                clean_id = mp4_m[0].replace('.html', '')
                direct = await asyncio.to_thread(resolve_mp4upload_direct, clean_id)
                if direct:
                    qualities[cand_q] = {'url': direct, 'host': 'Mp4Upload', 'source': 'AnimeSail'}
        except Exception:
            pass

    return qualities

async def extract_qualities_from_kuramanime(session: aiohttp.ClientSession, episode_url: str) -> dict:
    """Ekstrak semua resolusi dari episode Kuramanime (Kuramadrive direct MP4)."""
    status, ep_html = await fetch_html_stealth(session, episode_url)
    if status != 200 or not ep_html:
        return {}

    qualities = {}

    # 1. Regex kdrive direct MP4 dari HTML
    kdrive_matches = re.findall(r'(https?://[^\s"\'<>]+(?:kdrive|kuramadrive|\.mp4)[^\s"\'<>]*)', ep_html, re.I)
    for raw_link in kdrive_matches:
        clean_link = html.unescape(raw_link).replace('\\/', '/')
        # JANGAN ambil URL halaman web Kuramanime (/anime/..., /logs/..., dll) atau proxy mati (komi.my.id)
        if any(bad in clean_link.lower() for bad in ['/anime/', '/logs/', 'error', 'page=', 'komi.my.id']):
            continue
        if not ('.mp4' in clean_link.lower() or 'kdrive' in clean_link.lower() or 'amiya.my.id' in clean_link.lower()):
            continue

        q = '720p'
        qm = re.search(r'(1080|720|480|360)p?', clean_link, re.I)
        if qm: q = f"{qm.group(1)}p"
        if q not in qualities:
            qualities[q] = {'url': clean_link, 'host': 'Kuramadrive', 'source': 'Kuramanime'}

    # 2. Puppeteer kura-stream microservice (Hanya untuk internal host CasaOS jika tersedia di localhost)
    if not qualities or len(qualities) < 3:
        p_targets = []
        role = get_device_role()
        # Remote workers (Colab, Laptop, Warnet, Azure) dilarang melempar kura-stream ke CasaOS server
        if role == 'server':
            p_targets.append({'url': f"{PUPPETEER_URL}/kura-stream", 'headers': {}})
            p_targets.append({'url': 'http://nipnime-puppeteer:3000/kura-stream', 'headers': {}})
            p_targets.append({'url': 'http://localhost:3000/kura-stream', 'headers': {}})

        for p_target in p_targets:
            try:
                kura_api = p_target['url']
                hdrs = p_target.get('headers') or {}
                async with session.post(kura_api, json={'url': episode_url}, headers=hdrs, timeout=aiohttp.ClientTimeout(total=18)) as ks_resp:
                    if ks_resp.status == 200:
                        ks_data = await ks_resp.json()

                        # A. Prioritas 1: sources array dari Plyr player (720p, 480p, 360p)
                        for item in ks_data.get('sources', []):
                            s_url = item.get('src')
                            if not s_url or any(bad in s_url.lower() for bad in ['komi.my.id', 'error', 'blank']):
                                continue
                            size = item.get('size')
                            q = f"{size}p" if size else '720p'
                            qm = re.search(r'(1080|720|480|360)p?', s_url, re.I)
                            if qm:
                                q = f"{qm.group(1)}p"
                            qualities[q] = {'url': html.unescape(s_url), 'host': 'Kuramadrive', 'source': 'Kuramanime'}

                        # B. Prioritas 2: sourceSrc (Direct raw MP4 video URL dari player)
                        src_direct = ks_data.get('sourceSrc')
                        if src_direct and not any(bad in src_direct.lower() for bad in ['komi.my.id', 'error']) and ('.mp4' in src_direct or 'kdrive' in src_direct or 'amiya' in src_direct):
                            q = '720p'
                            qm = re.search(r'(1080|720|480|360)p?', src_direct, re.I)
                            if qm: q = f"{qm.group(1)}p"
                            if q not in qualities:
                                qualities[q] = {'url': html.unescape(src_direct), 'host': 'Kuramadrive', 'source': 'Kuramanime'}

                        # C. Prioritas 3: Network media requests (Hanya yang benar-benar video file)
                        for m_url in ks_data.get('media', []):
                            clean_m = html.unescape(m_url)
                            if any(bad in clean_m.lower() for bad in ['/anime/', '/logs/', 'error', 'page=', 'komi.my.id']):
                                continue
                            if '.mp4' in clean_m or 'kdrive' in clean_m or 'amiya' in clean_m:
                                q = '720p'
                                qm = re.search(r'(1080|720|480|360)p?', clean_m, re.I)
                                if qm: q = f"{qm.group(1)}p"
                                if q not in qualities:
                                    qualities[q] = {'url': clean_m, 'host': 'Kuramadrive', 'source': 'Kuramanime'}
                        break
            except Exception:
                continue

    return qualities

async def extract_qualities_from_nontonanimeid(session: aiohttp.ClientSession, episode_url: str, extra_info: dict = None) -> dict:
    """Ekstrak semua resolusi dari episode NontonAnimeID (Nipnime Player Proxy / KotakAnime / Mp4Upload / Pixeldrain)."""
    qualities = {}

    # 0. Prioritas Utama: Ekstrak stream resolusi langsung dari Nipnime Player Proxy (KotakAnime HLS 1080p/720p/480p atau Google Video MP4)
    if API_URL:
        try:
            p_payload = {'url': episode_url}
            if extra_info and extra_info.get('episode_id'):
                p_payload['episode_id'] = extra_info['episode_id']
            async with PLAYER_STREAM_SEM:
                async with session.post(
                    f"{API_URL}/player-stream",
                    json=p_payload,
                    headers={'X-Terop-Token': WORKER_TOKEN, 'Content-Type': 'application/json'},
                    timeout=aiohttp.ClientTimeout(total=25)
                ) as p_resp:
                    if p_resp.status == 200:
                        p_data = await p_resp.json()
                        streams = p_data.get('streams') or {}
                        for q, s_info in streams.items():
                            qualities[q] = {
                                'url': s_info.get('direct_url') or s_info['url'],
                                'direct_url': s_info.get('direct_url'),
                                'host': s_info.get('host', 'KotakAnime-Proxy'),
                                'source': 'NontonAnimeID',
                                'type': s_info.get('type', 'mp4'),
                                'embed_url': s_info.get('embed_url')
                            }
                    if qualities:
                        log("PLAYER_PROXY", f"⚡ Berhasil mendapatkan {len(qualities)} stream dari Nipnime Player Proxy ({', '.join(qualities.keys())})!", GREEN)
                        return qualities
        except Exception as e:
            log("PLAYER_WARN", f"Query player-stream API gagal/timeout: {e}", YELLOW)

    status, ep_html = await fetch_html_stealth(session, episode_url)
    if status != 200 or not ep_html:
        return qualities

    # 1. KotakAnime out redirect
    out_links = re.findall(r'href="(https?://[^"]*kotakanimeid\.link/out/[^"]+)"', ep_html)
    for out_url in out_links:
        try:
            pos = ep_html.find(out_url)
            ctx = ep_html[max(0, pos-200):min(len(ep_html), pos+200)] if pos != -1 else ""
            qm = re.search(r'\b(1080|720|480|360)p?\b', ctx, re.I)
            q_key = f"{qm.group(1)}p" if qm else "720p"

            direct_url, host = await asyncio.to_thread(resolve_kotakanime_out, out_url)
            if direct_url and q_key not in qualities:
                qualities[q_key] = {'url': direct_url, 'host': host, 'source': 'NontonAnimeID'}
        except Exception:
            pass

    # 2. Mp4Upload langsung
    mp4_links = re.findall(r'https?://(?:www\.)?mp4upload\.com/(?:embed-)?([a-zA-Z0-9_-]+)', ep_html)
    for fid in mp4_links:
        direct = await asyncio.to_thread(resolve_mp4upload_direct, fid)
        if direct and '720p' not in qualities:
            qualities['720p'] = {'url': direct, 'host': 'Mp4Upload', 'source': 'NontonAnimeID'}

    # 3. Pixeldrain jika ada
    pd_m = re.findall(r'https?://(?:www\.)?pixeldrain\.com/(?:u|d)/([a-zA-Z0-9_-]+)', ep_html)
    for file_id in pd_m:
        if '720p' not in qualities:
            qualities['720p'] = {'url': f"https://pixeldrain.com/api/file/{file_id}?download", 'host': 'Pixeldrain', 'source': 'NontonAnimeID'}

    return qualities

async def extract_qualities_from_samehadaku(session: aiohttp.ClientSession, episode_url: str) -> dict:
    """Ekstrak resolusi video dari episode Samehadaku (Mendukung MP4, MKV, Acefile, Pixeldrain direct dengan backup otomatis)."""
    status, ep_html = await fetch_html_stealth(session, episode_url)
    if status != 200 or not ep_html:
        return {}

    qualities = {}
    li_blocks = re.findall(r'<li[^>]*>\s*<strong>(.*?)</strong>([\s\S]*?)</li>', ep_html)
    for q_str, links_html in li_blocks:
        clean_tag = re.sub(r'<[^>]+>', '', q_str).strip()
        q_key = None
        if re.search(r'FULLHD|1080p', clean_tag, re.I):
            q_key = '1080p'
        elif re.search(r'MP4HD|720p', clean_tag, re.I):
            q_key = '720p'
        elif re.search(r'480p', clean_tag, re.I):
            q_key = '480p'
        elif re.search(r'360p', clean_tag, re.I):
            q_key = '360p'

        if not q_key:
            continue

        is_x265 = bool(re.search(r'x265|hevc', clean_tag, re.I))

        # Ekstrak tautan Acefile, Pixeldrain, dan Gofile
        af_links = re.findall(r'href="(https?://acefile\.co/f/[^"]+)"', links_html)
        pd_ids = re.findall(r'href="https?://pixeldrain\.com/(?:u|d)/([a-zA-Z0-9_-]+)"', links_html)
        pd_links = [f"https://pixeldrain.com/api/file/{fid}?download" for fid in pd_ids]
        gf_links = re.findall(r'href="(https?://gofile\.io/d/[a-zA-Z0-9_-]+)"', links_html)

        if not af_links and not pd_links and not gf_links:
            continue

        is_mp4 = bool(re.search(r'mp4', clean_tag, re.I)) or ('FULLHD' in clean_tag or 'MP4HD' in clean_tag)

        if af_links:
            primary_url = af_links[0]
            primary_host = 'Acefile'
            backup_candidates = pd_links + gf_links
        elif pd_links:
            primary_url = pd_links[0]
            primary_host = 'Pixeldrain'
            backup_candidates = pd_links[1:] + gf_links
        else:
            primary_url = gf_links[0]
            primary_host = 'Gofile'
            backup_candidates = gf_links[1:]

        entry = {
            'url': primary_url,
            'host': primary_host,
            'source': 'Samehadaku',
            'is_x265': is_x265,
            'backup_urls': list(dict.fromkeys(backup_candidates))
        }

        if q_key not in qualities:
            qualities[q_key] = entry
        else:
            existing = qualities[q_key]
            # Prioritas: Format MP4 selalu lebih diutamakan daripada MKV untuk web streaming
            if is_mp4:
                if existing.get('url') and existing['url'] != entry['url']:
                    entry.setdefault('backup_urls', []).append(existing['url'])
                if existing.get('backup_urls'):
                    entry.setdefault('backup_urls', []).extend(existing['backup_urls'])
                entry['backup_urls'] = list(dict.fromkeys(entry['backup_urls']))
                qualities[q_key] = entry
            else:
                if entry['url'] != existing.get('url'):
                    existing.setdefault('backup_urls', []).append(entry['url'])
                if entry.get('backup_urls'):
                    existing.setdefault('backup_urls', []).extend(entry['backup_urls'])
                existing['backup_urls'] = list(dict.fromkeys(existing['backup_urls']))

    return qualities

async def extract_qualities_from_oploverz(session: aiohttp.ClientSession, episode_url: str) -> dict:
    """Ekstrak resolusi video dari episode Oploverz (Acefile / Pixeldrain)."""
    status, ep_html = await fetch_html_stealth(session, episode_url)
    if status != 200 or not ep_html:
        return {}

    qualities = {}
    af_links = re.findall(r'href="(https?://acefile\.co/f/[^"]+)"', ep_html)
    for url in af_links:
        qm = re.search(r'(1080|720|480|360)p?', url, re.I)
        if qm:
            q_key = f"{qm.group(1)}p"
            if q_key not in qualities:
                qualities[q_key] = {
                    'url': url,
                    'host': 'Acefile',
                    'source': 'Oploverz'
                }

    pd_links = re.findall(r'https?://pixeldrain\.com/(?:u|d)/([a-zA-Z0-9_-]+)', ep_html)
    for fid in pd_links:
        if '720p' not in qualities:
            qualities['720p'] = {
                'url': f"https://pixeldrain.com/api/file/{fid}?download",
                'host': 'Pixeldrain',
                'source': 'Oploverz'
            }

    return qualities

async def extract_qualities_from_otakudesu(session: aiohttp.ClientSession, anime_or_ep_url: str, ep_num: int = None) -> dict:
    """Ekstrak resolusi video dari Otakudesu (Acefile / Pixeldrain / link.desustream.com)."""
    target_url = anime_or_ep_url
    status, html_c = await fetch_html_stealth(session, target_url)
    if status != 200 or not html_c:
        return {}

    if '/anime/' in target_url:
        ep_links = re.findall(r'<a\s+href="(https?://[^"]*otakudesu[^"]*/episode/[^"]+)"[^>]*>(.*?)</a>', html_c)
        for ep_href, ep_txt in ep_links:
            num_m = re.search(r'episode\s*(\d+)', ep_txt, re.I)
            if num_m and ep_num and int(num_m.group(1)) == ep_num:
                target_url = ep_href
                status, html_c = await fetch_html_stealth(session, target_url)
                break
        else:
            if ep_links and not ep_num:
                target_url = ep_links[0][0]
                status, html_c = await fetch_html_stealth(session, target_url)

    if status != 200 or not html_c:
        return {}

    qualities = {}
    for q in ['1080p', '720p', '480p', '360p']:
        m = re.search(rf'<strong>\s*{q}\s*</strong>(.*?)(?=</li>|</ul>)', html_c, re.DOTALL | re.I)
        if not m:
            pos = html_c.find(f">{q}<")
            if pos == -1: pos = html_c.find(q)
            snippet = html_c[pos:pos+700] if pos != -1 else ""
        else:
            snippet = m.group(1)

        if not snippet:
            continue

        # 1. Cek langsung acefile
        af_m = re.search(r'href="(https?://acefile\.co/f/[^"]+)"', snippet)
        pd_m = re.search(r'href="https?://pixeldrain\.com/(?:u|d)/([a-zA-Z0-9_-]+)"', snippet)
        pd_backup = [f"https://pixeldrain.com/api/file/{pd_m.group(1)}?download"] if pd_m else []

        if af_m:
            qualities[q] = {'url': af_m.group(1), 'host': 'Acefile', 'source': 'Otakudesu', 'backup_urls': pd_backup}
            continue

        # 2. Cek langsung pixeldrain
        if pd_m:
            fid = pd_m.group(1)
            qualities[q] = {'url': f"https://pixeldrain.com/api/file/{fid}?download", 'host': 'Pixeldrain', 'source': 'Otakudesu'}
            continue

        # 3. Cek link.desustream.com wrapper (Prioritas Cepat: OtakuDrive / DesuDrive / AceFile -> Mega -> PDrain)
        desu_matches = re.findall(r'href="(https?://link\.desustream\.com/\?id=[^"]+)"[^>]*>([^<]+)</a>', snippet)
        
        # Pass 1: Cek OtakuDrive / DesuDrive / AceFile (Google Drive CDN super cepat)
        for d_url, d_name in desu_matches:
            dn = d_name.lower()
            if any(k in dn for k in ['otakudrive', 'desudrive', 'acefile', 'gdrive', 'sharer']):
                dl_url, host = await resolve_desustream_link(session, d_url)
                if dl_url and host:
                    qualities[q] = {'url': dl_url, 'host': host, 'source': 'Otakudesu'}
                    break
        if q in qualities:
            continue

        # Pass 2: Cek Mega
        for d_url, d_name in desu_matches:
            if 'mega' in d_name.lower():
                dl_url, host = await resolve_desustream_link(session, d_url)
                if dl_url and host:
                    qualities[q] = {'url': dl_url, 'host': host, 'source': 'Otakudesu'}
                    break
        if q in qualities:
            continue

        # Pass 3: Cek PDrain / Fallback lainnya
        for d_url, d_name in desu_matches:
            dl_url, host = await resolve_desustream_link(session, d_url)
            if dl_url and host:
                qualities[q] = {'url': dl_url, 'host': host, 'source': 'Otakudesu'}
                break

    return qualities

def host_priority(host: str) -> int:
    """Prioritas kecepatan server video (Kuramadrive CDN 14+ MB/s, Acefile/GoogleDrive 10-30+ MB/s vs Pixeldrain 1-3 MB/s)."""
    h = (host or '').lower()
    if any(k in h for k in ['kdrive', 'kuramadrive', 'kuramanime']):
        return 100  # Kuramadrive CDN Cloudflare R2 (14+ MB/s)
    if any(k in h for k in ['acefile', 'google', 'drive', 'gdrive', 'otakudrive', 'desudrive', 'kamado', 'kturbo']):
        return 95   # Acefile / Kamado / OtakuDrive Google Drive CDN (80-150+ MB/s di Colab, 10-30+ MB/s lokal)
    if any(k in h for k in ['proxy', 'kotakanime', 'kotakvideo']):
        return 75   # Nipnime Player Proxy (KotakAnime HLS 1080p / Kotakvideo MP4)
    if 'pixeldrain' in h:
        return 50   # Pixeldrain (1-3 MB/s)
    if 'mediafire' in h:
        return 35   # Mediafire
    if 'mp4upload' in h:
        return 30   # Mp4Upload (0.5 MB/s)
    return 10

def is_better_source(new_d: dict, old_d: dict) -> bool:
    """Mengecek apakah sumber baru memiliki kecepatan unduh yang jauh lebih tinggi."""
    if not isinstance(old_d, dict): return True
    if not isinstance(new_d, dict): return False
    return host_priority(new_d.get('host')) > host_priority(old_d.get('host'))

def ensure_ep_links_dict(raw_map) -> dict:
    if not raw_map:
        return {}
    if isinstance(raw_map, dict):
        return {str(k): v for k, v in raw_map.items()}
    if isinstance(raw_map, list):
        res = {}
        for idx, item in enumerate(raw_map, start=1):
            if isinstance(item, str):
                m = re.search(r'episode[_-](\d+)', item, re.I)
                ep_k = str(int(m.group(1))) if m else str(idx)
                if ep_k not in res:
                    res[ep_k] = item
            elif isinstance(item, dict):
                ep_k = str(item.get('number') or item.get('ep') or idx)
                if ep_k not in res:
                    res[ep_k] = item.get('url', '')
        return res
    return {}

async def check_episode_on_all_sources(session: aiohttp.ClientSession, anime_title: str, ep_num: int, extra_info: dict = None, skip_source: str = None) -> dict:
    """Mencari episode tertentu di ketiga sumber dengan memprioritaskan server CDN tercepat (Kuramadrive 14-40 MB/s)."""
    if is_worker_quarantined() or is_remotely_paused():
        return {}
    combined = {}
    search_kw = anime_title.split(':')[0].strip()

    # 0. JALUR SUPER CEPAT: Jika anime tamat sudah memiliki direct episode URL di ep_links_map!
    # Ekstrak dari Otakudesu. HANYA return langsung jika mendapatkan host CDN super cepat (Kuramadrive / Acefile)!
    # Jika hanya memiliki Pixeldrain (yang berpotensi lambat atau limit kuota 403), lanjutkan pencarian ke Samehadaku (Acefile) & Kuramanime!
    ep_map = ensure_ep_links_dict((extra_info or {}).get('ep_links_map'))
    known_ot_url = ep_map.get(str(ep_num))
    if known_ot_url and skip_source != 'Otakudesu':
        try:
            ot_q = await extract_qualities_from_otakudesu(session, known_ot_url, ep_num)
            for q, d in ot_q.items():
                combined[q] = d
            has_super_fast = any(d.get('host') in ('Kuramadrive', 'Acefile') for d in combined.values())
            if has_super_fast and ('720p' in combined or '1080p' in combined):
                src_details = ', '.join(f"{q}: {d.get('source', '')} ({d.get('host', '')})" for q, d in combined.items())
                log("SRC_FOUND", f"✓ Sumber CDN Super Cepat untuk {anime_title} Ep {ep_num} -> [{src_details}]", GREEN)
                return combined
        except Exception:
            pass

    # 0b. JALUR NIPNIME PLAYER PROXY: Jika episode_id sudah terdaftar di database Nipnime!
    target_ep_id = None
    if extra_info and extra_info.get('episode_id'):
        extra_ep_num = extra_info.get('episode_number')
        # VALIDASI KETAT: Hanya gunakan episode_id jika episode_number cocok dengan ep_num yang sedang dicari!
        # Mencegah bug episode_id dari episode baru tertukar saat backfill episode sebelumnya.
        if extra_ep_num is None or str(extra_ep_num).strip() == str(ep_num).strip():
            target_ep_id = extra_info.get('episode_id')

    if target_ep_id and API_URL:
        try:
            log("PLAYER_STREAM", f"⚡ Menghubungi Nipnime Player Proxy untuk Ep {ep_num} (ID: {target_ep_id})...", CYAN)
            async with PLAYER_STREAM_SEM:
                async with session.post(
                    f"{API_URL}/player-stream",
                    json={'episode_id': target_ep_id},
                    headers={'X-Terop-Token': WORKER_TOKEN, 'Content-Type': 'application/json'},
                    timeout=aiohttp.ClientTimeout(total=35)
                ) as pp_resp:
                    if pp_resp.status == 200:
                        pp_data = await pp_resp.json()
                        st_map = pp_data.get('streams') or {}
                        if st_map:
                            log("PLAYER_PROXY", f"⚡ Berhasil mendapatkan {len(st_map)} stream dari Nipnime Player Proxy ({', '.join(st_map.keys())})!", GREEN)
                        for q, s_info in st_map.items():
                            if q not in combined or is_better_source(s_info, combined[q]):
                                combined[q] = {
                                    'url': s_info.get('direct_url') or s_info['url'],
                                    'direct_url': s_info.get('direct_url'),
                                    'host': s_info.get('host', 'Nipnime-Proxy'),
                                    'source': s_info.get('source', 'NipnimePlayer'),
                                    'type': s_info.get('type', 'mp4'),
                                    'embed_url': s_info.get('embed_url')
                                }
        except Exception as e_pp:
            log("PLAYER_WARN", f"Query player-stream Nipnime gagal / timeout: {e_pp}", YELLOW)

    # 1. Coba Kuramanime TERLEBIH DAHULU (Kuramadrive Cloudflare R2 14-40 MB/s, SUMBER TERCEPAT & PALING NGEBUT!)
    if skip_source != 'Kuramanime':
        try:
            kura_queries = [search_kw]
            clean_kura = re.sub(r'\b(s\d+|season\s*\d+|musim\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b', '', search_kw, flags=re.I).strip()
            clean_kura = re.sub(r'\s+', ' ', clean_kura)
            if clean_kura and clean_kura not in kura_queries:
                kura_queries.append(clean_kura)

            words = clean_kura.split() if clean_kura else search_kw.split()
            if len(words) > 2:
                kura_queries.append(' '.join(words[:2]))
            if len(words) > 3:
                kura_queries.append(' '.join(words[:3]))
            kura_queries = list(dict.fromkeys(kura_queries))[:3]

            norm_target = normalize_title(anime_title)
            target_words = set(re.findall(r'[a-zA-Z0-9]+', norm_target))

            for kw in kura_queries:
                search_url = f"https://v20.kuramanime.ing/anime?search={quote(kw)}"
                status, html_content = await fetch_html_stealth(session, search_url)
                if status == 200 and html_content:
                    matches = re.findall(r'/anime/(\d+)/([a-zA-Z0-9-]+)', html_content)
                    scored_candidates = []
                    for aid, slug in matches:
                        # VALIDASI SEASON: Mencegah Season 1 masuk ke Season 2 atau sebaliknya
                        if not is_season_match(anime_title, slug):
                            continue
                        slug_norm = slug.replace('-', ' ')
                        slug_words = set(re.findall(r'[a-zA-Z0-9]+', slug_norm))
                        common = target_words & slug_words
                        overlap = len(common) / max(1, len(target_words))
                        sim = difflib.SequenceMatcher(None, slug_norm, norm_target).ratio()
                        score = max(overlap, sim)
                        if score >= 0.45:
                            scored_candidates.append((score, aid, slug))

                    if scored_candidates:
                        # Pilih anime dengan skor kecocokan judul tertinggi yang season-nya cocok
                        scored_candidates.sort(key=lambda x: x[0], reverse=True)
                        best_score, aid, slug = scored_candidates[0]
                        ep_url = f"https://v20.kuramanime.ing/anime/{aid}/{slug}/episode/{ep_num}"
                        k_q = await extract_qualities_from_kuramanime(session, ep_url)
                        for q, d in k_q.items():
                            if q not in combined or combined[q].get('source') == skip_source or is_better_source(d, combined[q]):
                                combined[q] = d
                        if k_q:
                            break
        except Exception:
            pass

    # 2. Coba AnimeSail KEDUA (Untuk melengkapi resolusi lain yang belum ada di Kuramanime, misal 1080p Pixeldrain)
    if skip_source != 'AnimeSail':
        try:
            as_queries = [search_kw]
            clean_as = re.sub(r'\b(s\d+|season\s*\d+|musim\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b', '', search_kw, flags=re.I).strip()
            clean_as = re.sub(r'\s+', ' ', clean_as)
            if clean_as and clean_as not in as_queries:
                as_queries.append(clean_as)
            words_as = clean_as.split() if clean_as else search_kw.split()
            if len(words_as) > 2:
                as_queries.append(' '.join(words_as[:2]))
            as_queries = list(dict.fromkeys(as_queries))[:3]

            for akw in as_queries:
                search_url = f"https://v1.animesail.xyz/?s={quote(akw)}"
                status, html_content = await fetch_html_stealth(session, search_url)
                if status == 200 and html_content:
                    bsx_matches = re.findall(r'<div class="bsx">\s*<a\s+href="([^"]+)"[^>]*title="([^"]*)"', html_content)
                    if not bsx_matches:
                        bsx_matches = [(m, "") for m in re.findall(r'<div class="bsx">\s*<a\s+href="([^"]+)"', html_content)]
                    scored_as = []
                    for u, t in bsx_matches:
                        slug = u.rstrip('/').split('/')[-1]
                        slug_text = (t or slug).replace('-', ' ')
                        if not is_season_match(anime_title, slug_text):
                            continue
                        sim = difflib.SequenceMatcher(None, normalize_title(slug_text), norm_target).ratio()
                        if sim >= 0.45:
                            scored_as.append((sim, slug))
                    if scored_as:
                        scored_as.sort(key=lambda x: x[0], reverse=True)
                        best_slug = scored_as[0][1]
                        ep_url = f"https://v1.animesail.xyz/{best_slug}-episode-{ep_num}/"
                        as_q = await extract_qualities_from_animesail(session, ep_url, extra_info=extra_info)
                        for q, d in as_q.items():
                            if q not in combined or is_better_source(d, combined[q]):
                                combined[q] = d
                        if as_q:
                            break
        except Exception:
            pass

    # 3. Coba NontonAnimeID KETIGA
    if skip_source != 'NontonAnimeID':
        try:
            na_slug = (extra_info or {}).get('nontonanimeid_slug')
            if not na_slug:
                clean_t = normalize_title(anime_title).replace(' ', '-')
                na_slug = clean_t
            if is_season_match(anime_title, na_slug):
                ep_url = f"https://s13.nontonanimeid.boats/{na_slug}-episode-{ep_num}/"
                na_q = await extract_qualities_from_nontonanimeid(session, ep_url, extra_info=extra_info)
                for q, d in na_q.items():
                    if q not in combined or combined[q].get('source') == skip_source or is_better_source(d, combined[q]):
                        combined[q] = d
        except Exception:
            pass

    # 4. Coba Samehadaku KEEMPAT (Acefile Google Drive CDN 10-30+ MB/s & Pixeldrain)
    if skip_source != 'Samehadaku':
        try:
            sm_queries = [search_kw]
            clean_kw = re.sub(r'[^a-zA-Z0-9\s]', ' ', search_kw).strip()
            clean_kw = re.sub(r'\s+', ' ', clean_kw)
            if clean_kw and clean_kw not in sm_queries:
                sm_queries.append(clean_kw)
            s_clean = re.sub(r'(\d+)(?:st|nd|rd|th)\s+season', r'season \1', clean_kw, flags=re.I)
            if s_clean and s_clean not in sm_queries:
                sm_queries.append(s_clean)
            words = clean_kw.split()
            if len(words) > 3:
                sm_queries.append(' '.join(words[:4]))
                sm_queries.append(' '.join(words[:3]))
            sm_queries = list(dict.fromkeys(sm_queries))[:3]

            for kw in sm_queries:
                search_url = f"https://v2.samehadaku.how/?s={quote(kw)}"
                status, html_content = await fetch_html_stealth(session, search_url)
                if status == 200 and html_content:
                    arts = re.findall(r'<article[^>]*>([\s\S]*?)</article>', html_content)
                    found_sm = False
                    for art in arts:
                        m = re.search(r'href="([^"]+)"[^>]*title="([^"]*)"', art) or re.search(r'href="([^"]+)"', art)
                        if m:
                            u = m.group(1)
                            t = m.group(2) if len(m.groups()) > 1 else ""
                            if 'batch' in u.lower() or 'batch' in t.lower():
                                continue
                            # Validasi kesesuaian season artikel
                            if not is_season_match(anime_title, f"{t} {u}"):
                                continue
                            ep_m = re.search(r'episode[_-](\d+)', u, re.I) or re.search(r'episode\s*(\d+)', t, re.I)
                            if ep_m and int(ep_m.group(1)) == ep_num:
                                sm_q = await extract_qualities_from_samehadaku(session, u)
                                for q, d in sm_q.items():
                                    if q not in combined or is_better_source(d, combined[q]):
                                        if q in combined and d['url'] != combined[q]['url']:
                                            d.setdefault('backup_urls', []).append(combined[q]['url'])
                                            if 'backup_urls' in combined[q]:
                                                d['backup_urls'].extend(combined[q]['backup_urls'])
                                        combined[q] = d
                                found_sm = True
                                break
                    if found_sm:
                        break
        except Exception:
            pass

    # 5. Coba Oploverz KELIMA (Acefile / Pixeldrain)
    if skip_source != 'Oploverz':
        try:
            op_slug = normalize_title(anime_title).replace(' ', '-')
            if is_season_match(anime_title, op_slug):
                ep_url = f"https://oploverz.site/series/{op_slug}/episode/{ep_num}"
                op_q = await extract_qualities_from_oploverz(session, ep_url)
                for q, d in op_q.items():
                    if q not in combined or is_better_source(d, combined[q]):
                        combined[q] = d
        except Exception:
            pass

    # 6. Coba Otakudesu KEENAM (Acefile / Pixeldrain / link.desustream)
    if skip_source != 'Otakudesu':
        try:
            ot_ep_map = ensure_ep_links_dict((extra_info or {}).get('ep_links_map'))
            ot_ep_url = ot_ep_map.get(str(ep_num))
            if ot_ep_url and not combined:
                if is_season_match(anime_title, ot_ep_url):
                    ot_q = await extract_qualities_from_otakudesu(session, ot_ep_url, ep_num)
                    for q, d in ot_q.items():
                        if q not in combined or is_better_source(d, combined[q]):
                            combined[q] = d
            if not combined or not any(k in combined for k in ['1080p', '720p']):
                ot_queries = [search_kw]
                words = search_kw.split()
                if len(words) > 3:
                    ot_queries.append(' '.join(words[:3]))
                ot_queries = list(dict.fromkeys(ot_queries))[:2]

                for kw in ot_queries:
                    search_url = f"https://otakudesu.blog/?s={quote(kw)}&post_type=anime"
                    status, html_content = await fetch_html_stealth(session, search_url)
                    if status == 200 and html_content:
                        a_matches = re.findall(r'<a[^>]*href="(https?://[^"]*otakudesu[^"]*/anime/[^"]+)"[^>]*>', html_content)
                        found_ot = False
                        for a_url in a_matches[:5]:
                            # Validasi kesesuaian season URL Otakudesu
                            if not is_season_match(anime_title, a_url):
                                continue
                            ot_q = await extract_qualities_from_otakudesu(session, a_url, ep_num)
                            for q, d in ot_q.items():
                                if q not in combined or is_better_source(d, combined[q]):
                                    combined[q] = d
                            if ot_q:
                                found_ot = True
                                break
                        if found_ot:
                            break
        except Exception:
            pass

    if combined:
        src_details = ', '.join(f"{q}: {d.get('source', '')} ({d.get('host', '')})" for q, d in combined.items())
        log("SRC_FOUND", f"✓ Sumber untuk {anime_title} Ep {ep_num} -> [{src_details}]", GREEN)

    return combined

# ==============================================================================
# 3. DOWNLOADER & TELEGRAM UPLOADER
# ==============================================================================
async def download_chunk_worker(url: str, headers: dict, start: int, end: int, part_file: Path, state_ref: dict) -> bool:
    """Worker untuk mengunduh potongan file video secara paralel (multi-connection range request)."""
    part_headers = dict(headers)
    part_headers['Range'] = f"bytes={start}-{end}"
    timeout = aiohttp.ClientTimeout(total=900, connect=8.0, sock_connect=8.0, sock_read=25.0)
    is_colab = get_device_role() in CLOUD_ROLES
    buf_size = 1024 * 1024 if is_colab else 1024 * 512
    chunk_size = 1024 * 256 if is_colab else 1024 * 128
    try:
        async with aiohttp.ClientSession(headers=part_headers, timeout=timeout, read_bufsize=buf_size) as session:
            async with session.get(url) as resp:
                if resp.status not in (200, 206):
                    return False
                with open(part_file, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(chunk_size):
                        if state_ref.get('aborted_slow'):
                            return False
                        if not chunk: break
                        f.write(chunk)
                        state_ref['downloaded'] += len(chunk)
                        state_ref['last_chunk_time'] = time.time()
                return True
    except asyncio.CancelledError:
        return False
    except Exception:
        return False

PIXELDRAIN_SEMAPHORE = asyncio.Semaphore(48)
PLAYER_STREAM_SEM = asyncio.Semaphore(2)

async def download_hls_stream(url: str, dest_path: Path, quality: str) -> bool:
    dl_task_key = dest_path.name
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix('.tmp.mp4')
    chunks_dir = dest_path.parent / f"_hls_tmp_{dest_path.stem[:35]}_{int(time.time()*1000)}"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    log("HLS_DOWNLOAD", f"⚡ Mengunduh HLS [{quality}] via Parallel Segment Engine (16x Turbo): {url[:60]}...", CYAN)
    PROGRESS_MGR.update(
        key=dl_task_key,
        label=f"[{quality}] {dest_path.name}",
        cur_mb=0.0,
        tot_mb=0.0,
        speed_mb=0.0,
        eta_str="",
        status_text="Menganalisis playlist HLS..."
    )

    start_time = time.time()
    try:
        timeout = aiohttp.ClientTimeout(total=45, connect=10)
        connector = aiohttp.TCPConnector(limit=32, limit_per_host=16, ttl_dns_cache=300, ssl=False)

        target_m3u8 = url
        direct_headers = {
            'User-Agent': DEFAULT_UA,
            'Accept': '*/*'
        }
        role = get_device_role()
        server_p = 's1'

        # Unwrap link proxy Nipnime agar Colab / Worker langsung unduh ke CDN sumber (0 Beban Bandwidth Indihome!)
        if 'hls-manifest' in target_m3u8 and 'url=' in target_m3u8:
            try:
                pq = parse_qs(urlparse(target_m3u8).query)
                direct_u = pq.get('url', [None])[0]
                server_p = pq.get('server', ['s1'])[0]
                if direct_u:
                    target_m3u8 = direct_u
            except Exception:
                pass

        # Header wajib KotakAnime CDN agar tidak loop / 403
        if 'kotakanimeid.link' in target_m3u8 or 'kotakanime' in target_m3u8 or 'kotakanimeid.link' in url:
            direct_headers['Origin'] = f'https://{server_p}.kotakanimeid.link'
            direct_headers['Referer'] = f'https://{server_p}.kotakanimeid.link/'
            log("HLS_DIRECT", f"⚡ Menghubungkan HLS [{quality}] LANGSUNG dari {role.upper()} ke CDN KotakAnime ({server_p}) [0 Indihome]...", CYAN)

        async def _fetch_playlist_text(m_url: str, session: aiohttp.ClientSession) -> str:
            # 1. Gunakan curl_cffi stealth dengan Chrome TLS fingerprint (Wajib untuk Colab agar lolos Cloudflare)
            if HAS_CURL_CFFI and m_url.startswith('http'):
                try:
                    def _c_req():
                        return c_requests.get(
                            m_url,
                            headers=direct_headers,
                            impersonate="chrome120",
                            timeout=12,
                            verify=False
                        )
                    c_resp = await asyncio.to_thread(_c_req)
                    if c_resp.status_code == 200 and '#EXTM3U' in c_resp.text:
                        return c_resp.text
                except Exception:
                    pass

            # 2. Coba via aiohttp langsung
            try:
                async with session.get(m_url, headers=direct_headers, ssl=False, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        txt = await r.text()
                        if '#EXTM3U' in txt:
                            return txt
            except Exception:
                pass

            # 3. Fallback: Ambil teks manifest via proxy Nipnime
            if m_url != url:
                try:
                    proxy_manifest = f"{STREAM_BASE_URL.replace('/tg-stream', '')}/api/video/proxy/hls-manifest?url={quote(m_url)}&server={server_p}"
                    async with session.get(proxy_manifest, headers={'User-Agent': DEFAULT_UA}, timeout=aiohttp.ClientTimeout(total=15)) as fb_r:
                        if fb_r.status == 200:
                            txt = await fb_r.text()
                            if '#EXTM3U' in txt:
                                return txt
                except Exception:
                    pass

            return ""

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # 1. Unduh manifest utama
            m_text = await _fetch_playlist_text(target_m3u8, session)
            if not m_text and target_m3u8 != url:
                m_text = await _fetch_playlist_text(url, session)

            if not m_text:
                log("HLS_ERR", f"Gagal mengambil manifest HLS [{quality}]!", YELLOW)
                return False

            # 2. Cek apakah ini master playlist dengan resolusi bersarang
            if '#EXT-X-STREAM-INF' in m_text:
                m_lines = [l.strip() for l in m_text.splitlines() if l.strip()]
                matched_url = None
                fallback_url = None
                for i, l in enumerate(m_lines):
                    if l.startswith('#EXT-X-STREAM-INF'):
                        sub_url = m_lines[i + 1] if i + 1 < len(m_lines) else None
                        if sub_url and not sub_url.startswith('#'):
                            if not sub_url.startswith('http'):
                                sub_url = urljoin(target_m3u8, sub_url)
                            fallback_url = sub_url
                            if quality.lower().replace('p', '') in l.lower() or quality.lower().replace('p', '') in sub_url.lower():
                                matched_url = sub_url
                chosen_url = matched_url or fallback_url
                if chosen_url:
                    target_m3u8 = chosen_url
                    sub_text = await _fetch_playlist_text(target_m3u8, session)
                    if sub_text:
                        m_text = sub_text

            # 3. Parse semua URL segmen .ts
            lines = [l.strip() for l in m_text.splitlines() if l.strip()]
            segment_pairs = []
            durations = []
            cur_dur = 10.0
            has_extinf = False
            for l in lines:
                if l.startswith('#EXTINF:'):
                    try:
                        dur_match = re.search(r'#EXTINF:([\d.]+)', l)
                        if dur_match:
                            cur_dur = float(dur_match.group(1))
                    except Exception:
                        cur_dur = 10.0
                    has_extinf = True
                elif not l.startswith('#') and has_extinf:
                    has_extinf = False
                    orig_seg = l
                    direct_seg = None
                    # Selalu unwrap segmen proxy kembali ke direct CDN sumber (0 Beban Indihome!)
                    if 'hls-segment' in orig_seg and 'url=' in orig_seg:
                        try:
                            direct_seg = parse_qs(urlparse(orig_seg).query).get('url', [None])[0]
                        except Exception:
                            pass
                    if not orig_seg.startswith('http'):
                        orig_seg = urljoin(target_m3u8, orig_seg)
                    if direct_seg and not direct_seg.startswith('http'):
                        direct_seg = urljoin(target_m3u8, direct_seg)
                    
                    real_direct = direct_seg or orig_seg
                    proxy_fallback = f"{STREAM_BASE_URL.replace('/tg-stream', '')}/api/video/proxy/hls-segment?url={quote(real_direct)}&server={server_p}"
                    segment_pairs.append((real_direct, proxy_fallback))
                    durations.append(cur_dur)

            total_segments = len(segment_pairs)
            if total_segments == 0:
                log("HLS_ERR", f"Tidak ada segmen video ditemukan dalam manifest [{quality}]!", YELLOW)
                return False

            tot_duration = sum(durations) if durations else total_segments * 10.0
            log("HLS_INFO", f"✓ Ditemukan {total_segments} segmen video (~{tot_duration/60:.1f} mnt). Mengunduh langsung dari CDN KotakAnime...", CYAN)

            # 4. Unduh segmen secara paralel (16x koneksi simultan langsung ke CDN)
            sem = asyncio.Semaphore(16)
            downloaded_bytes = 0
            completed_count = 0
            seg_files = [chunks_dir / f"seg_{i:05d}.ts" for i in range(total_segments)]

            # Header segmen WAJIB membawa Origin & Referer agar CDN2 KotakAnime tidak 403!
            seg_headers = {
                'User-Agent': DEFAULT_UA,
                'Origin': f'https://{server_p}.kotakanimeid.link',
                'Referer': f'https://{server_p}.kotakanimeid.link/',
                'Accept': '*/*'
            }

            has_logged_fallback = False

            async def dl_segment(idx, seg_pair):
                nonlocal downloaded_bytes, completed_count, has_logged_fallback
                s_file = seg_files[idx]
                direct_u, proxy_u = seg_pair
                use_proxy = False

                for attempt in range(4):
                    curr_u = proxy_u if use_proxy else direct_u
                    req_h = seg_headers if not use_proxy else {'User-Agent': DEFAULT_UA, 'Accept': '*/*'}
                    try:
                        async with sem:
                            async with session.get(curr_u, headers=req_h, ssl=False, timeout=aiohttp.ClientTimeout(total=30)) as r:
                                if r.status == 200:
                                    data = await r.read()
                                    if len(data) > 0:
                                        with open(s_file, "wb") as f:
                                            f.write(data)
                                        downloaded_bytes += len(data)
                                        completed_count += 1

                                        # Update UI progress
                                        el = max(0.1, time.time() - start_time)
                                        cur_mb = downloaded_bytes / (1024 * 1024)
                                        sp = cur_mb / el
                                        est_tot_mb = (cur_mb / completed_count) * total_segments if completed_count >= 3 else 0.0
                                        rem_mb = max(0.0, est_tot_mb - cur_mb)
                                        eta_sec = int(rem_mb / sp) if sp > 0.05 and est_tot_mb > 0 else 0
                                        eta_str = f"{eta_sec//60:02d}:{eta_sec%60:02d}" if eta_sec > 0 else ""

                                        PROGRESS_MGR.update(
                                            key=dl_task_key,
                                            label=f"[{quality}] {dest_path.name}",
                                            cur_mb=cur_mb,
                                            tot_mb=est_tot_mb,
                                            speed_mb=sp,
                                            eta_str=eta_str,
                                            status_text=f"Segmen {completed_count}/{total_segments} ({sp:.1f}MB/s)"
                                        )
                                        return True
                                elif r.status in (403, 404, 410) and not use_proxy:
                                    if not has_logged_fallback:
                                        has_logged_fallback = True
                                        log("HLS_FALLBACK", f"⚡ Direct CDN ditolak (HTTP {r.status}). Mengunduh segmen via Nipnime Stream Proxy...", YELLOW)
                                    use_proxy = True
                                    continue
                    except Exception as e_seg:
                        if not use_proxy:
                            if not has_logged_fallback:
                                has_logged_fallback = True
                                log("HLS_FALLBACK", f"⚡ Direct CDN timeout/error ({e_seg}). Mengunduh segmen via Nipnime Stream Proxy...", YELLOW)
                            use_proxy = True
                        await asyncio.sleep(0.3 * (attempt + 1))
                return False

            tasks = [dl_segment(i, p) for i, p in enumerate(segment_pairs)]
            results = await asyncio.gather(*tasks)

        success_count = sum(1 for r in results if r)
        if success_count < total_segments * 0.95:
            log("HLS_WARN", f"Segmen paralel tidak lengkap ({success_count}/{total_segments}), mencoba fallback FFmpeg native...", YELLOW)
            shutil.rmtree(chunks_dir, ignore_errors=True)
            ff_headers = f'User-Agent: {DEFAULT_UA}\r\n'
            if 'kotakanimeid.link' in target_m3u8 or 'kotakanime' in target_m3u8 or 'kotakanimeid.link' in url:
                ff_headers += f'Origin: https://{server_p}.kotakanimeid.link\r\nReferer: https://{server_p}.kotakanimeid.link/\r\n'
            cmd_ff = [
                FFMPEG_PATH,
                '-y',
                '-loglevel', 'error',
                '-headers', ff_headers,
                '-i', target_m3u8,
                '-c', 'copy',
                '-bsf:a', 'aac_adtstoasc',
                str(tmp_path)
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd_ff,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=300)
            except asyncio.TimeoutError:
                try: proc.kill()
                except Exception: pass
                log("HLS_ERR", f"FFmpeg fallback timeout (5 menit).", RED)
                return False

            if proc.returncode == 0 and tmp_path.exists() and tmp_path.stat().st_size > 5 * 1024 * 1024:
                if dest_path.exists(): dest_path.unlink()
                tmp_path.rename(dest_path)
                f_size = dest_path.stat().st_size / (1024 * 1024)
                log("DONE", f"Selesai [{quality} - FFmpeg Native]: {dest_path.name} ({f_size:.1f} MB)", GREEN)
                return True
            log("HLS_ERR", f"Terlalu banyak segmen gagal ({success_count}/{total_segments} berhasil).", RED)
            return False

        # 5. Gabungkan segmen menjadi satu file MP4 (lossless stream copy muxing)
        concat_list = chunks_dir / "concat_list.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for s_file in seg_files:
                if s_file.exists():
                    f.write(f"file '{s_file.name}'\n")

        cmd = [
            FFMPEG_PATH,
            '-y',
            '-loglevel', 'error',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(concat_list),
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            str(tmp_path)
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(chunks_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            try: proc.kill()
            except Exception: pass
            log("HLS_ERR", "FFmpeg concat timeout (3 menit).", RED)
            return False

        if proc.returncode != 0:
            err_msg = stderr.decode('utf-8', errors='ignore').strip()
            log("HLS_WARN", f"FFmpeg concat warning: {err_msg[:100]}. Fallback direct concat...", YELLOW)
            with open(tmp_path, "wb") as f_out:
                for s_file in seg_files:
                    if s_file.exists():
                        with open(s_file, "rb") as f_in:
                            shutil.copyfileobj(f_in, f_out)

        if tmp_path.exists() and tmp_path.stat().st_size / (1024 * 1024) >= 2.0:
            if dest_path.exists():
                try: dest_path.unlink()
                except Exception: pass
            tmp_path.rename(dest_path)
            f_size = dest_path.stat().st_size / (1024 * 1024)
            el = max(0.1, time.time() - start_time)
            avg_sp = f_size / el
            log("DONE", f"Selesai [{quality} - HLS Parallel 16x]: {dest_path.name} ({f_size:.1f} MB) dalam {el:.1f}s @ {avg_sp:.2f} MB/s!", GREEN)
            return True

        return False

    except Exception as e:
        log("ERROR", f"Gagal mengunduh HLS parallel: {e}", RED)
        return False
    finally:
        PROGRESS_MGR.remove(dl_task_key)
        shutil.rmtree(chunks_dir, ignore_errors=True)
        if tmp_path.exists():
            try: tmp_path.unlink()
            except Exception: pass

async def _download_single_stream_url(url: str, dest_path: Path, quality: str, min_speed_mb: float = 0.8) -> bool:
    if get_device_role() == "server" and has_active_remote_workers():
        return False
    dl_task_key = dest_path.name
    url = html.unescape(url).strip()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix('.tmp')

    # 0a. Unduhan HLS stream (.m3u8 / hls-manifest) via FFmpeg
    if 'hls-manifest' in url or '.m3u8' in url:
        return await download_hls_stream(url, dest_path, quality)

    # 0. Resolusi tautan Acefile ke Google Drive CDN langsung
    gdrive_cookie = None
    if 'acefile.co' in url:
        log("ACEFILE", f"⚡ Mengurai tautan Acefile [{quality}] ke Google Drive CDN super cepat...", CYAN)
        direct_gdrive, gdrive_cookie = await asyncio.to_thread(resolve_acefile_to_direct, url)
        if direct_gdrive:
            url = direct_gdrive
            log("ACEFILE", f"✓ Berhasil terhubung ke Google Drive CDN! Mulai unduh...", GREEN)
        else:
            log("ACEFILE_WARN", f"Tautan Acefile [{quality}] gagal di-resolve / kuota penuh. Beralih ke sumber cadangan...", YELLOW)
            return False

    # 0b. Resolusi tautan Gofile ke direct stream via Puppeteer
    gofile_cookie = None
    if 'gofile.io' in url:
        log("GOFILE", f"⚡ Mengurai tautan Gofile [{quality}] via Puppeteer microservice...", CYAN)
        direct_gofile, gofile_cookie = await asyncio.to_thread(resolve_gofile_to_direct, url)
        if direct_gofile:
            url = direct_gofile
            log("GOFILE", f"✓ Berhasil mendapatkan Gofile direct stream link! Mulai unduh...", GREEN)
        else:
            log("GOFILE_WARN", f"Tautan Gofile [{quality}] gagal di-resolve. Beralih ke sumber cadangan...", YELLOW)
            return False

    orig_stream_url = url
    # 0c. Resolusi stream KotakAnime / Google Video langsung ke CDN sumber (Bypass CasaOS Proxy, 0 Beban Bandwidth Indihome!)
    kotak_cookie = None
    kotak_origin = None
    if 'kotakanimeid-stream' in url:
        try:
            pq = parse_qs(urlparse(url).query)
            b64_url = pq.get('url', [None])[0]
            b64_cookie = pq.get('cookie', [None])[0]
            b64_godl = pq.get('godl', [None])[0]
            server_p = pq.get('server', ['s1'])[0]
            cookie_str = base64.b64decode(b64_cookie).decode('utf-8') if b64_cookie else ""
            kotak_origin = f"https://{server_p}.kotakanimeid.link"
            if cookie_str:
                kotak_cookie = cookie_str

            resolved_from_godl = False
            # Jika ada endpoint go/dl, resolve langsung dari IP Colab/Laptop!
            # Ini menghasilkan tautan Google Video yang terikat ke IP Colab/Laptop (Bypass 403 & 0 Beban Indihome!)
            if b64_godl and HAS_CURL_CFFI:
                try:
                    godl_u = base64.b64decode(b64_godl).decode('utf-8')
                    log("KOTAK_RESOLVE", f"⚡ Mengurai tautan Google Video langsung dari IP {get_device_role().upper()} (0 Beban Indihome)...", CYAN)
                    r_godl = c_requests.get(
                        godl_u,
                        headers={
                            'Host': f"{server_p}.kotakanimeid.link",
                            'User-Agent': DEFAULT_UA,
                            'Referer': f"https://{server_p}.kotakanimeid.link/",
                            'Cookie': cookie_str,
                        },
                        allow_redirects=False,
                        verify=False,
                        timeout=10,
                        impersonate="chrome120"
                    )
                    fresh_loc = r_godl.headers.get('Location') or r_godl.headers.get('location')
                    if fresh_loc and ('googlevideo.com' in fresh_loc or '.mp4' in fresh_loc or 'videoplayback' in fresh_loc):
                        url = fresh_loc
                        resolved_from_godl = True
                        log("KOTAK_DIRECT", f"✓ Berhasil mendapatkan tautan Google Video terikat ke IP {get_device_role().upper()}! Mengunduh langsung...", GREEN)
                except Exception as e_gl:
                    log("KOTAK_WARN", f"Gagal resolve go/dl ({e_gl}), menggunakan tautan default...", YELLOW)

            if not resolved_from_godl and b64_url:
                direct_u = base64.b64decode(b64_url).decode('utf-8')
                log("KOTAK_DIRECT", f"⚡ Menghubungkan [{quality}] LANGSUNG dari {get_device_role().upper()} ke CDN KotakAnime / Video ({server_p}) [0 Indihome]...", CYAN)
                url = direct_u
        except Exception:
            pass

    # 0d. Resolusi stream Mp4Upload langsung ke CDN sumber (Bypass CasaOS Proxy)
    if 'mp4upload-stream' in url:
        try:
            pq = parse_qs(urlparse(url).query)
            b64_url = pq.get('url', [None])[0]
            if b64_url:
                direct_u = base64.b64decode(b64_url).decode('utf-8')
                log("MP4UPLOAD_DIRECT", f"⚡ Menghubungkan [{quality}] LANGSUNG dari Colab ke CDN Mp4Upload...", CYAN)
                url = direct_u
        except Exception:
            pass

    # 0e. Resolusi proxy/external (Kamado / Google Drive) langsung ke direct URL
    if 'proxy/external' in url:
        try:
            pq = parse_qs(urlparse(url).query)
            raw_u = pq.get('url', [None])[0]
            if raw_u:
                url = unquote(raw_u)
        except Exception:
            pass

    # 0f. Google Drive API (KamadoDrive): Ekstrak access_token ke Header Authorization: Bearer
    # Google API memblokir parameter query access_token (HTTP 403), wajib Authorization Bearer Header!
    google_bearer = None
    if 'googleapis.com' in url or '/drive/v3/files/' in url:
        try:
            parsed_g = urlparse(url)
            g_qs = parse_qs(parsed_g.query)
            token_vals = g_qs.pop('access_token', None)
            if token_vals and token_vals[0]:
                google_bearer = token_vals[0]
                new_query = urlencode(g_qs, doseq=True)
                url = urlunparse((parsed_g.scheme, parsed_g.netloc, parsed_g.path, parsed_g.params, new_query, parsed_g.fragment))
                log("KAMADO_DIRECT", f"⚡ Menghubungkan [{quality}] LANGSUNG dari Colab ke Google Drive CDN (Bearer Auth)...", CYAN)
        except Exception:
            pass

    headers = {'User-Agent': DEFAULT_UA, 'Referer': url}
    if google_bearer:
        headers['Authorization'] = f"Bearer {google_bearer}"
        headers['Referer'] = 'https://drive.google.com/'
    if gdrive_cookie:
        headers['Cookie'] = gdrive_cookie
    if gofile_cookie:
        headers['Cookie'] = gofile_cookie
        headers['Referer'] = 'https://gofile.io/'
    if kotak_cookie:
        headers['Cookie'] = kotak_cookie
    if kotak_origin:
        headers['Origin'] = kotak_origin
        headers['Referer'] = f"{kotak_origin}/"
    if any(dead in url.lower() for dead in ['komi.my.id']):
        log("NOTICE", f"Tautan [{quality}] berasal dari mirror bermasalah/mati (komi.my.id). Melewati otomatis...", YELLOW)
        return False
    if 'pixeldrain.com' in url:
        headers['Referer'] = 'https://pixeldrain.com/'
    elif 'drive.usercontent.google.com' in url or 'drive.google.com' in url or 'googleapis.com' in url:
        headers['Referer'] = 'https://drive.google.com/'
        if gdrive_cookie:
            headers['Cookie'] = gdrive_cookie
    elif 'mp4upload.com' in url:
        headers['Referer'] = 'https://www.mp4upload.com/'
        min_speed_mb = min(min_speed_mb, 0.3)
    elif any(k in url.lower() for k in ['amiya', 'kdrive', 'kuramadrive', 'kuramanime']):
        headers['Referer'] = 'https://v20.kuramanime.ing/'
    elif 'tg-stream' in url or 'nipnime.com' in url:
        headers['Referer'] = 'https://nipnime.com/'

    log("DOWNLOAD", f"Mengunduh [{quality}] dari: {url[:65]}...", CYAN)
    PROGRESS_MGR.update(
        key=dl_task_key,
        label=f"[{quality}] {dest_path.name}",
        cur_mb=0.0,
        tot_mb=0.0,
        speed_mb=0.0,
        eta_str="",
        status_text="Menghubungkan ke server..."
    )

    start_time = time.time()
    last_print = time.time()
    downloaded = 0

    # 1. Coba Multi-Connection Parallel Download untuk file Pixeldrain (mengatasi throttle 1 MB/s menjadi 3+ MB/s)
    if 'pixeldrain.com' in url:
        try:
            async with PIXELDRAIN_SEMAPHORE:
                head_timeout = aiohttp.ClientTimeout(total=8, connect=6.0)
                async with aiohttp.ClientSession(headers=headers, timeout=head_timeout) as h_session:
                    async with h_session.head(url) as h_resp:
                        if h_resp.status in (200, 206):
                            c_len = int(h_resp.headers.get('content-length', 0))
                            accepts_ranges = h_resp.headers.get('accept-ranges', '').lower() == 'bytes'
                            if c_len > 12 * 1024 * 1024 and accepts_ranges:
                                is_colab = get_device_role() in CLOUD_ROLES
                                num_workers = 8 if is_colab else 6
                                part_size = c_len // num_workers
                                total_mb = c_len / (1024 * 1024)
                                state_ref = {'downloaded': 0, 'last_chunk_time': time.time(), 'aborted_slow': False}
                                part_files = []
                                part_tasks = []

                                for idx in range(num_workers):
                                    p_start = idx * part_size
                                    p_end = (p_start + part_size - 1) if (idx < num_workers - 1) else (c_len - 1)
                                    p_file = dest_path.with_suffix(f'.part_{idx}.tmp')
                                    part_files.append(p_file)
                                    part_tasks.append(asyncio.create_task(download_chunk_worker(url, headers, p_start, p_end, p_file, state_ref)))

                                async def monitor_parallel():
                                    try:
                                        while not state_ref.get('aborted_slow') and state_ref['downloaded'] < c_len:
                                            await asyncio.sleep(0.3)
                                            now = time.time()
                                            cur_dl = state_ref['downloaded']
                                            if cur_dl > 0:
                                                first_dl = state_ref.setdefault('first_data_time', now)
                                                data_elapsed = max(0.1, now - first_dl)
                                                speed_mb = (cur_dl / data_elapsed) / (1024 * 1024)
                                            else:
                                                data_elapsed = 0.0
                                                speed_mb = 0.0

                                            cur_mb = cur_dl / (1024 * 1024)
                                            eta = f"{int((c_len - cur_dl) / (speed_mb * 1024 * 1024))}s" if speed_mb > 0 else ""

                                            # CasaOS Server Standby Guard: Jangan unduh apapun jika remote worker aktif
                                            if get_device_role() == "server" and has_active_remote_workers():
                                                state_ref['aborted_slow'] = True
                                                for pt in part_tasks:
                                                    pt.cancel()
                                                PROGRESS_MGR.remove(dl_task_key)
                                                log("STANDBY", f"💤 Server CasaOS Standby: Remote worker aktif di cluster. Menghentikan unduhan [{quality}]...", YELLOW)
                                                break

                                            # Stall Watchdog: tidak ada chunk baru selama >= 8.0 detik
                                            if cur_dl > 0 and (now - state_ref.get('last_chunk_time', now)) >= 8.0:
                                                state_ref['aborted_slow'] = True
                                                for pt in part_tasks:
                                                    pt.cancel()
                                                PROGRESS_MGR.remove(dl_task_key)
                                                log("SLOW_SPEED", f"⚠️ Unduhan [{quality}] macet (tidak ada respon data selama 8s). Dibatalkan...", YELLOW)
                                                break

                                            # Slow Speed Watchdog: Batalkan unduhan jika terdeteksi lambat (< min_speed_mb) setelah 12 detik transfer aktif
                                            if min_speed_mb > 0 and cur_dl > 0 and data_elapsed >= 12.0 and speed_mb < min_speed_mb and (cur_dl / c_len) < 0.6:
                                                state_ref['aborted_slow'] = True
                                                for pt in part_tasks:
                                                    pt.cancel()
                                                PROGRESS_MGR.remove(dl_task_key)
                                                log("SLOW_SPEED", f"⚠️ Kecepatan unduh [{quality}] lambat ({speed_mb:.1f} MB/s < batas {min_speed_mb} MB/s). Dibatalkan seketika...", YELLOW)
                                                break

                                            PROGRESS_MGR.update(
                                                key=dl_task_key,
                                                label=f"[{quality} Multi-Stream] {dest_path.name}",
                                                cur_mb=cur_mb,
                                                tot_mb=total_mb,
                                                speed_mb=speed_mb,
                                                eta_str=eta
                                            )
                                    except asyncio.CancelledError:
                                        pass
                                    except Exception:
                                        pass

                                mon_task = asyncio.create_task(monitor_parallel())
                                try:
                                    results = await asyncio.gather(*part_tasks, return_exceptions=True)
                                finally:
                                    mon_task.cancel()
                                    PROGRESS_MGR.remove(dl_task_key)

                                if state_ref.get('aborted_slow'):
                                    for pf in part_files:
                                        if pf.exists():
                                            try: pf.unlink()
                                            except Exception: pass
                                    return False

                                if all(r is True for r in results):
                                    with open(tmp_path, 'wb') as out_f:
                                        for pf in part_files:
                                            if pf.exists():
                                                with open(pf, 'rb') as in_f:
                                                    while True:
                                                        b = in_f.read(1024 * 1024 * 2)
                                                        if not b: break
                                                        out_f.write(b)
                                                pf.unlink()
                                    PROGRESS_MGR.remove(dl_task_key)
                                    if tmp_path.exists() and tmp_path.stat().st_size / (1024 * 1024) >= 2.0:
                                        if dest_path.exists(): dest_path.unlink()
                                        tmp_path.rename(dest_path)
                                        f_size = dest_path.stat().st_size / (1024 * 1024)
                                        tot_el = max(0.1, time.time() - start_time)
                                        avg_sp = f_size / tot_el
                                        log("DONE", f"Selesai [{quality} - 3x Multi-Stream]: {dest_path.name} ({f_size:.1f} MB) @ {avg_sp:.2f} MB/s", GREEN)
                                        return True
                                for pf in part_files:
                                    if pf.exists():
                                        try: pf.unlink()
                                        except Exception: pass
                        elif h_resp.status == 403:
                            PROGRESS_MGR.remove(dl_task_key)
                            log("NOTICE", f"Tautan [{quality}] Pixeldrain limit kuota harian (HTTP 403). Mencoba alternatif...", YELLOW)
                            return False
                        elif h_resp.status in (404, 410):
                            PROGRESS_MGR.remove(dl_task_key)
                            log("NOTICE", f"Tautan [{quality}] Pixeldrain tidak ditemukan (HTTP {h_resp.status}). Mencoba alternatif...", YELLOW)
                            return False
        except Exception:
            pass

    # 2. Standar High-Buffer Stream (untuk Kuramadrive CDN 14+ MB/s atau fallback)
    try:
        candidate_urls = [url]
        if orig_stream_url != url and orig_stream_url not in candidate_urls:
            candidate_urls.append(orig_stream_url)

        dl_success = False
        for c_idx, active_url in enumerate(candidate_urls):
            active_headers = dict(headers)
            if active_url == orig_stream_url and active_url != url:
                active_headers = {'User-Agent': DEFAULT_UA, 'Accept': '*/*'}
                log("FALLBACK", f"⚡ Direct CDN gagal/limit. Beralih mengunduh [{quality}] via Nipnime Player Proxy...", YELLOW)

            stream_timeout = aiohttp.ClientTimeout(total=1800, connect=10.0, sock_connect=10.0, sock_read=10.0)
            async with aiohttp.ClientSession(headers=active_headers, timeout=stream_timeout, read_bufsize=1024 * 1024) as session:
                try:
                    resp = await asyncio.wait_for(session.get(active_url, ssl=False), timeout=12.0)
                    async with resp:
                        if resp.status not in (200, 206):
                            if c_idx < len(candidate_urls) - 1:
                                continue
                            PROGRESS_MGR.remove(dl_task_key)
                            if resp.status == 451:
                                log("NOTICE", f"Tautan [{quality}] dihapus/diblokir hak cipta oleh hoster (HTTP 451 DMCA Takedown). Melanjutkan ke sumber lain...", YELLOW)
                            elif resp.status in (404, 410):
                                log("NOTICE", f"Tautan [{quality}] kadaluarsa/tidak ditemukan (HTTP {resp.status}). Melanjutkan...", YELLOW)
                            elif resp.status == 403:
                                log("NOTICE", f"Tautan [{quality}] limit kuota hoster (HTTP 403 Forbidden). Beralih ke alternatif...", YELLOW)
                            else:
                                log("NOTICE", f"Tautan [{quality}] gagal HTTP {resp.status} (limit hoster/kuota). Mencoba cadangan jika ada...", YELLOW)
                            return False

                        c_type = resp.headers.get('content-type', '').lower()
                        if any(bad in c_type for bad in ['text/html', 'text/plain', 'application/json']):
                            if c_idx < len(candidate_urls) - 1:
                                continue
                            PROGRESS_MGR.remove(dl_task_key)
                            sample_text = ""
                            try:
                                sample_bytes = await resp.content.read(2048)
                                sample_text = sample_bytes.decode('utf-8', errors='ignore').lower()
                            except Exception:
                                pass

                            if any(q_kw in sample_text for q_kw in ['quota exceeded', 'too many users', 'ratelimitexceeded', 'limit kuota']):
                                log("NOTICE", f"Tautan [{quality}] Google Drive / Acefile limit kuota download (Google Drive Quota Exceeded). Beralih ke sumber cadangan...", YELLOW)
                            elif any(nf_kw in sample_text for nf_kw in ['not found', 'notfound', 'tidak ditemukan', 'file deleted']):
                                log("NOTICE", f"Tautan [{quality}] file di hoster tidak ditemukan (404 Not Found / Dihapus). Beralih...", YELLOW)
                            elif 'download-form' in sample_text or 'uc-download-link' in sample_text:
                                log("NOTICE", f"Tautan [{quality}] Google Drive membutuhkan konfirmasi virus scan tambahan. Beralih...", YELLOW)
                            else:
                                log("NOTICE", f"Tautan [{quality}] mengarah ke halaman web ({c_type}), bukan file video langsung. Dibatalkan.", YELLOW)
                            return False

                        total_size = int(resp.headers.get('content-length', 0))
                        total_mb = (total_size / (1024 * 1024)) if total_size > 0 else 0

                        state_ref = {
                            'downloaded': 0,
                            'last_chunk_time': time.time(),
                            'aborted': False,
                            'abort_reason': ''
                        }

                        async def monitor_single():
                            while not state_ref['aborted']:
                                await asyncio.sleep(0.3)
                                now = time.time()
                                cur_dl = state_ref['downloaded']
                                if cur_dl > 0:
                                    first_dl = state_ref.setdefault('first_data_time', now)
                                    data_elapsed = max(0.1, now - first_dl)
                                    speed_mb = (cur_dl / data_elapsed) / (1024 * 1024)
                                else:
                                    data_elapsed = 0.0
                                    speed_mb = 0.0

                                cur_mb = cur_dl / (1024 * 1024)
                                eta = f"{int((total_size - cur_dl) / (speed_mb * 1024 * 1024))}s" if (total_size > 0 and speed_mb > 0) else ""

                                # CasaOS Server Standby Guard: Jangan unduh apapun jika remote worker aktif
                                if get_device_role() == "server" and has_active_remote_workers():
                                    state_ref['aborted'] = True
                                    state_ref['abort_reason'] = "remote worker aktif di cluster (CasaOS standby)"
                                    PROGRESS_MGR.remove(dl_task_key)
                                    log("STANDBY", f"💤 Server CasaOS Standby: Remote worker aktif di cluster. Menghentikan unduhan [{quality}]...", YELLOW)
                                    break

                                # Stall Watchdog: Tidak ada chunk data baru selama >= 15 detik (toleran terhadap buffer flush file besar)
                                if cur_dl > 0 and (now - state_ref['last_chunk_time']) >= 15.0:
                                    state_ref['aborted'] = True
                                    state_ref['abort_reason'] = "koneksi macet / tidak ada data selama 15s"
                                    break

                                # Slow Speed Watchdog: Batalkan unduhan jika terdeteksi lambat (< min_speed_mb) setelah 15 detik transfer aktif
                                if min_speed_mb > 0 and cur_dl > 0 and data_elapsed >= 15.0 and speed_mb < min_speed_mb and (total_size == 0 or (cur_dl / total_size) < 0.6):
                                    state_ref['aborted'] = True
                                    state_ref['abort_reason'] = f"kecepatan lambat ({speed_mb:.1f} MB/s < batas {min_speed_mb} MB/s)"
                                    break

                                # Khusus Pixeldrain Throttling Guard: Hanya batalkan jika worker meminta kecepatan tinggi (ongoing min_speed_mb >= 1.5)
                                # Untuk unduhan batch anime tamat (min_speed_mb < 1.5), biarkan Pixeldrain berjalan penuh hingga tuntas!
                                if min_speed_mb >= 1.5 and 'pixeldrain' in active_url.lower() and cur_dl > 0 and data_elapsed >= 8.0 and speed_mb <= 1.2 and (total_size == 0 or (cur_dl / total_size) < 0.7):
                                    state_ref['aborted'] = True
                                    state_ref['abort_reason'] = f"kecepatan limit hoster Pixeldrain ({speed_mb:.1f} MB/s <= 1.2 MB/s free tier limit)"
                                    break

                                PROGRESS_MGR.update(
                                    key=dl_task_key,
                                    label=f"[{quality}] {dest_path.name}",
                                    cur_mb=cur_mb,
                                    tot_mb=total_mb,
                                    speed_mb=speed_mb,
                                    eta_str=eta
                                )

                        mon_task = asyncio.create_task(monitor_single())
                        try:
                            with open(tmp_path, 'wb') as f:
                                while not state_ref['aborted']:
                                    try:
                                        chunk = await asyncio.wait_for(resp.content.read(1024 * 256), timeout=3.0)
                                    except asyncio.TimeoutError:
                                        if (time.time() - state_ref['last_chunk_time']) >= 12.0:
                                            state_ref['aborted'] = True
                                            state_ref['abort_reason'] = "tidak ada respon data selama 12s (stalled)"
                                            break
                                        continue

                                    if not chunk:
                                        break
                                    f.write(chunk)
                                    state_ref['downloaded'] += len(chunk)
                                    state_ref['last_chunk_time'] = time.time()
                        finally:
                            mon_task.cancel()

                        if state_ref['aborted']:
                            if c_idx < len(candidate_urls) - 1:
                                if tmp_path.exists(): tmp_path.unlink()
                                continue
                            PROGRESS_MGR.remove(dl_task_key)
                            log("SLOW_SPEED", f"⚠️ Unduhan [{quality}] dibatalkan ({state_ref['abort_reason']}). Mencari sumber lain atau skip...", YELLOW)
                            if tmp_path.exists(): tmp_path.unlink()
                            return False

                        dl_success = True
                        break
                except (asyncio.TimeoutError, aiohttp.ClientError) as conn_err:
                    if c_idx < len(candidate_urls) - 1:
                        if tmp_path.exists(): tmp_path.unlink()
                        continue
                    PROGRESS_MGR.remove(dl_task_key)
                    domain = urlparse(active_url).netloc
                    log("NOTICE", f"Tautan [{quality}] gagal terhubung / timeout (8s) ke {domain}. Beralih ke sumber alternatif...", YELLOW)
                    if tmp_path.exists(): tmp_path.unlink()
                    return False

        if not dl_success:
            return False

        PROGRESS_MGR.remove(dl_task_key)
        if tmp_path.exists():
            file_size_mb = tmp_path.stat().st_size / (1024 * 1024)
            if file_size_mb < 2.0:
                log("ERROR", f"Ukuran file mencurigakan terlalu kecil ({file_size_mb:.2f} MB), bukan file video asli. Dibatalkan!", RED)
                tmp_path.unlink()
                return False

            if dest_path.exists():
                try:
                    dest_path.unlink()
                except Exception:
                    pass
            try:
                tmp_path.rename(dest_path)
            except Exception as ren_err:
                # Jika Windows masih me-lock file lama, beri jeda singkat dan coba sekali lagi
                await asyncio.sleep(1.0)
                if dest_path.exists():
                    try: dest_path.unlink()
                    except Exception: pass
                tmp_path.rename(dest_path)

            log("DONE", f"Selesai [{quality}]: {dest_path.name} ({file_size_mb:.1f} MB)", GREEN)
            return True
    except Exception as e:
        log("ERROR", f"Gagal mengunduh: {e}", RED)
        return False
    finally:
        PROGRESS_MGR.remove(dl_task_key)
        if tmp_path.exists():
            try: tmp_path.unlink()
            except Exception: pass

async def download_file(url: str, dest_path: Path, quality: str, min_speed_mb: float = 0.8, backup_urls: list = None) -> bool:
    if get_device_role() == "server" and has_active_remote_workers():
        log("STANDBY", "💤 CasaOS Server Standby: Remote worker aktif di cluster. Membatalkan unduhan file.", YELLOW)
        return False
    if not ensure_safe_disk_space(required_mb=1000):
        return False
    urls_to_try = [url]
    if backup_urls:
        for b in backup_urls:
            b_clean = html.unescape(b).strip()
            if b_clean and b_clean not in urls_to_try:
                urls_to_try.append(b_clean)

    for idx, try_url in enumerate(urls_to_try):
        if idx > 0:
            log("BACKUP_TRY", f"⚡ Mencoba tautan cadangan ({idx}/{len(urls_to_try)-1}) [{quality}]: {try_url[:65]}...", CYAN)
        ok = await _download_single_stream_url(try_url, dest_path, quality, min_speed_mb=min_speed_mb)
        if ok and dest_path.exists():
            return True
    return False

def record_url_failure(failed_urls: dict, url: str) -> None:
    """Mencatat riwayat gagal unduhan (timeout / kecepatan drop / limit hoster) beserta timestamp agar bisa dicoba ulang setelah 1 jam."""
    if not isinstance(failed_urls, dict):
        return
    now = time.time()
    entry = failed_urls.get(url)
    if isinstance(entry, dict):
        cnt = entry.get('count', 0) + 1
        failed_urls[url] = {'count': cnt, 'last_failed': now}
    elif isinstance(entry, (int, float)):
        failed_urls[url] = {'count': int(entry) + 1, 'last_failed': now}
    else:
        failed_urls[url] = {'count': 1, 'last_failed': now}

def is_url_on_cooldown(failed_urls: dict, url: str, cooldown_sec: int = 3600) -> bool:
    """
    Mengecek apakah tautan sedang dalam masa jeda / cooldown 1 jam (misal limit kuota hoster / Pixeldrain / Google Drive / Kuramadrive).
    Setelah 1 jam (3600 detik), hitungan kegagalan otomatis di-reset agar dicoba kembali saat kuota pulih.
    """
    if not isinstance(failed_urls, dict):
        return False
    entry = failed_urls.get(url)
    if not entry:
        return False
    now = time.time()
    if isinstance(entry, dict):
        cnt = entry.get('count', 0)
        last_failed = entry.get('last_failed', 0)
        if cnt >= 2:
            if (now - last_failed) < cooldown_sec:
                return True
            else:
                # Masa cooldown 1 jam telah selesai! Reset hitungan gagal agar link dicoba kembali
                log("RETRY_LIMIT", f"⏳ Cooldown 1 jam selesai untuk {urlparse(url).netloc}. Mencoba kembali unduhan...", CYAN)
                entry['count'] = 0
                return False
    elif isinstance(entry, (int, float)):
        return entry >= 2
    return False

# =============================================================================
# ⚡ AKSELERASI MTPROTO MULTI-SESSION PARALLEL UPLOAD UNTUK PYROGRAM
# =============================================================================
_original_pyrogram_save_file = SaveFile.save_file

async def turbo_save_file(
    self: "pyrogram.Client",
    path: Union[str, BinaryIO],
    file_id: int = None,
    file_part: int = 0,
    progress: Callable = None,
    progress_args: tuple = ()
):
    """
    ⚡ Akselerasi MTProto Multi-Session Parallel Upload untuk Pyrogram.
    Membuka 4-6 media TCP session pool paralel ke Telegram DC,
    mengirim chunk 512KB secara concurrent via multi-stream pipeline.
    Menghilangkan limitasi 1 TCP socket antar-benua (Google Colab / Azure -> Telegram DC Singapore).
    """
    if path is None:
        return None

    # Fallback untuk retry part tunggal atau stream non-file tanpa ukuran tetap
    if file_id is not None or not isinstance(path, (str, Path, PurePath)):
        return await _original_pyrogram_save_file(
            self, path, file_id=file_id, file_part=file_part,
            progress=progress, progress_args=progress_args
        )

    file_path = Path(path)
    if not file_path.exists():
        return await _original_pyrogram_save_file(
            self, path, file_id=file_id, file_part=file_part,
            progress=progress, progress_args=progress_args
        )

    file_size = file_path.stat().st_size
    if file_size == 0:
        raise ValueError("File size equals to 0 B")

    # File kecil (<= 10MB) memakai standard single-session bawaan untuk hemat overhead
    if file_size <= 10 * 1024 * 1024:
        return await _original_pyrogram_save_file(
            self, path, file_id=file_id, file_part=file_part,
            progress=progress, progress_args=progress_args
        )

    async with self.save_file_semaphore:
        part_size = 512 * 1024  # 512 KB per chunk (ukuran standar MTProto Telegram)
        file_total_parts = int(math.ceil(file_size / part_size))
        assigned_file_id = self.rnd_id()
        file_name = file_path.name

        # Pool session paralel: 6 session untuk Colab / Azure, 4 untuk laptop / server
        dev_role = get_device_role()
        num_sessions = 6 if dev_role in CLOUD_ROLES else 4

        dc_id = await self.storage.dc_id()
        auth_key = await self.storage.auth_key()
        test_mode = await self.storage.test_mode()

        sessions = [
            Session(self, dc_id, auth_key, test_mode, is_media=True)
            for _ in range(num_sessions)
        ]

        # Inisialisasi koneksi paralel dengan jeda halus 50ms agar TCP & TLS handshake stabil
        for s in sessions:
            await s.start()
            await asyncio.sleep(0.05)

        queue = asyncio.Queue(maxsize=num_sessions * 2)
        uploaded_bytes = 0
        lock = asyncio.Lock()
        upload_error = None

        async def worker(sess: Session):
            nonlocal uploaded_bytes, upload_error
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    return

                part_idx, chunk = item
                if upload_error is not None:
                    queue.task_done()
                    continue

                try:
                    rpc = raw.functions.upload.SaveBigFilePart(
                        file_id=assigned_file_id,
                        file_part=part_idx,
                        file_total_parts=file_total_parts,
                        bytes=chunk
                    )
                    await sess.invoke(rpc)
                    async with lock:
                        uploaded_bytes += len(chunk)
                        if progress:
                            current_uploaded = min(uploaded_bytes, file_size)
                            func = functools.partial(
                                progress,
                                current_uploaded,
                                file_size,
                                *progress_args
                            )
                            if inspect.iscoroutinefunction(progress):
                                await func()
                            else:
                                await self.loop.run_in_executor(self.executor, func)
                except Exception as e:
                    upload_error = e
                    log("TURBO_ERR", f"Gagal upload chunk {part_idx}/{file_total_parts}: {e}", RED)
                finally:
                    queue.task_done()

        workers = [self.loop.create_task(worker(s)) for s in sessions]

        try:
            with open(file_path, "rb") as fp:
                for part_idx in range(file_total_parts):
                    if upload_error is not None:
                        break
                    chunk = fp.read(part_size)
                    if not chunk:
                        break
                    await queue.put((part_idx, chunk))

            await queue.join()

            if upload_error is not None:
                raise upload_error

            return raw.types.InputFileBig(
                id=assigned_file_id,
                parts=file_total_parts,
                name=file_name
            )
        finally:
            for _ in workers:
                await queue.put(None)
            await asyncio.gather(*workers, return_exceptions=True)
            await asyncio.gather(*[s.stop() for s in sessions], return_exceptions=True)

# Terapkan akselerasi multi-session secara global ke Pyrogram save_file
SaveFile.save_file = turbo_save_file

# =============================================================================
# ⚡ AKSELERASI MTPROTO MULTI-SESSION PARALLEL DOWNLOAD UNTUK PYROGRAM
# =============================================================================
async def turbo_download_file(
    client: Client,
    media,
    dest_path: Union[str, Path],
    progress: Callable = None,
    progress_args: tuple = ()
) -> bool:
    """
    ⚡ Akselerasi MTProto Multi-Session Parallel Download untuk Pyrogram.
    Membuka 4-6 media TCP session pool paralel ke Telegram DC,
    mengambil chunk 1MB secara concurrent via multi-stream pipeline.
    Menghilangkan limitasi 1 socket MTProto bawaan (300-500 KB/s) dan melonjakkan kecepatan hingga 15-40+ MB/s!
    """
    dest_file = Path(dest_path)
    file_size = getattr(media, "file_size", 0)
    file_id_str = getattr(media, "file_id", "")
    if not file_id_str or file_size <= 0:
        return False

    # File kecil (<= 5MB) memakai single-stream bawaan untuk hemat overhead
    if file_size <= 5 * 1024 * 1024:
        res = await client.download_media(media, file_name=str(dest_file), progress=progress, progress_args=progress_args)
        return bool(res and dest_file.exists() and dest_file.stat().st_size > 0)

    try:
        fid = FileId.decode(file_id_str)
        location = raw.types.InputDocumentFileLocation(
            id=fid.media_id,
            access_hash=fid.access_hash,
            file_reference=fid.file_reference,
            thumb_size=fid.thumbnail_size or ""
        )

        part_size = 1024 * 1024  # 1 MB per chunk (ukuran optimal GetFile MTProto)
        total_parts = int(math.ceil(file_size / part_size))

        # Pool session paralel: 6 session untuk Colab / Azure, 4 untuk laptop / server
        # Namun jika file berada di DC yang berbeda, gunakan 1 session saja agar TIDAK terkena FLOOD_WAIT ExportAuthorization
        dc_id = fid.dc_id
        client_dc_id = await client.storage.dc_id()
        test_mode = await client.storage.test_mode()

        dev_role = get_device_role()
        if dc_id != client_dc_id:
            num_sessions = 1
        else:
            num_sessions = 6 if dev_role in CLOUD_ROLES else 4
        auth_key = await client.storage.auth_key() if dc_id == client_dc_id else await Auth(client, dc_id, test_mode).create()

        sessions = [
            Session(client, dc_id, auth_key, test_mode, is_media=True)
            for _ in range(num_sessions)
        ]

        # Inisialisasi koneksi paralel dengan jeda halus 40ms
        for s in sessions:
            await s.start()
            if dc_id != client_dc_id:
                exp = await client.invoke(raw.functions.auth.ExportAuthorization(dc_id=dc_id))
                await s.invoke(raw.functions.auth.ImportAuthorization(id=exp.id, bytes=exp.bytes))
            await asyncio.sleep(0.04)

        dest_file.parent.mkdir(parents=True, exist_ok=True)
        # Pre-alokasi file di disk agar penulisan chunk paralel via seek langsung stabil
        with open(dest_file, "wb") as fp:
            fp.truncate(file_size)

        queue = asyncio.Queue()
        for p_idx in range(total_parts):
            queue.put_nowait((p_idx, 0))

        downloaded_bytes = 0
        file_lock = asyncio.Lock()
        dl_error = None

        with open(dest_file, "r+b") as fp:
            async def worker(sess: Session):
                nonlocal downloaded_bytes, dl_error
                while True:
                    if dl_error is not None:
                        return
                    try:
                        part_idx, attempt = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return

                    offset = part_idx * part_size
                    try:
                        r = await sess.invoke(
                            raw.functions.upload.GetFile(
                                location=location,
                                offset=offset,
                                limit=part_size
                            ),
                            sleep_threshold=60
                        )
                        if isinstance(r, raw.types.upload.File):
                            chunk_data = r.bytes
                            async with file_lock:
                                fp.seek(offset)
                                fp.write(chunk_data)
                                downloaded_bytes += len(chunk_data)
                                cur_down = min(downloaded_bytes, file_size)

                            if progress:
                                func = functools.partial(progress, cur_down, file_size, *progress_args)
                                if inspect.iscoroutinefunction(progress):
                                    await func()
                                else:
                                    await client.loop.run_in_executor(client.executor, func)
                            queue.task_done()
                        elif isinstance(r, raw.types.upload.FileCdnRedirect):
                            raise NotImplementedError("FileCdnRedirect detected")
                        else:
                            raise RuntimeError(f"Unexpected response: {type(r)}")
                    except Exception as e:
                        # Pulihkan sesi jika transport TCP terputus
                        try:
                            await sess.stop()
                        except Exception:
                            pass
                        try:
                            await sess.start()
                            if dc_id != client_dc_id:
                                exp = await client.invoke(raw.functions.auth.ExportAuthorization(dc_id=dc_id))
                                await sess.invoke(raw.functions.auth.ImportAuthorization(id=exp.id, bytes=exp.bytes))
                        except Exception:
                            pass

                        if attempt < 5:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            queue.put_nowait((part_idx, attempt + 1))
                            queue.task_done()
                        else:
                            dl_error = e
                            log("TURBO_DL_ERR", f"Gagal unduh chunk {part_idx}/{total_parts} setelah 5 percobaan: {e}", RED)
                            queue.task_done()
                            return

            workers = [client.loop.create_task(worker(s)) for s in sessions]
            try:
                await queue.join()
            finally:
                await asyncio.gather(*workers, return_exceptions=True)
                await asyncio.gather(*[s.stop() for s in sessions], return_exceptions=True)

        if dl_error is not None:
            raise dl_error

        return dest_file.exists() and dest_file.stat().st_size >= file_size
    except Exception as e:
        log("TURBO_DL_FALLBACK", f"Turbo download beralih ke download standar ({e})...", YELLOW)
        if dest_file.exists():
            try: dest_file.unlink()
            except Exception: pass
        res = await client.download_media(media, file_name=str(dest_file), progress=progress, progress_args=progress_args)
        return bool(res and dest_file.exists() and dest_file.stat().st_size > 0)



async def delegate_upload_to_relay_server(
    file_path: Path,
    anime_title: str,
    episode_num: any,
    quality: str,
    source_info: str,
    episode_id: int = 0,
    is_tamat: bool = False,
    server_name_custom: str = None
) -> int:
    """
    Cluster Upload Relay: Mendelegasikan file video yang sudah dirender GPU secara lokal
    ke server CasaOS via HTTPS Multipart Chunk Upload (20MB per chunk), agar diunggah
    ke Telegram oleh server yang memiliki akses penuh MTProto tanpa terhalang Mikrotik.
    """
    global _IS_UPLOADING_BYTES
    if not file_path.exists() or file_path.stat().st_size == 0:
        log("RELAY_ERR", f"File video tidak ditemukan atau kosong: {file_path}", RED)
        return None

    total_size = file_path.stat().st_size
    chunk_size = 20 * 1024 * 1024  # 20 MB per chunk (Aman untuk Nginx 50M & Cloudflare Tunnel 100M)
    total_chunks = max(1, (total_size + chunk_size - 1) // chunk_size)
    upload_id = f"relay_{int(time.time())}_{str(uuid.uuid4())[:8]}"
    relay_url = f"{API_URL}/upload-relay"

    log("RELAY_DELEGATE", f"🌐 [CLUSTER RELAY] Mengirim [{quality}] {file_path.name} ({round(total_size / 1048576, 1)} MB) ke Server CasaOS via {total_chunks} chunk...", BOLD + CYAN)

    up_task_key = f"relay_{file_path.name}_{quality}"
    upload_start_time = time.time()
    last_speed_check_time = upload_start_time
    last_speed_check_bytes = 0
    smooth_speed = 0.0

    _IS_UPLOADING_BYTES = True
    try:
        async with aiohttp.ClientSession() as session:
            with open(file_path, 'rb') as f_in:
                for chunk_idx in range(total_chunks):
                    chunk_bytes = f_in.read(chunk_size)
                    if not chunk_bytes:
                        break

                    now = time.time()
                    cur_uploaded = min(total_size, (chunk_idx * chunk_size) + len(chunk_bytes))
                    cur_mb = cur_uploaded / (1024 * 1024)
                    tot_mb = total_size / (1024 * 1024)
                    pct = (cur_uploaded / total_size) * 100 if total_size > 0 else 0

                    dt = now - last_speed_check_time
                    if dt >= 0.5:
                        delta_bytes = cur_uploaded - last_speed_check_bytes
                        instant_speed = (delta_bytes / dt) / (1024 * 1024)
                        smooth_speed = instant_speed if smooth_speed == 0.0 else (0.7 * smooth_speed + 0.3 * instant_speed)
                        last_speed_check_time = now
                        last_speed_check_bytes = cur_uploaded

                    total_elapsed = max(0.1, now - upload_start_time)
                    effective_speed = smooth_speed if smooth_speed > 0 else (cur_mb / total_elapsed)

                    eta_str = ""
                    if effective_speed > 0 and total_size > cur_uploaded:
                        rem_sec = int((tot_mb - cur_mb) / effective_speed)
                        if rem_sec >= 60:
                            eta_str = f"{rem_sec // 60}m {rem_sec % 60}s"
                        else:
                            eta_str = f"{rem_sec}s"

                    PROGRESS_MGR.update(
                        key=up_task_key,
                        label=f"[{quality} Relay Upload] {file_path.name}",
                        cur_mb=round(cur_mb, 1),
                        tot_mb=round(tot_mb, 1),
                        pct=pct,
                        speed_mb=round(effective_speed, 2),
                        eta_str=eta_str,
                        status_text=f"Relay Chunk {chunk_idx + 1}/{total_chunks}: {pct:.1f}% @ {effective_speed:.1f} MB/s" + (f" (ETA: {eta_str})" if eta_str else ""),
                        category="tamat" if is_tamat else "ongoing"
                    )

                    chunk_sent = False
                    for c_attempt in range(4):
                        try:
                            data = aiohttp.FormData()
                            data.add_field('upload_id', upload_id)
                            data.add_field('chunk_index', str(chunk_idx))
                            data.add_field('total_chunks', str(total_chunks))
                            data.add_field('file_name', file_path.name)
                            data.add_field('quality', quality)
                            data.add_field('anime_title', anime_title)
                            data.add_field('episode_num', str(episode_num))
                            data.add_field('episode_id', str(episode_id))
                            data.add_field('source_info', source_info)
                            data.add_field('is_tamat', '1' if is_tamat else '0')
                            data.add_field('worker_id', get_worker_id())
                            if server_name_custom:
                                data.add_field('server_name', server_name_custom)
                            data.add_field(
                                'chunk_data',
                                chunk_bytes,
                                filename=f"chunk_{chunk_idx:05d}",
                                content_type='application/octet-stream'
                            )

                            headers = {
                                'User-Agent': DEFAULT_UA,
                                'X-Terop-Token': WORKER_TOKEN,
                                'Accept': 'application/json'
                            }

                            async with session.post(relay_url, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                                if resp.status == 200:
                                    res_json = await resp.json()
                                    if res_json.get('success'):
                                        chunk_sent = True
                                        break
                                    else:
                                        log("RELAY_RETRY", f"Server menolak chunk {chunk_idx}: {res_json}", YELLOW)
                                else:
                                    log("RELAY_RETRY", f"HTTP {resp.status} saat kirim chunk {chunk_idx}", YELLOW)
                        except Exception as ce:
                            log("RELAY_RETRY", f"Koneksi chunk {chunk_idx} gagal (percobaan {c_attempt + 1}/4): {ce}", YELLOW)
                        await asyncio.sleep(2)

                    if not chunk_sent:
                        PROGRESS_MGR.remove(up_task_key)
                        log("RELAY_FAIL", f"Gagal mengirim chunk {chunk_idx}/{total_chunks} ke server relay setelah 4 percobaan.", RED)
                        return None

            PROGRESS_MGR.remove(up_task_key)
            log("RELAY_SUCCESS", f"✓ [RELAY BERHASIL] Seluruh chunk video {file_path.name} [{quality}] sukses dikirim ke Server CasaOS!", BOLD + GREEN)
            return -999
    except Exception as e:
        PROGRESS_MGR.remove(up_task_key)
        log("RELAY_ERROR", f"Kendala saat delegasi upload ke server relay: {e}", RED)
        return None
    finally:
        _IS_UPLOADING_BYTES = False


async def upload_video_to_telegram(client: Client, file_path: Path, anime_title: str, episode_num: int, quality: str, source_info: str, skip_watermark: bool = False, is_tamat: bool = False, episode_id: int = 0) -> int:
    global _watermark_test_count, WATERMARK_SINGLE_TEST, _RELAY_UPLOAD_MODE

    upload_target = file_path
    is_temp_wm = False

    # Penerapan Watermark Resmi Nipnime
    if ENABLE_WATERMARK and not skip_watermark:
        try:
            wm_file = await apply_nipnime_watermark(file_path, quality, source_info)
            if wm_file and wm_file.exists() and wm_file != file_path:
                upload_target = wm_file
                is_temp_wm = True
        except Exception as wme:
            log("WATERMARK_WARN", f"Gagal menerapkan watermark ({wme}), mengunggah video asli.", YELLOW)
            upload_target = file_path
            is_temp_wm = False

    # JIKA DALAM MODE RELAY UPLOAD (Misal PC Warnet diblokir Telegram MTProto oleh Mikrotik):
    # Kirim video terenkripsi / chunk ke server Nipnime via HTTPS API untuk di-upload oleh server CasaOS!
    if _RELAY_UPLOAD_MODE or not client or not getattr(client, 'is_connected', False):
        try:
            return await delegate_upload_to_relay_server(
                file_path=upload_target,
                anime_title=anime_title,
                episode_num=episode_num,
                quality=quality,
                source_info=source_info,
                episode_id=episode_id,
                is_tamat=is_tamat
            )
        finally:
            if is_temp_wm and upload_target.exists():
                try: upload_target.unlink()
                except Exception: pass

    up_task_key = f"up_{upload_target.name}_{quality}"
    log("UPLOAD", f"Mengunggah [{quality}] ke Telegram Channel [{CHANNEL_ID}]...", CYAN)

    upload_start_time = time.time()
    last_speed_check_time = upload_start_time
    last_speed_check_bytes = 0
    smooth_speed = 0.0

    def progress_callback(current, total):
        nonlocal last_speed_check_time, last_speed_check_bytes, smooth_speed
        now = time.time()
        cur_mb = current / (1024 * 1024)
        tot_mb = total / (1024 * 1024)
        pct = (current / total) * 100 if total > 0 else 0

        dt = now - last_speed_check_time
        if dt >= 0.5:
            delta_bytes = current - last_speed_check_bytes
            instant_speed = (delta_bytes / dt) / (1024 * 1024)
            smooth_speed = instant_speed if smooth_speed == 0.0 else (0.7 * smooth_speed + 0.3 * instant_speed)
            last_speed_check_time = now
            last_speed_check_bytes = current

        total_elapsed = max(0.1, now - upload_start_time)
        effective_speed = smooth_speed if smooth_speed > 0 else (cur_mb / total_elapsed)

        eta_str = ""
        if effective_speed > 0 and total > current:
            rem_sec = int((tot_mb - cur_mb) / effective_speed)
            if rem_sec >= 60:
                eta_str = f"{rem_sec // 60}m {rem_sec % 60}s"
            else:
                eta_str = f"{rem_sec}s"

        PROGRESS_MGR.update(
            key=up_task_key,
            label=f"[{quality} Upload] {upload_target.name}",
            cur_mb=round(cur_mb, 1),
            tot_mb=round(tot_mb, 1),
            pct=pct,
            speed_mb=round(effective_speed, 2),
            eta_str=eta_str,
            status_text=f"Upload: {pct:.1f}% @ {effective_speed:.1f} MB/s" + (f" (ETA: {eta_str})" if eta_str else ""),
            category="tamat" if is_tamat else "ongoing"
        )

    caption = (
        f"🎬 **{anime_title}** - Episode {episode_num}\n\n"
        f"📺 Resolusi: {quality} (Cloud Stream)\n"
        f"⚡ Sumber: {source_info}\n"
        f"#Nipnime #AnimeStream #{quality}"
    )

    up_sem = get_upload_semaphore()
    tot_file_mb = round(upload_target.stat().st_size / (1024 * 1024), 1) if upload_target.exists() else 1.0

    global _IS_UPLOADING_BYTES
    _IS_UPLOADING_BYTES = True
    try:
        async with up_sem:
            async with ClusterUploadLock(upload_target.name, quality, tot_file_mb):
                try:
                    for attempt in range(4):
                        try:
                            message = await client.send_video(
                                chat_id=int(CHANNEL_ID),
                                video=str(upload_target),
                                caption=caption,
                                supports_streaming=True,
                                progress=progress_callback
                            )
                            PROGRESS_MGR.remove(up_task_key)
                            log("UPLOAD", f"✓ Berhasil diunggah ke Telegram! Message ID: {message.id}", GREEN)
                            _watermark_test_count += 1
                            return message.id
                        except Exception as ue:
                            err_type = type(ue).__name__
                            if 'FloodWait' in err_type or hasattr(ue, 'value'):
                                wait_sec = getattr(ue, 'value', 15) + 1
                                log("FLOOD_WAIT", f"⏳ Rate limit Telegram (FloodWait). Menunggu {wait_sec}s sebelum coba ulang...", YELLOW)
                                await asyncio.sleep(wait_sec)
                                continue
                            PROGRESS_MGR.remove(up_task_key)
                            raise ue
                    PROGRESS_MGR.remove(up_task_key)
                    return None
                finally:
                    # Hapus file watermark sementara agar disk Colab / server tetap bersih
                    if is_temp_wm and upload_target.exists():
                        try:
                            upload_target.unlink()
                        except Exception:
                            pass
    finally:
        _IS_UPLOADING_BYTES = False

async def submit_to_nipnime(session: aiohttp.ClientSession, episode_id: int, quality: str, message_id: int, old_msg_ids: list = None, anime_title: str = "", ep_num: any = "", server_name_custom: str = None, dont_exit: bool = False, overwrite: bool = True) -> bool:
    if message_id == -999:
        log("API", f"📦 [Relay Delegation] Video {anime_title} Ep {ep_num} [{quality}] diserahkan ke CasaOS untuk upload Telegram & publikasi.", GREEN)
        return True

    submit_url = f"{API_URL}/submit"
    headers = {'X-Terop-Token': WORKER_TOKEN, 'Accept': 'application/json'}
    default_server_name = f"Nipnime Stream [Cloud {quality}]"
    server_name = server_name_custom or default_server_name
    payload = {
        'episode_id': episode_id,
        'source': 'telegram',
        'server_name': server_name,
        'url': f"{STREAM_BASE_URL}/{message_id}",
        'quality': quality,
        'audio_type': 'sub',
        'overwrite': overwrite
    }
    if old_msg_ids:
        payload['old_msg_ids'] = old_msg_ids

    sub_ok = False
    try:
        s_status, data = await async_request_nipnime_api('POST', submit_url, payload, headers=headers, timeout=15)
        if s_status == 200 and isinstance(data, dict) and data.get('success'):
            log("API", f"✓ Tersimpan di Nipnime: {server_name}", GREEN)
            sub_ok = True
        else:
            async with session.post(submit_url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get('success'):
                    log("API", f"✓ Tersimpan di Nipnime: {server_name}", GREEN)
                    sub_ok = True
                else:
                    log("API", f"Gagal submit ke Nipnime: {data}", RED)
    except Exception as e:
        log("API", f"Exception submit: {e}", RED)

    if dont_exit:
        return sub_ok

    # Logika Penghenti Mode Uji Coba (Bisa 1 video atau N video sesuai batas MAX_TEST_COUNT)
    if MAX_TEST_COUNT > 0 and _watermark_test_count >= MAX_TEST_COUNT:
        print()
        log("TEST_DONE", "==================================================================", BOLD + GREEN)
        log("TEST_DONE", f"🎉 [UJI COBA BATCH {MAX_TEST_COUNT} VIDEO SELESAI]", BOLD + GREEN)
        log("TEST_DONE", f"✓ Total {_watermark_test_count} video telah sukses diproses & diunggah ke Telegram!", GREEN)
        log("TEST_DONE", "✓ Watermark NIPNIME.COM + Pembersih Logo luar aktif", GREEN)
        log("TEST_DONE", "✓ Tersedia opsi 'Nipnime Stream [Cloud 2K QHD]' untuk resolusi 1080p!", GREEN)
        log("TEST_DONE", f"🛑 Worker berhenti otomatis sesuai batas uji coba ({MAX_TEST_COUNT} video).", BOLD + YELLOW)
        log("TEST_DONE", "Silakan periksa channel Telegram & web Nipnime untuk melihat hasil!", BOLD + GREEN)
        log("TEST_DONE", "==================================================================", BOLD + GREEN)
        print()
        await asyncio.sleep(2)
        os._exit(0)
    elif WATERMARK_SINGLE_TEST and _watermark_test_count >= 1 and MAX_TEST_COUNT == 0:
        print()
        log("WATERMARK_TEST", "==================================================================", BOLD + GREEN)
        log("WATERMARK_TEST", "🎉 [UJI COBA 1 VIDEO BERHASIL]", BOLD + GREEN)
        if anime_title:
            log("WATERMARK_TEST", f"🎬 Judul  : {anime_title} Episode {ep_num} [{quality}]", GREEN)
        log("WATERMARK_TEST", "✨ Desain : Montserrat-Black (900) Extra Bold White@0.75 + Soft Shadow", GREEN)
        log("WATERMARK_TEST", f"📱 Telegram Msg ID : {message_id} (Channel: {CHANNEL_ID})", GREEN)
        log("WATERMARK_TEST", f"🌐 Nipnime Stream  : {STREAM_BASE_URL}/{message_id}", CYAN)
        log("WATERMARK_TEST", "🛑 Mode uji coba 1 video selesai! Worker berhenti otomatis.", BOLD + YELLOW)
        log("WATERMARK_TEST", "Silakan cek video di Telegram atau web Nipnime untuk mengevaluasi hasil!", BOLD + GREEN)
        log("WATERMARK_TEST", "==================================================================", BOLD + GREEN)
        print()
        await asyncio.sleep(2)
        os._exit(0)

    return sub_ok

async def maybe_upscale_and_upload_2k(tg_client: Client, session: aiohttp.ClientSession, file_path: Path, anime_title: str, ep_num: any, episode_id: int, source_info: str, completed_qualities: set = None) -> bool:
    """Otomatis meng-upscale master 1080p lokal ke 2K QHD (2560x1440) Lanczos + Unsharp dan upload ke Telegram."""
    role = get_device_role()
    force_server_wm = os.getenv('FORCE_SERVER_WATERMARK', 'false').lower() in ('true', '1', 'yes')
    if role == "server" and not force_server_wm:
        log("2K_SKIP", f"⚡ Server CasaOS: Upscale 2K dilewati untuk menghemat CPU server. Fitur 2K Upscale khusus untuk Google Colab & Laptop (GPU).", GRAY)
        return False

    if not ENABLE_2K_UPSCALE:
        return False
    if completed_qualities is not None and ('1440p' in completed_qualities or '2k' in completed_qualities):
        return False
    try:
        log("2K_UPSCALE", f"🚀 Menghasilkan versi 2K QHD (2560x1440) dari 1080p untuk {anime_title} Ep {ep_num}...", CYAN)
        msg_id_2k = await upload_video_to_telegram(tg_client, file_path, anime_title, ep_num, '2K QHD', f"{source_info} [2K Upscale]", episode_id=episode_id)
        if msg_id_2k:
            await submit_to_nipnime(session, episode_id, '1440p', msg_id_2k, anime_title=anime_title, ep_num=ep_num, server_name_custom="Nipnime Stream [Cloud 2K QHD]")
            if completed_qualities is not None:
                completed_qualities.add('1440p')
                completed_qualities.add('2k')
            log("2K_UPSCALE", f"✓ Versi 2K QHD tersimpan di Nipnime: Nipnime Stream [Cloud 2K QHD] (Msg ID: {msg_id_2k})", GREEN)
            return True
    except Exception as e_2k:
        log("2K_WARN", f"Gagal membuat versi 2K QHD untuk {anime_title} Ep {ep_num}: {e_2k}", YELLOW)
    return False

async def download_video_from_telegram(client: Client, message_id: int, dest_file: Path) -> bool:
    """Mengunduh video master 1080p langsung dari Telegram MTProto atau Nipnime Stream Gateway (HTTP)."""
    task_key = f"tg_dl_{message_id}"

    # 1. Jalur Utama: MTProto Pyrogram Multi-Session jika client terhubung
    if client and getattr(client, 'is_connected', False):
        try:
            log("TG_DOWNLOAD", f"📥 Mengunduh master 1080p dari Telegram (Message ID: {message_id}) [Mode Turbo Multi-Session]...", CYAN)
            channel = int(CHANNEL_ID)
            msg = await client.get_messages(channel, message_ids=message_id)
            if msg and (msg.video or msg.document):
                media = msg.video or msg.document
                total_media_size = getattr(media, 'file_size', 0) or 0
                def _prog(cur, tot):
                    cur_mb = cur / (1024 * 1024)
                    tot_mb = tot / (1024 * 1024)
                    pct = int((cur / tot) * 100) if tot > 0 else 0
                    PROGRESS_MGR.update(
                        key=task_key,
                        label=f"[Telegram 1080p Master] {dest_file.name}",
                        cur_mb=cur_mb,
                        tot_mb=tot_mb,
                        status_text=f"Turbo Unduh TG: {pct}% ({cur_mb:.1f}/{tot_mb:.1f} MB)"
                    )

                PROGRESS_MGR.update(
                    key=task_key,
                    label=f"[Telegram 1080p Master] {dest_file.name}",
                    cur_mb=0.0,
                    tot_mb=round(total_media_size / (1024 * 1024), 1) if total_media_size else 1.0,
                    status_text="Menghubungkan ke Telegram..."
                )
                try:
                    ok_dl = await turbo_download_file(client, media, dest_file, progress=_prog)
                    if ok_dl and dest_file.exists() and dest_file.stat().st_size > 2 * 1024 * 1024:
                        f_mb = dest_file.stat().st_size / (1024 * 1024)
                        log("TG_DONE", f"✓ Master 1080p berhasil diunduh via Turbo ({f_mb:.1f} MB)!", GREEN)
                        return True
                    else:
                        log("TG_DL_ERR", "Unduhan via MTProto tidak lengkap. Beralih ke Nipnime Stream Gateway...", YELLOW)
                finally:
                    PROGRESS_MGR.remove(task_key)
        except Exception as e:
            PROGRESS_MGR.remove(task_key)
            log("TG_DL_ERR", f"Gagal mengunduh via MTProto ({e}). Beralih ke Nipnime Stream Gateway...", YELLOW)

    # 2. Jalur Alternatif Kuat & Cepat: Unduh via Nipnime Stream Gateway (Anti-FLOOD_WAIT)
    try:
        stream_url = f"{STREAM_BASE_URL}/{message_id}"
        log("STREAM_GATEWAY", f"🌐 Mengunduh master 1080p dari Nipnime Stream Gateway ({stream_url})...", CYAN)
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        ok_stream = await download_file(stream_url, dest_file, "1080p", min_speed_mb=0.3)
        if ok_stream and dest_file.exists() and dest_file.stat().st_size > 2 * 1024 * 1024:
            f_mb = dest_file.stat().st_size / (1024 * 1024)
            log("TG_DONE", f"✓ Master 1080p berhasil diunduh via Nipnime Stream Gateway ({f_mb:.1f} MB)!", GREEN)
            return True
    except Exception as se:
        log("STREAM_GATEWAY_ERR", f"Gagal unduh dari Stream Gateway: {se}", YELLOW)

    return False

async def _do_ensure_2k_upscale(
    tg_client: Client,
    session: aiohttp.ClientSession,
    anime_title: str,
    ep_num: any,
    episode_id: int,
    completed: set,
    found_qualities: dict = None,
    failed_urls: dict = None,
    tg_servers: dict = None,
    source: str = "Unknown"
) -> bool:
    """
    Eksekutor Render 2K QHD sebenarnya (berjalan di Background Worker GPU).
    Memproses master 1080p lalu meng-upscale ke 2K QHD (2560x1440) Lanczos secara asynchronous.
    """
    if not is_2k_required():
        return False
    has_2k = '2k' in completed or '1440p' in completed
    if has_2k:
        return True
    if '1080p' not in completed and not (found_qualities and '1080p' in found_qualities):
        return False

    slug = safe_file_slug(anime_title, 50)
    dest_1080 = TEMP_DOWNLOAD_DIR / f"{slug}_ep{ep_num}_1080p_for_2k.mp4"
    obtained = False
    src_info = f"{source} - Auto 2K Upscale"

    # Jalur 1: Unduh dari direct link scraper jika tersedia di found_qualities
    if found_qualities and '1080p' in found_qualities:
        q_data = found_qualities['1080p']
        u = q_data.get('url', '')
        if u and not (failed_urls and is_url_on_cooldown(failed_urls, u)):
            log("2K_SOURCE", f"⚡ Mengunduh 1080p dari {q_data.get('source', source)} ({q_data.get('host', 'Direct')}) untuk 2K Upscale...", CYAN)
            ok_dl = await download_file(u, dest_1080, '1080p', min_speed_mb=0.8, backup_urls=q_data.get('backup_urls'))
            if ok_dl and dest_1080.exists():
                obtained = True
                src_info = f"{q_data.get('source', source)} ({q_data.get('host', 'Direct')}) - 2K Upscale"

    # Jalur 1.5: Query match-title jika tg_servers belum lengkap untuk mendapatkan msg_id
    if not obtained and (not tg_servers or '1080p' not in tg_servers or not tg_servers['1080p'].get('msg_id')):
        try:
            chk_url = f"{API_URL}/match-title"
            headers = {'X-Terop-Token': WORKER_TOKEN, 'Accept': 'application/json'}
            payload = {'title': f"{anime_title} Episode {ep_num}", 'auto_create_episode': False, 'episode_number': ep_num}
            c_status, chk_data = await async_request_nipnime_api('POST', chk_url, payload, headers=headers, timeout=10)
            if c_status != 200 or not isinstance(chk_data, dict):
                async with session.post(chk_url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as chk_resp:
                    if chk_resp.status == 200:
                        chk_data = await chk_resp.json()
            if isinstance(chk_data, dict):
                ep_obj = chk_data.get('episode') or {}
                tg_servers = ep_obj.get('telegram_servers', {}) or {}
        except Exception:
            pass

    # Jalur 2: Jika dari scraper tidak ada atau gagal, unduh langsung dari channel Telegram Nipnime
    if not obtained and tg_servers and '1080p' in tg_servers and tg_servers['1080p'].get('msg_id'):
        tg_msg_id = tg_servers['1080p']['msg_id']
        ok_tg = await download_video_from_telegram(tg_client, tg_msg_id, dest_1080)
        if ok_tg and dest_1080.exists():
            obtained = True
            src_info = f"Telegram CDN (Msg ID: {tg_msg_id}) - 2K Upscale"

    # Jalur 3: Jika masih belum ada, coba cek video server Fast 1080p di Nipnime
    if not obtained and tg_servers and '1080p' in tg_servers and tg_servers['1080p'].get('embed_url'):
        fast_u = tg_servers['1080p']['embed_url']
        if '/storage/videos/episodes/' in fast_u:
            ok_dl = await download_file(fast_u, dest_1080, '1080p', min_speed_mb=0.8)
            if ok_dl and dest_1080.exists():
                obtained = True
                src_info = "Nipnime Fast Storage - 2K Upscale"

    if obtained and dest_1080.exists():
        try:
            ok_2k = await maybe_upscale_and_upload_2k(tg_client, session, dest_1080, anime_title, ep_num, episode_id, src_info, completed)
            if ok_2k:
                completed.add('2k')
                completed.add('1440p')
                return True
        finally:
            if dest_1080.exists():
                try: dest_1080.unlink()
                except Exception: pass

    return False

def should_worker_upscale_2k_locally() -> bool:
    """
    Evaluasi Keputusan di Worker A (PRD Section 5.1):
    - Jika role == 'server' dan tidak ada GPU -> False (CasaOS Guard)
    - Jika sisa disk < 15.0 GB -> False (Lempar ke worker disk banyak)
    - Jika antrean render GPU > 0 -> False (Worker masih sibuk memproses render lain)
    - Jika sedang ada tugas download/ekstrak aktif > 1 -> False
    - Selain itu -> True (Upscale 2K langsung lokal)
    """
    role = get_device_role()
    if role == "server" and not check_has_nvenc():
        return False

    free_gb = get_disk_free_mb() / 1024.0
    if free_gb < 15.0:
        return False

    try:
        q = get_render_queue()
        if q and q.qsize() > 0:
            return False
    except Exception:
        pass

    try:
        if 'PROGRESS_MGR' in globals() and PROGRESS_MGR:
            active_cnt = len(PROGRESS_MGR.tasks)
            if active_cnt > 1:
                return False
    except Exception:
        pass

    return True

async def _process_bg_watermark_upgrade(tg_client: Client, session: aiohttp.ClientSession, job: dict):
    """Memproses antrean render branding watermark resmi & 2K QHD di background worker GPU."""
    staged_file: Path = job['staged_file']
    q = job['quality']
    episode_id = job['episode_id']
    raw_msg_id = job['raw_msg_id']
    anime_title = job['anime_title']
    ep_num = job['ep_num']
    src_info = job['src_info']
    is_2k_candidate = job.get('is_2k_candidate', False)
    completed_qualities = job.get('completed_qualities')

    try:
        if not staged_file.exists():
            # Jika file staging di disk tidak ada (misal akibat worker di-stop / runtime Colab restart),
            # unduh langsung file video mentah (Fast Raw) dari Telegram CDN menggunakan raw_msg_id!
            if raw_msg_id:
                log("BG_RECOVER", f"📥 File staging lokal tidak ditemukan. Mengunduh video mentah [{q}] dari Telegram CDN (Msg ID: {raw_msg_id}) untuk render watermark...", CYAN)
                staged_file = TEMP_DOWNLOAD_DIR / f"raw_rec_{safe_file_slug(anime_title, 40)}_ep{ep_num}_{q}.mp4"
                ok_rec = await download_video_from_telegram(tg_client, raw_msg_id, staged_file)
                if not ok_rec or not staged_file.exists():
                    log("BG_RENDER_ERR", f"Gagal memulihkan video mentah dari Telegram CDN untuk {anime_title} Ep {ep_num} [{q}]", RED)
                    return
            else:
                log("BG_RENDER_ERR", f"File sumber render tidak ditemukan di disk: {staged_file.name}", RED)
                return

        log("BG_RENDER", f"🎨 [GPU WORKER] Merender watermark resmi Nipnime untuk {anime_title} Ep {ep_num} [{q}]...", CYAN)
        wm_file = await apply_nipnime_watermark(staged_file, q, src_info)
        if wm_file and wm_file.exists() and wm_file != staged_file:
            log("BG_UPLOAD", f"📤 [GPU WORKER] Mengunggah versi render berwatermark [{q}] ke Telegram...", CYAN)
            wm_msg_id = await upload_video_to_telegram(tg_client, wm_file, anime_title, ep_num, q, f"{src_info} [Nipnime Watermarked]", skip_watermark=True, episode_id=episode_id)
            if wm_msg_id:
                # Ganti / upgrade link video di web Nipnime secara mulus tanpa mengganggu penonton
                await submit_to_nipnime(session, episode_id, q, wm_msg_id, old_msg_ids=[raw_msg_id], anime_title=anime_title, ep_num=ep_num, dont_exit=is_2k_candidate)
                log("BG_DONE", f"✓ [UPGRADE SELESAI] Video {anime_title} Ep {ep_num} [{q}] di web berhasil diganti dengan versi Resmi Berwatermark!", BOLD + GREEN)
                # Bersihkan status pending_watermark dari state karena render sudah selesai
                try:
                    s_key = f"{normalize_title(anime_title)}:{ep_num}"
                    g_st = load_ongoing_state()
                    if s_key in g_st and 'pending_watermarks' in g_st[s_key]:
                        g_st[s_key]['pending_watermarks'].pop(q, None)
                        if not g_st[s_key]['pending_watermarks']:
                            g_st[s_key].pop('pending_watermarks', None)
                        save_ongoing_state(g_st)
                except Exception:
                    pass
            if wm_file.exists():
                try: wm_file.unlink()
                except Exception: pass

        # Jika resolusi 1080p, evaluasi: Langsung Upscale Lokal vs Lempar ke Worker Disk Banyak (PRD Section 5)
        if is_2k_candidate and staged_file.exists():
            should_local = should_worker_upscale_2k_locally()
            if should_local:
                job_key_2k = f"2k_{episode_id}_{ep_num}"
                if not is_render_queued_or_active(job_key_2k):
                    claimed_2k = True
                    if session:
                        claimed_2k = await claim_episode_lock(session, f"{anime_title} [2K]", ep_num, episode_id, ttl=2400)
                    if claimed_2k:
                        staged_2k_file = staged_file.with_name(f"stage2k_{staged_file.stem[:50]}{staged_file.suffix}")
                        try:
                            staged_file.rename(staged_2k_file)
                        except Exception:
                            staged_2k_file = staged_file

                        await enqueue_render_job({
                            'type': '2k_upscale_staged',
                            'key': job_key_2k,
                            'label': f"[2K QHD Lanczos] {anime_title} Ep {ep_num}",
                            'staged_file': staged_2k_file,
                            'anime_title': anime_title,
                            'ep_num': ep_num,
                            'episode_id': episode_id,
                            'src_info': src_info,
                            'completed_qualities': completed_qualities
                        }, priority=2)
                        staged_file = Path('/dev/null')
            else:
                # Worker sibuk tugas lain / disk sempit (<15GB) / CasaOS CPU:
                # LEMPAR KE WORKER LAIN YANG DISKNYA BANYAK VIA TELEGRAM CDN
                log("2K_HANDOVER", f"🚀 Worker sibuk/disk sempit. Mendelegasikan 2K {anime_title} Ep {ep_num} ke cluster...", BOLD + CYAN)
                anime_obj = {'id': episode_id, 'title': anime_title, 'slug': normalize_title(anime_title).replace(' ', '-')}
                await delegate_2k_handover(session, anime_obj, ep_num, episode_id, raw_msg_id)
                # Langsung bersihkan file 1080p lokal agar disk langsung bebas!
                try: staged_file.unlink()
                except Exception: pass
                staged_file = Path('/dev/null')
    except Exception as e:
        log("BG_RENDER_WARN", f"Kendala saat render upgrade {anime_title} Ep {ep_num}: {e}", YELLOW)
    finally:
        if staged_file.exists() and str(staged_file) != '/dev/null':
            try: staged_file.unlink()
            except Exception: pass

async def _process_bg_2k_upscale_staged(tg_client: Client, session: aiohttp.ClientSession, job: dict):
    """Memproses antrean 2K upscale menggunakan file lokal 1080p yang sudah tersedia dari rilis baru."""
    staged_file: Path = job['staged_file']
    anime_title = job['anime_title']
    ep_num = job['ep_num']
    episode_id = job['episode_id']
    src_info = job['src_info']
    completed_qualities = job.get('completed_qualities')

    try:
        if not staged_file.exists() or str(staged_file) == '/dev/null':
            log("BG_2K_ERR", f"File sumber 1080p untuk 2K tidak ditemukan di disk: {staged_file.name}", RED)
            return

        log("BG_2K", f"🚀 [GPU WORKER] Memulai 2K Lanczos AI Upscale dari file lokal untuk {anime_title} Ep {ep_num}...", CYAN)
        ok_2k = await maybe_upscale_and_upload_2k(tg_client, session, staged_file, anime_title, ep_num, episode_id, src_info, completed_qualities)
        if ok_2k:
            if completed_qualities is not None:
                completed_qualities.add('2k')
                completed_qualities.add('1440p')
            log("BG_2K_DONE", f"✓ [2K SELESAI] {anime_title} Ep {ep_num} versi 2K QHD berhasil dibuat & tayang di web!", BOLD + GREEN)
            try: update_heartbeat(status="running")
            except Exception: pass
    except Exception as e:
        log("BG_2K_ERR", f"Kendala saat 2K upscale {anime_title} Ep {ep_num}: {e}", RED)
    finally:
        if session:
            await release_episode_lock(session, f"{anime_title} [2K]", ep_num)
        if staged_file.exists() and str(staged_file) != '/dev/null':
            try: staged_file.unlink()
            except Exception: pass

async def _process_bg_2k_upscale(tg_client: Client, session: aiohttp.ClientSession, job: dict):
    """Memproses antrean 2K upscale (backfill / anime tamat) di background worker GPU."""
    anime_title = job['anime_title']
    ep_num = job['ep_num']
    episode_id = job['episode_id']
    completed = job.get('completed', set())
    found_qualities = job.get('found_qualities')
    failed_urls = job.get('failed_urls')
    tg_servers = job.get('tg_servers')
    source = job.get('source', 'Background')
    item = job.get('item')
    state = job.get('state')
    state_lock = job.get('state_lock')
    is_tamat = job.get('is_tamat', False)

    try:
        log("BG_2K", f"🚀 [GPU WORKER] Memproses 2K Upscale dari Antrean untuk {anime_title} Ep {ep_num}...", CYAN)
        ok_2k = await _do_ensure_2k_upscale(
            tg_client, session, anime_title, ep_num, episode_id,
            completed, found_qualities, failed_urls, tg_servers, source
        )
        if ok_2k:
            completed.add('2k')
            completed.add('1440p')
            if item is not None:
                if is_tamat:
                    item.pop('retry_after', None)
                    failed_eps = item.get('failed_eps')
                    if isinstance(failed_eps, dict):
                        failed_eps.pop(str(ep_num), None)
                    c_eps = set(item.get('completed_eps', []))
                    c_eps.add(ep_num)
                    item['completed_eps'] = sorted(list(c_eps))
                    item['last_checked_ep'] = max(item.get('last_checked_ep', 0), ep_num)
                    if state:
                        save_completed_state(state)
                else:
                    item['completed_qualities'] = list(completed)
                    target_q = get_target_qualities()
                    rem = [mq for mq in target_q if mq not in completed]
                    item['missing_qualities'] = rem
                    if not rem:
                        item['status'] = 'complete'
                    if state:
                        if state_lock:
                            async with state_lock:
                                save_ongoing_state(state)
                        else:
                            save_ongoing_state(state)
            log("BG_2K_DONE", f"✓ [2K SELESAI] {anime_title} Ep {ep_num} versi 2K QHD berhasil dibuat & tayang di web!", BOLD + GREEN)
            try: update_heartbeat(status="running")
            except Exception: pass
        else:
            log("BG_2K_FAIL", f"⚠️ Versi 2K untuk {anime_title} Ep {ep_num} belum berhasil dibuat (sumber 1080p belum siap/gagal unduh). Diberi jeda 30 menit...", YELLOW)
            if item is not None:
                if 'failed_2k_eps' not in item or not isinstance(item['failed_2k_eps'], dict):
                    item['failed_2k_eps'] = {}
                item['failed_2k_eps'][str(ep_num)] = time.time() + 1800
                if state:
                    if is_tamat:
                        save_completed_state(state)
                    else:
                        if state_lock:
                            async with state_lock:
                                save_ongoing_state(state)
                        else:
                            save_ongoing_state(state)
    finally:
        if session:
            await release_episode_lock(session, f"{anime_title} [2K]", ep_num)
            await release_episode_lock(session, anime_title, ep_num)

async def background_render_worker(tg_client: Client, session: aiohttp.ClientSession):
    """
    Worker Latar Belakang Mandiri (Independent Background GPU Render Worker):
    Berjalan secara non-blocking di samping loop utama scraper.
    Mengambil tugas dari _RENDER_QUEUE berdasarkan prioritas (PriorityQueue):
      - Prio 1: Watermark Branding rilis baru (15-25 detik per episode) -> Langsung tayang resmi!
      - Prio 2: 2K Upscale rilis ongoing baru (Lanczos QHD)
      - Prio 3: 2K Upscale backfill episode lama & anime tamat
    Loop scraper utama TIDAK PERNAH terblokir atau menunggu proses render!
    """
    queue = get_render_queue()
    log("BG_RENDER", "🚀 Background Render Worker (GPU Priority Pipeline) aktif dan siap memproses antrean...", BOLD + GREEN)
    while True:
        job = None
        try:
            prio, seq, job = await queue.get()
            job_type = job.get('type')
            job_key = job.get('key')
            label = job.get('label', job_key)

            prio_labels = {1: "⚡ Watermark Kilat", 2: "🚀 2K Rilis Baru", 3: "⏳ 2K Backfill"}
            prio_tag = prio_labels.get(prio, f"Prio {prio}")
            log("BG_RENDER", f"▶ Memulai pengerjaan render GPU [{prio_tag}]: {label}", BOLD + CYAN)

            global _IS_RENDERING_ACTIVE
            _IS_RENDERING_ACTIVE = True
            try:
                if job_type == 'watermark_upgrade':
                    await _process_bg_watermark_upgrade(tg_client, session, job)
                elif job_type == '2k_upscale_staged':
                    await _process_bg_2k_upscale_staged(tg_client, session, job)
                elif job_type == '2k_upscale':
                    await _process_bg_2k_upscale(tg_client, session, job)
                else:
                    log("BG_RENDER_WARN", f"Tipe pekerjaan render tidak dikenal: {job_type}", YELLOW)
            finally:
                _IS_RENDERING_ACTIVE = False

        except asyncio.CancelledError:
            log("BG_RENDER", "Background Render Worker dihentikan.", GRAY)
            break
        except Exception as e:
            log("BG_RENDER_ERR", f"Kesalahan pada Background Render Worker: {e}", RED)
        finally:
            if job and 'key' in job:
                _QUEUED_RENDER_KEYS.discard(job['key'])
            if job:
                queue.task_done()

async def recover_pending_watermarks(tg_client: Client, session: aiohttp.ClientSession, state: dict) -> int:
    """
    Sistem Pemulih Otomatis (Auto-Resume & State Recovery):
    Jika worker di-stop lalu dijalankan lagi, fungsi ini secara otomatis mendeteksi episode
    yang baru tayang versi raw di web dan memasukkan tugas render watermark-nya kembali ke Priority 1!
    """
    if not check_has_nvenc():
        log("RECOVER_SKIP", "ℹ️ Mesin CPU/VPS: Pemulihan antrean watermark dilewati agar disk tidak terisi unduhan Telegram CDN. Tugas render ditangani oleh worker GPU.", GRAY)
        return 0
    recovered = 0
    for k, v in list(state.items()):
        pending_wm = v.get('pending_watermarks')
        if not pending_wm or not isinstance(pending_wm, dict):
            continue
        ep_num = v.get('episode_number', 1)
        if not is_episode_in_shard(ep_num):
            continue
        anime_title = v.get('anime_title', '')
        episode_id = v.get('episode_id')
        completed = set(v.get('completed_qualities', []))
        for q, info in list(pending_wm.items()):
            job_key = f"wm_{episode_id}_{q.lower()}"
            if is_render_queued_or_active(job_key):
                continue
            staged_path = Path(info.get('staged_file', ''))
            is_2k_cand = (q.lower() == '1080p' and is_2k_required())
            log("RECOVER_WM", f"🔄 Melanjutkan render watermark untuk {anime_title} Ep {ep_num} [{q}] (Auto-Resume)...", CYAN)
            await enqueue_render_job({
                'type': 'watermark_upgrade',
                'key': job_key,
                'label': f"[Watermark {q}] {anime_title} Ep {ep_num}",
                'staged_file': staged_path,
                'anime_title': anime_title,
                'ep_num': ep_num,
                'episode_id': episode_id,
                'quality': q,
                'raw_msg_id': info.get('raw_msg_id'),
                'src_info': info.get('src_info', 'Fast Raw Recovered'),
                'is_2k_candidate': is_2k_cand,
                'completed_qualities': completed
            }, priority=1)
            recovered += 1
    if recovered:
        log("RECOVER_WM", f"✓ Berhasil memulihkan {recovered} antrean render watermark dari sesi sebelumnya!", BOLD + GREEN)
    return recovered

async def ensure_2k_upscale_for_episode(
    tg_client: Client,
    session: aiohttp.ClientSession,
    anime_title: str,
    ep_num: any,
    episode_id: int,
    completed: set,
    found_qualities: dict = None,
    failed_urls: dict = None,
    tg_servers: dict = None,
    source: str = "Unknown",
    item: dict = None,
    state: dict = None,
    state_lock: asyncio.Lock = None,
    is_tamat: bool = False,
    priority: int = 3
) -> bool:
    """
    Memasukkan tugas 2K QHD ke Antrean GPU Latar Belakang (Non-blocking).
    Worker scraper TIDAK AKAN PERNAH terhenti atau menunggu render GPU,
    sehingga proses scanning & perilisan episode anime lain tetap berjalan lancar!
    """
    if not is_2k_required():
        return False
    has_2k = '2k' in completed or '1440p' in completed
    if has_2k:
        return True
    if '1080p' not in completed and not (found_qualities and '1080p' in found_qualities):
        return False

    if item is not None and isinstance(item.get('failed_2k_eps'), dict):
        cd = item['failed_2k_eps'].get(str(ep_num), 0)
        if cd > time.time():
            return False

    job_key = f"2k_{episode_id}_{ep_num}"
    if is_render_queued_or_active(job_key):
        return False

    if session:
        claimed_2k = await claim_episode_lock(session, f"{anime_title} [2K]", ep_num, episode_id, ttl=2400)
        if not claimed_2k:
            return False

    return await enqueue_render_job({
        'type': '2k_upscale',
        'key': job_key,
        'label': f"[2K QHD] {anime_title} Ep {ep_num}",
        'anime_title': anime_title,
        'ep_num': ep_num,
        'episode_id': episode_id,
        'completed': completed,
        'found_qualities': found_qualities,
        'failed_urls': failed_urls,
        'tg_servers': tg_servers,
        'source': source,
        'item': item,
        'state': state,
        'state_lock': state_lock,
        'is_tamat': is_tamat
    }, priority=priority)

async def upload_and_process_two_stage(
    tg_client: Client,
    session: aiohttp.ClientSession,
    dest_file: Path,
    anime_title: str,
    ep_num: any,
    episode_id: int,
    quality: str,
    src_info: str,
    completed_qualities: set = None,
    on_raw_registered_callback = None,
    is_tamat: bool = False
) -> int:
    """
    Sistem Rilis Dua Tahap Non-Blocking (Two-Stage Fast Release & Async Render Pipeline):
    1. Tahap 1 (Rilis Kilat): Upload video mentah/raw LANGSUNG ke Telegram & daftarkan ke Nipnime agar video tayang di web dalam hitungan detik!
    2. Tahap 2 & 3 (Antrean Render GPU Latar Belakang): Sementara video mentah sudah ditonton pengunjung di web, tugas render watermark & 2K
       dimasukkan ke antrean GPU latar belakang (_RENDER_QUEUE). Worker utama TIDAK PERNAH MENUNGGU RENDER dan langsung bebas mencari episode baru!
    """
    global FAST_RELEASE_FIRST, ENABLE_WATERMARK, ENABLE_2K_UPSCALE, _RELAY_UPLOAD_MODE
    q = quality
    is_2k_candidate = (q.lower() == '1080p' and is_2k_required() and q.lower() != '2k qhd')

    if _RELAY_UPLOAD_MODE:
        # Jalur Relay Worker (Warnet GPU): Render watermark langsung dengan GPU lokal (NVENC),
        # lalu delegasikan hasil render akhir ke server CasaOS via HTTPS agar tidak memboroskan bandwidth upload 2x!
        msg_id = await upload_video_to_telegram(tg_client, dest_file, anime_title, ep_num, q, src_info, episode_id=episode_id)
        if msg_id:
            await submit_to_nipnime(session, episode_id, q, msg_id, anime_title=anime_title, ep_num=ep_num, dont_exit=is_2k_candidate)
            if completed_qualities is not None:
                completed_qualities.add(q)
            if on_raw_registered_callback:
                try:
                    on_raw_registered_callback()
                except Exception:
                    pass
            if is_2k_candidate:
                ok_2k = await maybe_upscale_and_upload_2k(tg_client, session, dest_file, anime_title, ep_num, episode_id, src_info, completed_qualities)
                if ok_2k and on_raw_registered_callback:
                    try:
                        on_raw_registered_callback()
                    except Exception:
                        pass
            return msg_id
        return None

    # Jika mode 2-Tahap aktif (default) dan Watermark aktif:
    if FAST_RELEASE_FIRST and ENABLE_WATERMARK and q.lower() != '2k qhd':
        # --- TAHAP 1: RILIS KILAT (RAW VIDEO LANGSUNG KE TELEGRAM & WEB) ---
        log("FAST_RELEASE", f"⚡ [TAHAP 1: RILIS KILAT] Mengunggah [{q}] mentah ke Telegram agar web langsung tayang...", BOLD + CYAN)
        raw_msg_id = await upload_video_to_telegram(tg_client, dest_file, anime_title, ep_num, q, f"{src_info} [Fast Raw]", skip_watermark=True, is_tamat=is_tamat, episode_id=episode_id)
        if not raw_msg_id:
            log("FAST_ERR", f"Gagal mengunggah video mentah [{q}] ke Telegram.", RED)
            return None

        # Daftarkan langsung ke Nipnime agar web langsung aktif
        await submit_to_nipnime(session, episode_id, q, raw_msg_id, anime_title=anime_title, ep_num=ep_num, dont_exit=True)
        if completed_qualities is not None:
            completed_qualities.add(q)
        if on_raw_registered_callback:
            try:
                on_raw_registered_callback()
            except Exception:
                pass
        log("FAST_RELEASE", f"🎉 [WEB TAYANG] {anime_title} Ep {ep_num} [{q}] SUDAH TAYANG DI SITUS NIPNIME! Pengunjung bisa langsung streaming.", BOLD + GREEN)

        # --- TAHAP 2 & 3: MASUKKAN KE ANTREAN RENDER GPU LATAR BELAKANG ---
        # Di mesin CPU/VPS atau jika ruang disk terbatas, batasi staging lokal agar tidak menumpuk puluhan GB
        q_curr_size = get_render_queue().qsize()
        has_gpu = check_has_nvenc()
        free_mb = get_disk_free_mb()
        if (not has_gpu and q_curr_size >= 2) or free_mb < 2500:
            log("DISK_GUARD", f"⚡ [HEMAT DISK] Rilis kilat [{q}] sukses & web aktif. Melewati antrean render lokal (Antre: {q_curr_size}, Free: {free_mb:.0f} MB) untuk mencegah disk penuh.", CYAN)
            try:
                if dest_file.exists(): dest_file.unlink()
            except Exception: pass
            return raw_msg_id

        # Pindahkan file ke file staging antrean render agar aman dari pembersihan di blok finally caller
        staged_render_file = dest_file.with_name(f"stage_{dest_file.stem[:50]}_{q.lower()}{dest_file.suffix}")
        try:
            dest_file.rename(staged_render_file)
        except Exception:
            import shutil
            shutil.copy2(dest_file, staged_render_file)
            try: dest_file.unlink()
            except Exception: pass

        job_key = f"wm_{episode_id}_{q.lower()}"
        await enqueue_render_job({
            'type': 'watermark_upgrade',
            'key': job_key,
            'label': f"[Watermark {q}] {anime_title} Ep {ep_num}",
            'staged_file': staged_render_file,
            'anime_title': anime_title,
            'ep_num': ep_num,
            'episode_id': episode_id,
            'quality': q,
            'raw_msg_id': raw_msg_id,
            'src_info': src_info,
            'is_2k_candidate': is_2k_candidate,
            'completed_qualities': completed_qualities,
            'is_tamat': is_tamat
        }, priority=1)

        # Catat di state agar jika worker di-stop / restart, tugas watermark tidak hilang dan bisa di-resume otomatis
        try:
            s_key = f"{normalize_title(anime_title)}:{ep_num}"
            g_st = load_ongoing_state()
            if s_key in g_st:
                pw = g_st[s_key].setdefault('pending_watermarks', {})
                pw[q] = {
                    'raw_msg_id': raw_msg_id,
                    'src_info': src_info,
                    'episode_id': episode_id,
                    'staged_file': str(staged_render_file)
                }
                save_ongoing_state(g_st)
        except Exception:
            pass

        log("FAST_RELEASE", f"🚀 Rilis mentah [{q}] sudah aktif di web! Render branding diserahkan ke Antrean GPU Latar Belakang agar scraper bebas mencari anime lain.", CYAN)
        return raw_msg_id

    else:
        # Jalur reguler (Single-stage: langsung render sebelum upload jika FAST_RELEASE_FIRST dimatikan)
        msg_id = await upload_video_to_telegram(tg_client, dest_file, anime_title, ep_num, q, src_info, episode_id=episode_id)
        if msg_id:
            await submit_to_nipnime(session, episode_id, q, msg_id, anime_title=anime_title, ep_num=ep_num, dont_exit=is_2k_candidate)
            if completed_qualities is not None:
                completed_qualities.add(q)
            if on_raw_registered_callback:
                try:
                    on_raw_registered_callback()
                except Exception:
                    pass
            if is_2k_candidate:
                ok_2k = await maybe_upscale_and_upload_2k(tg_client, session, dest_file, anime_title, ep_num, episode_id, src_info, completed_qualities)
                if ok_2k and on_raw_registered_callback:
                    try:
                        on_raw_registered_callback()
                    except Exception:
                        pass
            return msg_id
        return None

# ==============================================================================
# 4. FIRST RELEASE INGESTION & QUALITY BACKFILL ENGINE
# ==============================================================================
async def process_new_ongoing_release(tg_client: Client, session: aiohttp.ClientSession, release: dict, state: dict):
    if get_device_role() == "server" and has_active_remote_workers():
        return 0
    anime_title = release['anime_title']
    ep_num = release['episode_number']
    source = release['source']
    ep_url = release['episode_url']
    rel_time = release.get('released_at', '')
    anime_slug = release.get('anime_slug', '')

    # Catatan: Seleksi shard sudah dilakukan di dispatcher feed utama.
    # Jangan tolak episode di sini agar gotong royong saat worker nganggur tetap berjalan.

    key = f"{normalize_title(anime_title)}:{ep_num}"
    if key in state:
        st = state[key].get('status')
        retry_after = state[key].get('retry_after', 0)
        if retry_after and time.time() < retry_after:
            return 0
        if st == 'complete':
            return 0
        if st == 'skipped':
            last_chk = state[key].get('last_checked_at', 0)
            if time.time() - last_chk < 7200:
                return 0
        elif st == 'partial':
            last_chk = state[key].get('last_checked_at', 0)
            # Jika masa cooldown baru saja selesai, izinkan langsung jalan
            if not retry_after or time.time() < (retry_after + 60):
                if time.time() - last_chk < 300:
                    return 0
    new_downloaded = 0

    # Cocokkan episode dengan Nipnime database (Auto-Create jika baru rilis)
    match_url = f"{API_URL}/match-title"
    headers = {'X-Terop-Token': WORKER_TOKEN, 'Accept': 'application/json'}
    payload = {'title': f"{anime_title} Episode {ep_num}", 'auto_create_episode': True, 'episode_number': ep_num}
    if anime_slug:
        payload['anime_slug'] = anime_slug

    episode_id = None
    existing_tg_qualities = []
    tg_servers = {}
    missing_previous_eps = []
    try:
        m_status, m_data = await async_request_nipnime_api('POST', match_url, payload, headers=headers, timeout=15)
        if m_status != 200 or not isinstance(m_data, dict):
            async with session.post(match_url, json=payload, headers=headers) as m_resp:
                if m_resp.status == 200:
                    m_data = await m_resp.json()
        if m_data and isinstance(m_data, dict):
            ep_obj = m_data.get('episode')
            if ep_obj:
                episode_id = ep_obj.get('id')
                existing_tg_qualities = ep_obj.get('telegram_qualities', [])
                tg_servers = ep_obj.get('telegram_servers', {})
            missing_previous_eps = m_data.get('missing_previous_episodes', [])
    except Exception as e:
        log("MATCH_WARN", f"Cek judul ke Nipnime gagal: {e}", YELLOW)

    if not episode_id:
        return 0

    # Validasi status anime: Abaikan anime yang sudah tamat/completed atau di-drop oleh admin
    anime_obj = (m_data.get('anime') or {}) if 'm_data' in locals() else {}
    anime_status = (anime_obj.get('status') or '').lower()
    if anime_status != 'ongoing' or ('m_data' in locals() and m_data.get('dropped')):
        if key in state:
            state.pop(key, None)
            save_ongoing_state(state)
        return 0

    # Inisialisasi state jika baru rilis
    if key not in state:
        state[key] = {
            'anime_title': anime_title,
            'episode_number': ep_num,
            'episode_id': episode_id,
            'first_source': source,
            'first_released_at': rel_time,
            'nontonanimeid_slug': anime_slug if source == 'NontonAnimeID' else None,
            'completed_qualities': list(existing_tg_qualities),
            'status': 'partial',
            'created_at': time.time(),
            'last_checked_at': time.time()
        }
        save_ongoing_state(state)

    item = state[key]
    if source == 'NontonAnimeID' and anime_slug:
        item['nontonanimeid_slug'] = anime_slug

    completed = set(item.get('completed_qualities', []))
    if existing_tg_qualities:
        completed.update(existing_tg_qualities)
        item['completed_qualities'] = list(completed)
    else:
        # Jika DB tidak memiliki server telegram (misal episode baru atau baru dibersihkan dari salah season),
        # sinkronkan state agar episode baru yang sah diproses dan menimpa yang lama
        if not existing_tg_qualities and item.get('completed_qualities'):
            item['completed_qualities'] = []
            completed = set()
    target_q = get_target_qualities()
    has_2k = '2k' in completed or '1440p' in completed
    has_fhd_and_hd = '1080p' in completed and '720p' in completed

    is_already_done = False
    if is_2k_required():
        if (has_fhd_and_hd and has_2k) or ('1080p' in completed and has_2k):
            is_already_done = True
    else:
        if set(target_q).issubset(completed) or set(['1080p', '720p', '480p']).issubset(completed) or has_fhd_and_hd:
            is_already_done = True

    if is_already_done:
        item['status'] = 'complete'
        item['missing_qualities'] = [q for q in target_q if q not in completed]
        save_ongoing_state(state)
        return


    print(f"\n{BOLD}{CYAN}{'='*65}{RESET}")
    log("FIRST_RELEASE", f"⚡ RILIS TERCEPAT: {anime_title} Ep {ep_num} rilis duluan di {source}! (Waktu: {rel_time})", BOLD + GREEN)
    print(f"{BOLD}{CYAN}{'='*65}{RESET}")

    # Ekstrak resolusi yang tersedia dari sumber yang baru rilis ini
    if source == 'AnimeSail':
        found_qualities = await extract_qualities_from_animesail(session, ep_url, extra_info=item)
    elif source == 'Kuramanime':
        found_qualities = await extract_qualities_from_kuramanime(session, ep_url)
    elif source == 'Samehadaku':
        found_qualities = await extract_qualities_from_samehadaku(session, ep_url)
    elif source == 'Oploverz':
        found_qualities = await extract_qualities_from_oploverz(session, ep_url)
    elif source == 'Otakudesu':
        found_qualities = await extract_qualities_from_otakudesu(session, ep_url, ep_num)
    else:
        found_qualities = await extract_qualities_from_nontonanimeid(session, ep_url, extra_info=item)

    found_qualities = found_qualities or {}

    # Cek ke seluruh sumber untuk melengkapi resolusi ATAU upgrade ke server CDN super kencang (Kuramadrive 14+ MB/s)
    other_q = await check_episode_on_all_sources(session, anime_title, ep_num, extra_info=item)
    for q, q_data in other_q.items():
        if q not in found_qualities or is_better_source(q_data, found_qualities[q]):
            found_qualities[q] = q_data

    slug = safe_file_slug(anime_title, 50)
    failed_urls = item.get('failed_urls')
    if not isinstance(failed_urls, dict):
        failed_urls = {}
        item['failed_urls'] = failed_urls
    had_failed_dl = False

    active_q_list = [
        (q, q_data) for q, q_data in found_qualities.items()
        if q not in completed and not is_url_on_cooldown(failed_urls, q_data['url'])
    ]

    state_lock = asyncio.Lock()
    async def process_single_q(q, q_data):
        nonlocal new_downloaded, had_failed_dl
        dest_file = TEMP_DOWNLOAD_DIR / f"{slug}_ep{ep_num}_{q}.mp4"
        try:
            log("INGEST", f"Mengunduh resolusi rilis awal [{q}] dari {q_data.get('source', source)} ({q_data.get('host', 'Direct')})...", MAGENTA)
            ok = await download_file(q_data['url'], dest_file, q, min_speed_mb=0.8, backup_urls=q_data.get('backup_urls'))
            if not ok:
                had_failed_dl = True
                record_url_failure(failed_urls, q_data['url'])
                curr_src = q_data.get('source', source)
                alt_sources = await check_episode_on_all_sources(session, anime_title, ep_num, extra_info=item, skip_source=curr_src)
                alt_sources = alt_sources or {}
                if q in alt_sources and alt_sources[q]['url'] != q_data['url']:
                    alt_data = alt_sources[q]
                    alt_url = alt_data['url']
                    if not is_url_on_cooldown(failed_urls, alt_url):
                        log("FALLBACK", f"Mencoba sumber cadangan [{q}] dari {alt_data['source']} ({alt_data.get('host')})...", YELLOW)
                        ok = await download_file(alt_url, dest_file, q, min_speed_mb=0.8)
                        if ok:
                            q_data = alt_data
                            had_failed_dl = False
                        else:
                            record_url_failure(failed_urls, alt_url)
                            log("SKIP", f"⏩ Sumber cadangan [{q}] juga lambat/tidak ada respon. Menunggu 1 jam agar limit hoster reset...", YELLOW)
            if ok and dest_file.exists():
                rw, rh = get_video_dimensions(dest_file)
                min_h = {'1080p': 850, '720p': 550, '480p': 380}.get(q.lower(), 0)
                if rh > 0 and min_h > 0 and rh < min_h:
                    log("RESOLUTION_MISMATCH", f"⚠️ File [{q}] yang diunduh hanya beresolusi riil {rw}x{rh} (jauh di bawah standar {q})! Mencoba sumber alternatif...", YELLOW)
                    ok = False
                    record_url_failure(failed_urls, q_data['url'])
                    curr_src = q_data.get('source', source)
                    alt_sources = await check_episode_on_all_sources(session, anime_title, ep_num, extra_info=item, skip_source=curr_src)
                    alt_sources = alt_sources or {}
                    if q in alt_sources and alt_sources[q]['url'] != q_data['url']:
                        alt_data = alt_sources[q]
                        alt_url = alt_data['url']
                        if not is_url_on_cooldown(failed_urls, alt_url):
                            log("FALLBACK", f"Mencoba sumber cadangan [{q}] dari {alt_data['source']} ({alt_data.get('host')})...", YELLOW)
                            ok = await download_file(alt_url, dest_file, q, min_speed_mb=0.8)
                            if ok and dest_file.exists():
                                rw2, rh2 = get_video_dimensions(dest_file)
                                if rh2 > 0 and min_h > 0 and rh2 < min_h:
                                    ok = False
                                    record_url_failure(failed_urls, alt_url)
                                else:
                                    q_data = alt_data

            if ok and dest_file.exists():
                src_info = f"{q_data.get('source', source)} ({q_data.get('host', 'Direct')}) - Tercepat Rilis"
                def _on_raw_registered():
                    nonlocal new_downloaded
                    new_downloaded += 1
                    item['completed_qualities'] = list(completed)
                    item['last_checked_at'] = time.time()
                    target_q = get_target_qualities()
                    rem = [mq for mq in target_q if mq not in completed]
                    item['missing_qualities'] = rem
                    if not rem:
                        item['status'] = 'complete'
                    save_ongoing_state(state)

                await upload_and_process_two_stage(
                    tg_client, session, dest_file, anime_title, ep_num, episode_id, q, src_info,
                    completed_qualities=completed,
                    on_raw_registered_callback=_on_raw_registered
                )
        finally:
            if dest_file.exists():
                try: dest_file.unlink()
                except Exception: pass

    role = get_device_role()
    is_turbo_mode = (role in ('colab', 'codespace')) and len(active_q_list) > 1

    if is_turbo_mode:
        parallel_count = min(4, len(active_q_list))
        log("TURBO", f"⚡ Memproses {len(active_q_list)} resolusi serentak secara paralel untuk {anime_title} Ep {ep_num} [Turbo {parallel_count}x]...", BOLD + CYAN)
        q_sem = asyncio.Semaphore(parallel_count)
        async def _worker(q, q_d):
            async with q_sem:
                await process_single_q(q, q_d)
        await asyncio.gather(*[_worker(q, q_d) for q, q_d in active_q_list], return_exceptions=True)
    else:
        for q, q_data in active_q_list:
            await process_single_q(q, q_data)

    # Khusus jika 2K Wajib: pastikan versi 2K diproses jika 1080p sudah selesai/tersedia tapi 2K belum ada
    if is_2k_required() and not ('2k' in completed or '1440p' in completed):
        ok_2k = await ensure_2k_upscale_for_episode(
            tg_client, session, anime_title, ep_num, episode_id,
            completed, found_qualities, failed_urls, tg_servers, source, priority=2
        )
        if ok_2k:
            new_downloaded += 1

    item['completed_qualities'] = list(completed)
    item['last_checked_at'] = time.time()
    target_q = get_target_qualities()
    missing = [q for q in target_q if q not in completed]
    item['missing_qualities'] = missing

    # Kriteria kelengkapan rilis
    has_fhd_and_hd = '1080p' in completed and '720p' in completed
    has_2k = '2k' in completed or '1440p' in completed

    if is_2k_required():
        is_major_complete = (has_fhd_and_hd and has_2k) or ('1080p' in completed and has_2k)
    else:
        is_major_complete = set(['1080p', '720p', '480p']).issubset(completed) or has_fhd_and_hd

    is_standard_complete = ('720p' in completed and ('480p' in completed or '360p' in completed))
    # Filter valid_unreleased: hanya untuk resolusi yang memang disediakan scraper (bukan 2k)
    valid_unreleased = [
        mq for mq in missing 
        if mq != '2k' and mq in other_q and not is_url_on_cooldown(failed_urls, other_q[mq]['url'])
    ]
    has_other_sources_unreleased = len(valid_unreleased) > 0

    if not missing or is_major_complete:
        item['status'] = 'complete'
        item['missing_qualities'] = []
        item.pop('retry_after', None)
        log("STATUS", f"✓ RILIS LENGKAP ({', '.join(completed)}) untuk {anime_title} Ep {ep_num}!", GREEN)
    elif had_failed_dl:
        item['status'] = 'partial'
        item['missing_qualities'] = missing
        item['retry_after'] = time.time() + 3600
        log("COOLDOWN", f"⏳ {anime_title} Ep {ep_num}: Unduhan lambat / timeout. Dijadwalkan coba ulang 1 jam lagi...", YELLOW)
    elif missing == ['2k'] and '1080p' in completed:
        # Jika hanya 2k yang belum selesai dan 1080p sudah ada, jangan beri cooldown 1 jam!
        item['status'] = 'partial'
        item['missing_qualities'] = ['2k']
        item.pop('retry_after', None)
        log("WAIT_2K", f"⏳ {anime_title} Ep {ep_num}: Versi 1080p siap, menunggu render 2K GPU...", CYAN)
    elif not has_other_sources_unreleased:
        item['status'] = 'partial'
        item['missing_qualities'] = missing
        if missing != ['2k']:
            item['retry_after'] = time.time() + 3600
        else:
            item.pop('retry_after', None)
        if not found_qualities and not completed:
            log("NO_LINKS", f"⏳ {anime_title} Ep {ep_num}: Belum ada direct link video dari sumber rilis. Dijadwalkan coba ulang 1 jam lagi...", YELLOW)
        elif completed:
            log("WAIT_RESOLUTIONS", f"✓ {anime_title} Ep {ep_num}: Siap ditonton ({', '.join(completed)}). Menunggu 1080p jika dirilis susulan...", CYAN)
        else:
            log("COOLDOWN", f"⏳ {anime_title} Ep {ep_num}: Menunggu sumber rilisan lain. Dijadwalkan coba ulang 1 jam lagi...", YELLOW)
    else:
        item['status'] = 'partial'
        item['missing_qualities'] = missing
        item.pop('retry_after', None)
        log("WAIT_RESOLUTIONS", f"Tersedia: {', '.join(completed)} | Menunggu resolusi susulan: {', '.join(missing)}", YELLOW)

    save_ongoing_state(state)

    # 4. CEK & BACKFILL EPISODE SEBELUMNYA (JIKA EPISODE > 1)
    if ep_num > 1:
        try:
            await check_and_backfill_previous_episodes(
                tg_client, session, anime_title, ep_num, missing_previous_eps, state, extra_info=item
            )
        except Exception as p_err:
            log("PREV_ERR", f"Gagal periksa episode sebelumnya: {p_err}", RED)

    return new_downloaded

async def check_and_backfill_previous_episodes(
    tg_client: Client,
    session: aiohttp.ClientSession,
    anime_title: str,
    current_ep: int,
    missing_from_api: list,
    state: dict,
    extra_info: dict = None
):
    """
    Mengecek apakah episode-episode sebelumnya sudah ada di Nipnime / Telegram.
    Jika episode sebelumnya belum ada, sistem otomatis mencari di 3 sumber,
    mengunduh resolusi yang ada, mengunggah ke Telegram, dan menyetor ke Nipnime.
    """
    if current_ep <= 1:
        return

    # Tentukan nomor episode sebelumnya yang perlu diperiksa
    ep_numbers_to_check = []
    if missing_from_api:
        for m in missing_from_api:
            ep_numbers_to_check.append(int(m.get('episode_number')))
    else:
        # Fallback jika API belum mengirim daftar: cek 1 episode sebelumnya
        if current_ep > 1:
            ep_numbers_to_check.append(current_ep - 1)

    # Ambil episode-episode sebelumnya yang belum lengkap (hingga 5 episode per siklus)
    ep_numbers_to_check = ep_numbers_to_check[:5]
    if WORKER_SHARD not in ('all', 'semua', 'none', '*', ''):
        ep_numbers_to_check = [n for n in ep_numbers_to_check if is_episode_in_shard(n)]

    if not ep_numbers_to_check:
        return

    log("PREV_CHECK", f"🔍 Memeriksa kelengkapan episode sebelumnya ({ep_numbers_to_check}) untuk '{anime_title}'...", BLUE)

    for prev_num in ep_numbers_to_check:
        prev_key = f"{normalize_title(anime_title)}:{prev_num}"

        # Jika di state lokal sudah berstatus complete atau dalam masa cooldown, lewati
        if prev_key in state:
            retry_after = state[prev_key].get('retry_after', 0)
            if retry_after and time.time() < retry_after:
                continue
            st_val = state[prev_key].get('status')
            if st_val == 'complete':
                continue
            if st_val == 'skipped':
                last_chk = state[prev_key].get('last_checked_at', 0)
                if time.time() - last_chk < 7200:
                    continue

        # Cek status ke Nipnime jika belum lengkap di state
        match_url = f"{API_URL}/match-title"
        headers = {'X-Terop-Token': WORKER_TOKEN, 'Accept': 'application/json'}
        match_payload = {
            'title': f"{anime_title} Episode {prev_num}",
            'auto_create_episode': True,
            'episode_number': prev_num
        }

        prev_ep_id = None
        has_tg = False
        existing_qualities = []

        matched_meta = next((m for m in missing_from_api if int(m.get('episode_number', 0)) == prev_num), None)
        if matched_meta and matched_meta.get('episode_id'):
            prev_ep_id = matched_meta['episode_id']
            has_tg = matched_meta.get('has_telegram', False)
            existing_qualities = matched_meta.get('telegram_qualities', [])
        else:
            try:
                m_status, m_data = await async_request_nipnime_api('POST', match_url, match_payload, headers=headers, timeout=15)
                if m_status != 200 or not isinstance(m_data, dict):
                    async with session.post(match_url, json=match_payload, headers=headers) as m_resp:
                        if m_resp.status == 200:
                            m_data = await m_resp.json()
                        if m_data.get('dropped'):
                            log("DROPPED", f"⏩ Melewati {anime_title} Ep {prev_num} karena berstatus Dropped oleh Admin", YELLOW)
                            break
                        anime_obj = m_data.get('anime') or {}
                        anime_st = (anime_obj.get('status') or '').lower()
                        if anime_st != 'ongoing':
                            log("NOT_ONGOING", f"⏩ Melewati {anime_title} Ep {prev_num} karena anime berstatus '{anime_st}' (bukan Ongoing)", YELLOW)
                            break
                        ep_obj = m_data.get('episode')
                        if ep_obj:
                            prev_ep_id = ep_obj.get('id')
                            has_tg = ep_obj.get('has_telegram', False)
                            existing_qualities = ep_obj.get('telegram_qualities', [])
            except Exception:
                pass

        if not prev_ep_id:
            continue

        completed = set(existing_qualities)

        # Jika episode sebelumnya sudah memiliki server telegram utama, perbarui state lokal dan lewati unduhan awal
        if has_tg and ('720p' in completed or '1080p' in completed or set(TARGET_ALL_QUALITIES).issubset(completed)):
            log("PREV_EXIST", f"[SUDAH ADA] Ep {prev_num} sudah ada di Nipnime ({', '.join(completed)})", GRAY)
            state[prev_key] = {
                'anime_title': anime_title,
                'episode_number': prev_num,
                'episode_id': prev_ep_id,
                'first_source': 'Nipnime Telegram',
                'first_released_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'completed_qualities': list(completed),
                'status': 'complete' if (('1080p' in completed and '720p' in completed and ('2k' in completed or '1440p' in completed)) or not is_2k_required()) else 'partial',
                'created_at': state.get(prev_key, {}).get('created_at', time.time()),
                'last_checked_at': time.time(),
            }
            save_ongoing_state(state)
            continue

        log("PREV_MISSING", f"⚡ Ep {prev_num} BELUM ADA di Nipnime! Mencari di AnimeSail, Kurama, NontonAnimeID...", YELLOW)

        # Cari episode ini di ketiga sumber dengan extra_info khusus episode sebelumnya
        prev_extra_info = dict(extra_info or {})
        prev_extra_info['episode_id'] = prev_ep_id
        prev_extra_info['episode_number'] = prev_num
        found_sources = await check_episode_on_all_sources(session, anime_title, prev_num, extra_info=prev_extra_info)
        if not found_sources:
            log("PREV_NOT_FOUND", f"Episode sebelumnya {anime_title} Ep {prev_num} belum ditemukan di ketiga sumber (coba lagi 1 jam)", GRAY)
            state[prev_key] = {
                'anime_title': anime_title,
                'episode_number': prev_num,
                'episode_id': prev_ep_id,
                'first_source': 'Previous Episode Backfill',
                'first_released_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'completed_qualities': list(existing_qualities),
                'status': 'partial',
                'retry_after': time.time() + 3600,
                'created_at': time.time(),
                'last_checked_at': time.time(),
                'skip_reason': 'not_found'
            }
            save_ongoing_state(state)
            continue

        if prev_key not in state:
            state[prev_key] = {
                'anime_title': anime_title,
                'episode_number': prev_num,
                'episode_id': prev_ep_id,
                'first_source': 'Previous Episode Backfill',
                'first_released_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'nontonanimeid_slug': (extra_info or {}).get('nontonanimeid_slug'),
                'completed_qualities': list(existing_qualities),
                'status': 'partial',
                'created_at': time.time(),
                'last_checked_at': time.time()
            }
            save_ongoing_state(state)

        prev_item = state[prev_key]
        completed = set(prev_item.get('completed_qualities', []))

        slug = safe_file_slug(anime_title, 50)
        ingested_count = 0

        failed_urls = prev_item.get('failed_urls')
        if not isinstance(failed_urls, dict):
            failed_urls = {}
            prev_item['failed_urls'] = failed_urls

        for q, q_data in found_sources.items():
            if q in completed:
                continue

            cur_url = q_data['url']
            if is_url_on_cooldown(failed_urls, cur_url):
                continue

            log("PREV_INGEST", f"Mengunduh episode sebelumnya Ep {prev_num} [{q}] dari {q_data['source']} ({q_data.get('host')})...", MAGENTA)
            dest_file = TEMP_DOWNLOAD_DIR / f"{slug}_ep{prev_num}_{q}.mp4"

            ok = await download_file(cur_url, dest_file, q, min_speed_mb=0.8, backup_urls=q_data.get('backup_urls'))
            if not ok:
                record_url_failure(failed_urls, cur_url)
                # Coba cari alternatif dari sumber lain jika tautan pertama gagal / lambat / timeout
                alt_found = await check_episode_on_all_sources(session, anime_title, prev_num, extra_info=prev_extra_info, skip_source=q_data.get('source'))
                alt_found = alt_found or {}
                if q in alt_found and alt_found[q]['url'] != cur_url:
                    alt_data = alt_found[q]
                    alt_url = alt_data['url']
                    if not is_url_on_cooldown(failed_urls, alt_url):
                        log("FALLBACK", f"Mencoba sumber cadangan Ep {prev_num} [{q}] dari {alt_data['source']} ({alt_data.get('host')})...", YELLOW)
                        ok = await download_file(alt_url, dest_file, q, min_speed_mb=0.8)
                        if ok:
                            q_data = alt_data
                        else:
                            record_url_failure(failed_urls, alt_url)
                            log("SKIP", f"⏩ Sumber cadangan Ep {prev_num} [{q}] juga lambat/gagal. Menunggu 1 jam agar limit hoster reset...", YELLOW)
                else:
                    log("SKIP", f"⏩ Tidak ada sumber cadangan lain untuk Ep {prev_num} [{q}]. Menunggu 1 jam agar limit hoster reset...", YELLOW)

            if ok and dest_file.exists():
                try:
                    src_info = f"{q_data['source']} ({q_data.get('host')}) - Backfill Ep Sebelumnya"
                    def _on_prev_registered():
                        nonlocal ingested_count
                        ingested_count += 1
                        prev_item['completed_qualities'] = list(completed)
                        prev_item['last_checked_at'] = time.time()
                        save_ongoing_state(state)

                    await upload_and_process_two_stage(
                        tg_client, session, dest_file, anime_title, prev_num, prev_ep_id, q, src_info,
                        completed_qualities=completed,
                        on_raw_registered_callback=_on_prev_registered
                    )
                finally:
                    if dest_file.exists(): dest_file.unlink()

        prev_item['completed_qualities'] = list(completed)
        prev_item['last_checked_at'] = time.time()
        target_q = get_target_qualities()
        rem = [q for q in target_q if q not in completed]
        prev_item['missing_qualities'] = rem
        has_fhd_and_hd = '1080p' in completed and '720p' in completed
        has_2k = '2k' in completed or '1440p' in completed

        if is_2k_required():
            is_major = (has_fhd_and_hd and has_2k) or ('1080p' in completed and has_2k)
        else:
            is_major = set(['1080p', '720p', '480p']).issubset(completed) or has_fhd_and_hd

        if ingested_count > 0 or len(completed) > 0:
            if not rem or is_major:
                prev_item['status'] = 'complete'
                prev_item['missing_qualities'] = []
                prev_item.pop('retry_after', None)
                log("STATUS", f"✓ Backfill LENGKAP ({', '.join(completed)}) untuk {anime_title} Ep {prev_num}!", GREEN)
            else:
                prev_item['status'] = 'partial'
                prev_item['retry_after'] = time.time() + 3600
                log("COOLDOWN", f"✓ Backfill sebagian ({', '.join(completed)}) untuk {anime_title} Ep {prev_num}. Sisa resolusi ({', '.join(rem)}) dijadwalkan coba ulang 1 jam lagi...", YELLOW)
        else:
            prev_item['status'] = 'partial'
            prev_item['retry_after'] = time.time() + 3600
            log("COOLDOWN", f"⏳ Backfill Ep {prev_num} gagal unduh / limit kuota hoster. Dijadwalkan coba ulang 1 jam lagi...", YELLOW)
        save_ongoing_state(state)

async def backfill_single_episode(k: str, item: dict, tg_client: Client, session: aiohttp.ClientSession, state: dict, state_lock: asyncio.Lock):
    """Memproses satu episode ongoing yang belum lengkap resolusinya."""
    anime_title = item['anime_title']
    ep_num = item['episode_number']
    episode_id = item['episode_id']
    completed = set(item.get('completed_qualities', []))

    # Catatan: Seleksi shard dan gotong royong sudah dilakukan di backfill_missing_resolutions.
    # Jangan tolak episode di sini agar gotong royong saat worker nganggur tetap berjalan.

    # Sinkronkan dengan Nipnime jika ada resolusi yang sudah diunggah di database
    tg_servers = {}
    if episode_id:
        try:
            chk_url = f"{API_URL}/match-title"
            headers = {'X-Terop-Token': WORKER_TOKEN, 'Accept': 'application/json'}
            payload = {'title': f"{anime_title} Episode {ep_num}", 'auto_create_episode': False, 'episode_number': ep_num}
            async with session.post(chk_url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as chk_resp:
                if chk_resp.status == 200:
                    chk_data = await chk_resp.json()
                    if chk_data.get('dropped'):
                        log("DROPPED", f"⏩ Melewati {anime_title} Ep {ep_num} karena berstatus Dropped oleh Admin", YELLOW)
                        state.pop(item_key, None)
                        async with state_lock:
                            save_ongoing_state(state)
                        return 0
                    ep_obj = chk_data.get('episode') or {}
                    if ep_obj.get('id'):
                        item['episode_id'] = ep_obj.get('id')
                    tg_q = ep_obj.get('telegram_qualities', [])
                    tg_servers = ep_obj.get('telegram_servers', {})
                    if tg_q:
                        completed.update(tg_q)
                        item['completed_qualities'] = list(completed)
                        item.pop('retry_after', None)
                        item.pop('skip_reason', None)
        except Exception:
            pass

    target_q = get_target_qualities()
    missing = [q for q in target_q if q not in completed]
    has_fhd_and_hd = '1080p' in completed and '720p' in completed
    has_2k = '2k' in completed or '1440p' in completed

    is_complete = False
    if is_2k_required():
        if (has_fhd_and_hd and has_2k) or ('1080p' in completed and has_2k):
            is_complete = True
    else:
        if not missing or set(['1080p', '720p', '480p']).issubset(completed) or has_fhd_and_hd:
            is_complete = True

    if is_complete:
        item['status'] = 'complete'
        item['missing_qualities'] = []
        async with state_lock:
            save_ongoing_state(state)
        return 0

    failed_urls = item.get('failed_urls')
    if not isinstance(failed_urls, dict):
        failed_urls = {}
        item['failed_urls'] = failed_urls

    # OPTIMASI KILAT: Jika HANYA 2K yang belum ada dan 1080p sudah selesai:
    # Scraper TIDAK PERNAH memiliki 2K. Langsung masukkan ke antrean GPU latar belakang tanpa buang waktu scraping!
    only_2k_missing = set(missing).issubset({'2k', '1440p'})
    if is_2k_required() and not has_2k and '1080p' in completed and only_2k_missing:
        job_key = f"2k_{episode_id}_{ep_num}"
        if not is_render_queued_or_active(job_key):
            q_render = get_render_queue()
            if q_render.qsize() >= 4:
                # Batasi agar antrean backfill 2K tidak membanjiri GPU. Tunda ke siklus berikutnya.
                return 0
            await ensure_2k_upscale_for_episode(
                tg_client, session, anime_title, ep_num, episode_id,
                completed, None, failed_urls, tg_servers, item.get('first_source', 'Backfill'),
                item=item, state=state, state_lock=state_lock, priority=3
            )
        return 0

    # Cek ke seluruh sumber apakah resolusi yang belum ada (720p/480p) sudah menyusul dirilis
    all_found = await check_episode_on_all_sources(session, anime_title, ep_num, extra_info=item)
    all_found = all_found or {}
    newly_added = 0
    slug = safe_file_slug(anime_title, 50)

    # Khusus jika 2K wajib: pastikan 2K dimasukkan ke antrean render non-blocking (jika antrean belum padat)
    if is_2k_required() and not has_2k and ('1080p' in completed or (all_found and '1080p' in all_found)):
        q_render = get_render_queue()
        if q_render.qsize() < 4:
            await ensure_2k_upscale_for_episode(
                tg_client, session, anime_title, ep_num, episode_id,
                completed, all_found, failed_urls, tg_servers, item.get('first_source', 'Backfill'),
                item=item, state=state, state_lock=state_lock, priority=3
            )

    for q in missing:
        if q in all_found and q not in completed and q != '2k':
            q_data = all_found[q]
            cur_url = q_data['url']
            if is_url_on_cooldown(failed_urls, cur_url):
                # Tautan ini sedang dalam masa cooldown 1 jam
                continue

    active_backfill_q = [
        (q, q_data) for q, q_data in all_found.items()
        if q in missing and not is_url_on_cooldown(failed_urls, q_data['url'])
    ]

    async def _process_backfill_q(q, q_data):
        nonlocal newly_added
        cur_url = q_data['url']
        dest_file = TEMP_DOWNLOAD_DIR / f"{slug}_ep{ep_num}_{q}.mp4"
        try:
            log("BACKFILL_FOUND", f"⚡ Resolusi susulan [{q}] DITEMUKAN untuk {anime_title} Ep {ep_num} dari {q_data['source']} ({q_data.get('host')})!", GREEN)
            ok = await download_file(cur_url, dest_file, q, min_speed_mb=0.8, backup_urls=q_data.get('backup_urls'))
            if not ok:
                record_url_failure(failed_urls, cur_url)
                # Coba cari alternatif dari sumber lain jika tautan pertama gagal / lambat / timeout
                alt_found = await check_episode_on_all_sources(session, anime_title, ep_num, extra_info=item, skip_source=q_data['source'])
                alt_found = alt_found or {}
                if q in alt_found and alt_found[q]['url'] != cur_url:
                    alt_data = alt_found[q]
                    alt_url = alt_data['url']
                    if not is_url_on_cooldown(failed_urls, alt_url):
                        log("FALLBACK", f"Mencoba sumber cadangan [{q}] dari {alt_data['source']} ({alt_data.get('host')})...", YELLOW)
                        ok = await download_file(alt_url, dest_file, q, min_speed_mb=0.8)
                        if ok:
                            q_data = alt_data
                        else:
                            record_url_failure(failed_urls, alt_url)
                            log("SKIP", f"⏩ Sumber cadangan [{q}] juga lambat/tidak ada respon. Menunggu 1 jam agar limit hoster reset...", YELLOW)
                else:
                    log("SKIP", f"⏩ Tidak ada sumber cadangan lain untuk [{q}]. Menunggu 1 jam agar limit hoster reset...", YELLOW)

            if ok and dest_file.exists():
                rw, rh = get_video_dimensions(dest_file)
                min_h = {'1080p': 850, '720p': 550, '480p': 380}.get(q.lower(), 0)
                if rh > 0 and min_h > 0 and rh < min_h:
                    log("RESOLUTION_MISMATCH", f"⚠️ File [{q}] yang diunduh hanya beresolusi riil {rw}x{rh} (jauh di bawah standar {q})! Mencoba sumber alternatif...", YELLOW)
                    ok = False
                    record_url_failure(failed_urls, q_data['url'])
                    alt_found = await check_episode_on_all_sources(session, anime_title, ep_num, extra_info=item, skip_source=q_data['source'])
                    alt_found = alt_found or {}
                    if q in alt_found and alt_found[q]['url'] != cur_url:
                        alt_data = alt_found[q]
                        alt_url = alt_data['url']
                        if not is_url_on_cooldown(failed_urls, alt_url):
                            log("FALLBACK", f"Mencoba sumber cadangan [{q}] dari {alt_data['source']} ({alt_data.get('host')})...", YELLOW)
                            ok = await download_file(alt_url, dest_file, q, min_speed_mb=0.8)
                            if ok and dest_file.exists():
                                rw2, rh2 = get_video_dimensions(dest_file)
                                if rh2 > 0 and min_h > 0 and rh2 < min_h:
                                    ok = False
                                    record_url_failure(failed_urls, alt_url)
                                else:
                                    q_data = alt_data

            if ok and dest_file.exists():
                src_info = f"{q_data['source']} ({q_data.get('host')}) - Resolusi Susulan"
                def _on_bf_registered():
                    nonlocal newly_added
                    newly_added += 1
                    item['completed_qualities'] = list(completed)
                    rem_missing = [mq for mq in target_q if mq not in completed]
                    item['missing_qualities'] = rem_missing
                    has_fhd = '1080p' in completed and '720p' in completed
                    has_2k = '2k' in completed or '1440p' in completed
                    if not rem_missing or (is_2k_required() and has_fhd and has_2k) or (not is_2k_required() and has_fhd):
                        item['status'] = 'complete'
                        item['missing_qualities'] = []
                        log("FULL", f"✓ Berhasil melengkapi SEMUA resolusi untuk {anime_title} Ep {ep_num}!", GREEN)
                    save_ongoing_state(state)

                await upload_and_process_two_stage(
                    tg_client, session, dest_file, anime_title, ep_num, episode_id, q, src_info,
                    completed_qualities=completed,
                    on_raw_registered_callback=_on_bf_registered
                )
        finally:
            if dest_file.exists():
                try: dest_file.unlink()
                except Exception: pass

    role = get_device_role()
    if role in ('colab', 'codespace') and len(active_backfill_q) > 1:
        bf_sem = asyncio.Semaphore(min(4, len(active_backfill_q)))
        async def _bf_w(q, q_d):
            async with bf_sem:
                await _process_backfill_q(q, q_d)
        await asyncio.gather(*[_bf_w(q, q_d) for q, q_d in active_backfill_q], return_exceptions=True)
    else:
        for q, q_data in active_backfill_q:
            await _process_backfill_q(q, q_data)

    rem_missing = [q for q in target_q if q not in completed]
    has_fhd = '1080p' in completed and '720p' in completed
    has_2k = '2k' in completed or '1440p' in completed

    if is_2k_required():
        is_major = (has_fhd and has_2k) or ('1080p' in completed and has_2k)
    else:
        is_major = set(['1080p', '720p', '480p']).issubset(completed) or has_fhd
    valid_remaining = [
        mq for mq in rem_missing 
        if mq != '2k' and mq in all_found and not is_url_on_cooldown(failed_urls, all_found[mq]['url'])
    ]
    has_more_available = len(valid_remaining) > 0

    item['completed_qualities'] = list(completed)
    item['last_checked_at'] = time.time()

    if not rem_missing or is_major:
        item['status'] = 'complete'
        item['missing_qualities'] = []
        item.pop('retry_after', None)
        log("FULL", f"✓ Episode selesai ({', '.join(completed)}) untuk {anime_title} Ep {ep_num}!", GREEN)
    elif rem_missing == ['2k'] and '1080p' in completed:
        item['status'] = 'partial'
        item['missing_qualities'] = ['2k']
        item.pop('retry_after', None)
        log("WAIT_2K", f"⏳ {anime_title} Ep {ep_num}: Versi 1080p siap, menunggu render 2K GPU...", CYAN)
    elif not has_more_available:
        # Jika link yang ada gagal / timeout / limit hoster:
        # Berikan jeda 1 jam agar limit pulih, dan TETAP simpan di antrean partial!
        item['status'] = 'partial'
        item['missing_qualities'] = rem_missing
        if rem_missing != ['2k']:
            item['retry_after'] = time.time() + 3600
        else:
            item.pop('retry_after', None)
        log("COOLDOWN", f"⏳ {anime_title} Ep {ep_num}: Link resolusi susulan ({', '.join(rem_missing)}) limit/lambat. Dijadwalkan coba ulang 1 jam lagi...", YELLOW)
    else:
        item['status'] = 'partial'
        item['missing_qualities'] = rem_missing
        item.pop('retry_after', None)

    async with state_lock:
        save_ongoing_state(state)
    return newly_added

async def check_has_new_ongoing_release(session: aiohttp.ClientSession, state: dict) -> bool:
    """Cek kilat apakah ada episode ongoing baru yang baru tayang di feed sumber dan belum ada di state."""
    try:
        tasks = [
            asyncio.create_task(scan_animesail_latest(session)),
            asyncio.create_task(scan_kuramanime_latest(session))
        ]
        res = await asyncio.gather(*tasks, return_exceptions=True)
        for r_list in res:
            if isinstance(r_list, list):
                for r in r_list:
                    if not isinstance(r, dict): continue
                    r_title = r.get('anime_title', '')
                    r_ep = r.get('episode_number', 1)
                    r_k = f"{normalize_title(r_title)}:{r_ep}"
                    if r_k not in state or state[r_k].get('status') != 'complete':
                        if r_k not in state:
                            return True
    except Exception:
        pass
    return False

async def backfill_missing_resolutions(tg_client: Client, session: aiohttp.ClientSession, state: dict, concurrency: int = 1) -> int:
    """Mengecek ulang seluruh episode ongoing yang resolusinya belum lengkap (1080p, 480p, 360p) dengan claim lock anti-tabrakan."""
    if get_device_role() == "server" and has_active_remote_workers():
        return 0
    now = time.time()
    # Ambil SEMUA episode ongoing aktif yang resolusinya belum lengkap
    candidate_keys = [
        k for k, v in state.items() 
        if isinstance(v, dict) and v.get('status') == 'partial' 
        and (now - v.get('created_at', 0)) < 259200 
        and (now - v.get('last_checked_at', 0)) >= 30 
        and (not v.get('retry_after') or now >= v['retry_after'] or (is_2k_required() and '1080p' in v.get('completed_qualities', []) and not ('2k' in v.get('completed_qualities', []) or '1440p' in v.get('completed_qualities', []))))
    ]

    # Prioritaskan:
    # 1. Episode yang sudah punya 1080p tapi belum 2K (jika GPU worker aktif):
    #    Bisa langsung masuk ke GPU Render Queue latar belakang tanpa buang waktu scraping web!
    # 2. Episode yang belum memiliki video server sama sekali / paling sedikit resolusi.
    def _prio_candidate(k):
        v = state.get(k) or {}
        comp = set(v.get('completed_qualities', []))
        only_2k = ('1080p' in comp and not ('2k' in comp or '1440p' in comp))
        if is_2k_required() and only_2k:
            return 0
        return 1 + len(comp)

    candidate_keys.sort(key=_prio_candidate)

    if not candidate_keys:
        return 0

    # Klaim episode lock ke server secara dinamis gotong-royong (Work-Stealing Cluster)
    # Batasi batch klaim agar episode lain tetap terbuka untuk dikerjakan worker lain secara serentak
    max_claim = max(2, concurrency * 2)
    active_keys = []
    for k in candidate_keys:
        ov = state.get(k)
        if not ov: continue
        ep_n = ov.get('episode_number', k.split(':')[-1])
        t_title = ov.get('anime_title', '')
        claimed = await claim_episode_lock(session, t_title, ep_n, ov.get('episode_id'))
        if claimed:
            active_keys.append(k)
            if len(active_keys) >= max_claim:
                break

    if not active_keys:
        return 0

    concurrency_text = f" [Paralel {concurrency} Task]" if concurrency > 1 else ""
    log("BACKFILL_CHECK", f"Memeriksa resolusi susulan untuk {len(active_keys)} episode ongoing aktif{concurrency_text}...", CYAN)

    state_lock = asyncio.Lock()
    total_added = 0

    if concurrency <= 1:
        for idx, k in enumerate(active_keys):
            # Di sela-sela episode, cek apakah ada rilis ongoing baru yang mendesak di feed sumber
            if idx > 0 and (await check_has_new_ongoing_release(session, state)):
                log("PRIO_NEW", "🚨 Terdeteksi episode rilis baru di feed sumber! Menunda sisa backfill untuk mengutamakan rilis baru...", BOLD + CYAN)
                break

            item = state.get(k)
            if not item: continue
            v_ep = item.get('episode_number', k.split(':')[-1])
            v_title = item.get('anime_title', '')
            try:
                cnt = await backfill_single_episode(k, item, tg_client, session, state, state_lock)
                total_added += (cnt or 0)
            except Exception as e:
                log("ERR_BACKFILL_EP", f"Gagal backfill {k}: {e}", RED)
            finally:
                job_key = f"2k_{item.get('episode_id')}_{v_ep}"
                if not is_render_queued_or_active(job_key):
                    await release_episode_lock(session, v_title, v_ep)
    else:
        # Eksekusi paralel per batch seukuran concurrency
        batch_size = max(1, concurrency)
        for i in range(0, len(active_keys), batch_size):
            if i > 0 and (await check_has_new_ongoing_release(session, state)):
                log("PRIO_NEW", "🚨 Terdeteksi episode rilis baru di feed sumber! Menunda sisa backfill untuk mengutamakan rilis baru...", BOLD + CYAN)
                break

            current_batch = active_keys[i:i + batch_size]
            sem = asyncio.Semaphore(concurrency)
            async def sem_worker(k):
                nonlocal total_added
                async with sem:
                    item = state.get(k)
                    if not item: return
                    v_ep = item.get('episode_number', k.split(':')[-1])
                    v_title = item.get('anime_title', '')
                    try:
                        cnt = await backfill_single_episode(k, item, tg_client, session, state, state_lock)
                        total_added += (cnt or 0)
                    except Exception as e:
                        log("ERR_BACKFILL_EP", f"Gagal backfill {k}: {e}", RED)
                    finally:
                        job_key = f"2k_{item.get('episode_id')}_{v_ep}"
                        if not is_render_queued_or_active(job_key):
                            await release_episode_lock(session, v_title, v_ep)

            tasks = [asyncio.create_task(sem_worker(k)) for k in current_batch]
            await asyncio.gather(*tasks, return_exceptions=True)

    return total_added

# ==============================================================================
# 5. COMPLETED ANIME ENGINE (MODE ANIME TAMAT)
# ==============================================================================
def ensure_completed_state_dict(s) -> dict:
    if isinstance(s, dict):
        if not isinstance(s.get('queue'), list):
            s['queue'] = []
        if not isinstance(s.get('history'), dict):
            s['history'] = {}
        for it in s['queue']:
            if isinstance(it, dict):
                if not isinstance(it.get('failed_eps'), dict):
                    it['failed_eps'] = {}
                if not isinstance(it.get('failed_urls'), dict):
                    it['failed_urls'] = {}
                if not isinstance(it.get('kuramanime_batch_info'), dict):
                    it['kuramanime_batch_info'] = {}
                if not isinstance(it.get('kusonime_batch_info'), dict):
                    it['kusonime_batch_info'] = {}
                if not isinstance(it.get('otakudesu_batch_info'), dict):
                    it['otakudesu_batch_info'] = {}
                if not isinstance(it.get('ep_links_map'), dict):
                    it['ep_links_map'] = ensure_ep_links_dict(it.get('ep_links_map'))
        return s
    elif isinstance(s, list):
        return {'otakudesu_page': 1, 'queue': s, 'history': {}}
    return {'otakudesu_page': 1, 'queue': [], 'history': {}}

def load_completed_state() -> dict:
    possible_paths = [
        Path('/app/.completed_anime_state.json'),
        Path('.completed_anime_state.json'),
        SCRIPT_DIR / '.completed_anime_state.json',
        Path('Z:/tools/terop-worker/.completed_anime_state.json'),
        Path('D:/tools/terop-worker/.completed_anime_state.json')
    ]
    for p in possible_paths:
        if p.exists():
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return ensure_completed_state_dict(data)
            except Exception:
                pass

    if get_device_role() in REMOTE_ROLES:
        remote_data = sync_state_from_server()
        if remote_data and isinstance(remote_data, dict):
            comp = remote_data.get('completed_state')
            if comp:
                return ensure_completed_state_dict(comp)

    return {'otakudesu_page': 1, 'queue': [], 'history': {}}

def save_completed_state(state: dict):
    possible_paths = [
        SCRIPT_DIR / '.completed_anime_state.json',
        Path('.completed_anime_state.json'),
        Path('/app/.completed_anime_state.json') if Path('/app').is_dir() else None,
        Path('Z:/tools/terop-worker/.completed_anime_state.json'),
        Path('D:/tools/terop-worker/.completed_anime_state.json')
    ]
    for p in filter(None, possible_paths):
        try:
            if p.parent.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, 'w', encoding='utf-8') as f:
                    json.dump(state, f, indent=2)
        except Exception:
            continue
    # Jika di remote worker (Colab / Laptop / Azure / AWS), perbarui heartbeat agar state anime tamat langsung terkirim ke server
    if get_device_role() in REMOTE_ROLES:
        update_heartbeat(status="running")

async def claim_episode_lock(session: aiohttp.ClientSession, anime_title: str, episode_number: int, anime_id: any = None, ttl: int = 900) -> bool:
    """Mengklaim pengerjaan episode di server Nipnime agar tidak dikerjakan ganda oleh worker lain."""
    if is_worker_quarantined() or is_remotely_paused():
        return False
    try:
        url = f"{API_URL}/claim-episode"
        payload = {
            'worker_id': get_worker_id(),
            'anime_title': anime_title,
            'episode_number': episode_number,
            'anime_id': anime_id,
            'ttl': ttl
        }
        headers = {
            'X-Terop-Token': WORKER_TOKEN,
            'Authorization': f"Bearer {WORKER_TOKEN}",
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': DEFAULT_UA
        }
        c_status, c_data = await async_request_nipnime_api('POST', f"{url}?token={WORKER_TOKEN}", payload, headers=headers, timeout=8)
        if c_status == 200 and isinstance(c_data, dict):
            return bool(c_data.get('granted'))
        async with session.post(f"{url}?token={WORKER_TOKEN}", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return bool(data.get('granted'))
            return True
    except Exception:
        return True

async def release_episode_lock(session: aiohttp.ClientSession, anime_title: str, episode_number: int):
    """Melepaskan klaim pengerjaan episode di server Nipnime."""
    try:
        url = f"{API_URL}/release-episode"
        payload = {
            'worker_id': get_worker_id(),
            'anime_title': anime_title,
            'episode_number': episode_number
        }
        headers = {
            'X-Terop-Token': WORKER_TOKEN,
            'Authorization': f"Bearer {WORKER_TOKEN}",
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': DEFAULT_UA
        }
        await async_request_nipnime_api('POST', f"{url}?token={WORKER_TOKEN}", payload, headers=headers, timeout=8)
    except Exception:
        pass

async def ingest_single_completed_episode(
    ep_num: int,
    item: dict,
    state: dict,
    tg_client: Client,
    session: aiohttp.ClientSession,
    db_title: str,
    db_slug: str,
    episode_id: int,
    tg_qualities: set,
    state_lock: asyncio.Lock,
    is_gotong_royong: bool = False
) -> bool:
    """Memproses unduh & unggah satu episode anime tamat."""
    if not is_gotong_royong and not is_episode_in_shard(ep_num):
        return False
    try:
        log("TAMAT_INGEST", f"📥 Memproses anime tamat: {db_title} Ep {ep_num}...", MAGENTA)

        extra_info_obj = {**item, 'episode_id': episode_id} if isinstance(item, dict) else {'episode_id': episode_id}
        all_sources = await check_episode_on_all_sources(session, db_title, ep_num, extra_info=extra_info_obj)
        all_sources = all_sources or {}

        # Khusus jika 1080p sudah ada di Telegram tapi 2K belum ada (dan 2K wajib karena di Colab/Laptop)
        need_2k_only = is_2k_required() and '1080p' in tg_qualities and not ('2k' in tg_qualities or '1440p' in tg_qualities)
        if need_2k_only:
            job_key = f"2k_{episode_id}_{ep_num}"
            if not is_render_queued_or_active(job_key):
                q_render = get_render_queue()
                if q_render.qsize() >= 4:
                    return False
                await ensure_2k_upscale_for_episode(
                    tg_client, session, db_title, ep_num, episode_id,
                    tg_qualities, all_sources, item.get('failed_urls', {}), extra_info_obj.get('telegram_servers', {}), "Anime Tamat",
                    item=item, state=state, state_lock=state_lock, is_tamat=True, priority=3
                )
            return True

        available_qualities = [q for q in ['1080p', '720p', '480p', '360p'] if q in all_sources and q not in tg_qualities]

        if not available_qualities:
            async with state_lock:
                failed_eps = item.setdefault('failed_eps', {})
                failed_eps[str(ep_num)] = time.time() + 1800
                save_completed_state(state)
            log("TAMAT_COOLDOWN", f"⏳ Link {db_title} Ep {ep_num} belum tersedia. Dijadwalkan coba ulang 30 menit lagi...", YELLOW)
            return False

        success = False
        safe_slug = safe_file_slug(db_slug or db_title, 50)
        for chosen_q in available_qualities:
            q_data = all_sources[chosen_q]
            cur_url = q_data['url']
            dest_file = TEMP_DOWNLOAD_DIR / f"{safe_slug}_ep{ep_num}_{chosen_q}.mp4"

            update_heartbeat(status="running", current_task=f"🎬 Anime Tamat: {db_title} Ep {ep_num} [{chosen_q}]")
            ok = await download_file(cur_url, dest_file, chosen_q, min_speed_mb=0.8, backup_urls=q_data.get('backup_urls'))
            if ok and dest_file.exists():
                try:
                    update_heartbeat(status="running", current_task=f"📤 Unggah Tamat: {db_title} Ep {ep_num} [{chosen_q}]")
                    src_info = f"{q_data['source']} ({q_data.get('host')}) - Anime Tamat"
                    def _on_comp_registered():
                        item.pop('retry_after', None)
                        failed_eps = item.get('failed_eps')
                        if not isinstance(failed_eps, dict):
                            failed_eps = {}
                            item['failed_eps'] = failed_eps
                        failed_eps.pop(str(ep_num), None)
                        c_eps = set(item.get('completed_eps', []))
                        c_eps.add(ep_num)
                        item['completed_eps'] = sorted(list(c_eps))
                        item['last_checked_ep'] = max(item.get('last_checked_ep', 0), ep_num)
                        save_completed_state(state)

                    msg_id = await upload_and_process_two_stage(
                        tg_client, session, dest_file, db_title, ep_num, episode_id, chosen_q, src_info,
                        completed_qualities=tg_qualities,
                        on_raw_registered_callback=_on_comp_registered,
                        is_tamat=True
                    )
                    if msg_id:
                        log("TAMAT_DONE", f"✓ Berhasil unggah anime tamat: {db_title} Ep {ep_num} [{chosen_q}]!", GREEN)
                        success = True
                        break
                finally:
                    if dest_file.exists():
                        dest_file.unlink()
            else:
                log("TAMAT_FALLBACK", f"⚠️ Unduhan {db_title} Ep {ep_num} [{chosen_q}] dibatalkan/limit hoster. Mencoba resolusi alternatif...", YELLOW)

        if success:
            return True

        # Jika seluruh resolusi dari sumber awal gagal/limit, fallback ke sumber alternatif (Samehadaku Acefile, AnimeSail, dll)
        first_src = list(all_sources.values())[0].get('source') if all_sources else 'Otakudesu'
        log("TAMAT_FALLBACK", f"🔄 Seluruh resolusi dari {first_src} gagal/limit. Mencari sumber alternatif (Samehadaku Acefile / AnimeSail)...", CYAN)
        alt_sources = await check_episode_on_all_sources(session, db_title, ep_num, extra_info=extra_info_obj, skip_source=first_src)
        alt_qualities = [q for q in ['1080p', '720p', '480p', '360p'] if q in alt_sources and q not in tg_qualities]
        if alt_qualities:
            for chosen_q in alt_qualities:
                q_data = alt_sources[chosen_q]
                cur_url = q_data['url']
                dest_file = TEMP_DOWNLOAD_DIR / f"{safe_slug}_ep{ep_num}_{chosen_q}.mp4"
                update_heartbeat(status="running", current_task=f"🎬 Anime Tamat (Alt): {db_title} Ep {ep_num} [{chosen_q}]")
                ok = await download_file(cur_url, dest_file, chosen_q, min_speed_mb=0.8, backup_urls=q_data.get('backup_urls'))
                if ok and dest_file.exists():
                    try:
                        update_heartbeat(status="running", current_task=f"📤 Unggah Tamat: {db_title} Ep {ep_num} [{chosen_q}]")
                        src_info = f"{q_data['source']} ({q_data.get('host')}) - Anime Tamat"
                        def _on_comp_alt_registered():
                            item.pop('retry_after', None)
                            failed_eps = item.get('failed_eps')
                            if not isinstance(failed_eps, dict):
                                failed_eps = {}
                                item['failed_eps'] = failed_eps
                            failed_eps.pop(str(ep_num), None)
                            c_eps = set(item.get('completed_eps', []))
                            c_eps.add(ep_num)
                            item['completed_eps'] = sorted(list(c_eps))
                            item['last_checked_ep'] = max(item.get('last_checked_ep', 0), ep_num)
                            save_completed_state(state)

                        msg_id = await upload_and_process_two_stage(
                            tg_client, session, dest_file, db_title, ep_num, episode_id, chosen_q, src_info,
                            completed_qualities=tg_qualities,
                            on_raw_registered_callback=_on_comp_alt_registered,
                            is_tamat=True
                        )
                        if msg_id:
                            log("TAMAT_DONE", f"✓ Berhasil unggah anime tamat dari sumber alternatif: {db_title} Ep {ep_num} [{chosen_q}]!", GREEN)
                            success = True
                            break
                    finally:
                        if dest_file.exists():
                            dest_file.unlink()
                else:
                    log("TAMAT_FALLBACK", f"⚠️ Unduhan alternatif {db_title} Ep {ep_num} [{chosen_q}] gagal.", YELLOW)

        if success:
            return True

        # Seluruh kualitas dari seluruh sumber gagal untuk episode ini
        async with state_lock:
            failed_eps = item.setdefault('failed_eps', {})
            failed_eps[str(ep_num)] = time.time() + 1800
            save_completed_state(state)
        log("TAMAT_COOLDOWN", f"⏳ Seluruh resolusi & sumber alternatif {db_title} Ep {ep_num} ({', '.join(available_qualities)}) gagal/limit kuota hoster. Episode ini di-cooldown 30 menit.", YELLOW)
        return False
    except Exception as e:
        log("ERR_EP", f"Gagal proses {db_title} Ep {ep_num}: {e}", RED)
        return False
    finally:
        await release_episode_lock(session, db_title, ep_num)

async def check_batch_package_already_complete_in_db(
    session: aiohttp.ClientSession,
    headers: dict,
    match_url: str,
    db_title: str,
    p_start: int,
    p_end: int,
    target_res: str
) -> bool:
    """
    PRE-DOWNLOAD COMPLETENESS GUARD:
    Memeriksa secara cepat apakah seluruh episode dalam rentang p_start s/d p_end
    sudah lengkap resolusi target_res di database Nipnime.
    Jika sudah lengkap, unduhan arsip multi-gigabyte dilewati agar hemat bandwidth.
    """
    if p_end < p_start:
        return False
    # Cek sampling episode awal, tengah, dan akhir
    sample_eps = sorted(list(set([p_start, (p_start + p_end) // 2, p_end])))
    for ep in sample_eps:
        payload = {'title': f"{db_title} Episode {ep}", 'episode_number': ep, 'auto_create_episode': False}
        try:
            status, data = await async_request_nipnime_api('POST', f"match-title?token={WORKER_TOKEN}", payload, headers=headers, timeout=8)
            if status == 200 and isinstance(data, dict) and data.get('matched'):
                ep_obj = data.get('episode') or {}
                tq = set(ep_obj.get('telegram_qualities') or [])
                if target_res not in tq:
                    return False
            else:
                return False
        except Exception:
            return False

    # Jika sampling lengkap, periksa sisa episode lainnya
    for ep in range(p_start, p_end + 1):
        if ep in sample_eps:
            continue
        payload = {'title': f"{db_title} Episode {ep}", 'episode_number': ep, 'auto_create_episode': False}
        try:
            status, data = await async_request_nipnime_api('POST', f"match-title?token={WORKER_TOKEN}", payload, headers=headers, timeout=8)
            if status == 200 and isinstance(data, dict) and data.get('matched'):
                ep_obj = data.get('episode') or {}
                tq = set(ep_obj.get('telegram_qualities') or [])
                if target_res not in tq:
                    return False
            else:
                return False
        except Exception:
            return False
    return True

async def try_process_kusonime_batch(
    tg_client: Client,
    session: aiohttp.ClientSession,
    anime_obj: dict,
    item: dict,
    state: dict,
    state_lock: asyncio.Lock,
    headers: dict,
    match_url: str
) -> bool:
    """
    Mencari dan memproses paket batch dari Kusonime untuk anime tamat.
    Menerapkan Progressive Extraction, Active Preemption Guard, Idempotent DB Check,
    Stream Compatibility Guard (MKV->MP4), dan Disk Space Guard.
    """
    if not search_kusonime or not parse_kusonime_batch_page:
        return False

    if not isinstance(item, dict):
        return False

    if isinstance(anime_obj, list):
        anime_obj = anime_obj[0] if (anime_obj and isinstance(anime_obj[0], dict)) else {}
    elif not isinstance(anime_obj, dict):
        anime_obj = {}

    db_title = anime_obj.get('title') or item.get('title', '')
    anime_id = anime_obj.get('id')
    db_slug = anime_obj.get('slug') or normalize_title(db_title).replace(' ', '-')
    total_eps = int(anime_obj.get('total_episodes') or 0)
    
    kuso_cache = item.get('kusonime_batch_info')
    if not isinstance(kuso_cache, dict):
        kuso_cache = {}
        item['kusonime_batch_info'] = kuso_cache
    if kuso_cache.get('not_found_until', 0) > time.time():
        return False

    # 1. Cari anime di Kusonime
    try:
        candidates = await asyncio.to_thread(search_kusonime, db_title, 12)
        match = match_kusonime_result(db_title, candidates)
        if not match:
            kuso_cache['not_found_until'] = time.time() + 86400  # Cooldown 24 jam jika tidak ditemukan
            save_completed_state(state)
            return False

        packages = await asyncio.to_thread(parse_kusonime_batch_page, match['url'], None, 12)
        if not packages:
            kuso_cache['not_found_until'] = time.time() + 86400
            save_completed_state(state)
            return False

        # Anti-Halu 1080p: Deteksi resolusi yang nyata tersedia di paket batch Kusonime
        found_res = set()
        for pkg in packages:
            if isinstance(pkg, dict):
                r_map = pkg.get('resolutions') or {}
                if isinstance(r_map, dict):
                    for r_name, r_links in r_map.items():
                        if r_links:
                            found_res.add(r_name.lower())
        if found_res:
            item['available_resolutions'] = [r for r in ['1080p', '720p', '480p', '360p'] if r in found_res]
            save_completed_state(state)
    except Exception as se:
        log("KUSONIME_WARN", f"Pencarian batch Kusonime '{db_title}' tertunda: {se}", YELLOW)
        return False

    # 2. Distributed Claim Lock khusus batch agar cluster worker tidak tabrakan (TTL 1 Jam)
    claim_success = await claim_episode_lock(session, f"batch_{db_title}", 1, anime_id, ttl=3600)
    if not claim_success:
        return False

    try:
        log("KUSONIME", f"📦 Ditemukan {len(packages)} paket batch Kusonime untuk '{db_title}'. Memeriksa ketersediaan resolusi...", CYAN)
        for pkg_idx, pkg in enumerate(packages, 1):
            if not isinstance(pkg, dict):
                continue
            pkg_title = pkg.get('package_title', f"Paket {pkg_idx}")
            pkg_res = pkg.get('resolutions') or {}
            if isinstance(pkg_res, list):
                r_dict = {}
                for it in pkg_res:
                    if isinstance(it, dict):
                        for k, v in it.items():
                            r_dict[k] = v
                pkg_res = r_dict

            if not isinstance(pkg_res, dict):
                continue

            # Prioritas Resolusi: 1080p -> 720p -> 480p -> 360p
            for target_res in ['1080p', '720p', '480p', '360p']:
                hosters = pkg_res.get(target_res, [])
                if not hosters or not isinstance(hosters, list):
                    continue

                # 3. Disk Space Guard: Periksa sisa ruang disk
                ok_disk, disk_msg = disk_space_guard(2 * 1024 * 1024 * 1024, TEMP_DOWNLOAD_DIR)
                if not ok_disk:
                    log("DISK_WARN", f"Penundaan batch '{db_title}': {disk_msg}", YELLOW)
                    return False

                # 3b. PRE-DOWNLOAD COMPLETENESS GUARD:
                # Periksa apakah episode dalam paket batch ini SUDAH LENGKAP di database Nipnime untuk target_res.
                m_range = re.search(r'(\d+)\s*[-–]\s*(\d+)', pkg_title)
                if m_range:
                    p_start, p_end = int(m_range.group(1)), int(m_range.group(2))
                else:
                    p_start, p_end = 1, int(anime_obj.get('total_episodes') or 12)

                is_complete_already = await check_batch_package_already_complete_in_db(
                    session, headers, match_url, db_title, p_start, p_end, target_res
                )
                if is_complete_already:
                    log("BATCH_SKIP", f"✓ Seluruh episode ({p_start}-{p_end}) {db_title} [{target_res}] SUDAH LENGKAP di database. Melewati unduhan paket ({pkg_title}).", GREEN)
                    continue

                safe_slug = safe_file_slug(db_slug or db_title, 35)
                pkg_tag = safe_file_slug(pkg_title, 20)
                archive_name = f"batch_{safe_slug}_{pkg_tag}_{target_res}.rar"
                archive_path = TEMP_DOWNLOAD_DIR / archive_name

                # 4. Unduh arsip batch dengan multi-hoster fallback
                # Jika hoster pertama (misal: Acefile/GDrive) limit/gagal, otomatis coba hoster berikutnya (misal: Pixeldrain)!
                chosen_h = None
                if not archive_path.exists() or archive_path.stat().st_size < 1024 * 1024:
                    download_success = False
                    for h in hosters:
                        if isinstance(h, str):
                            h = {'url': h, 'hoster': 'Direct'}
                        elif not isinstance(h, dict):
                            continue
                        resolved_url, r_hdrs = await asyncio.to_thread(resolve_kusonime_download_link, h, target_res)
                        if not resolved_url:
                            continue

                        h_disp = h.get('hoster', 'Direct') if isinstance(h, dict) else 'Direct'
                        log("BATCH_DL", f"📥 Mengunduh arsip batch {db_title} [{target_res}] ({pkg_title}) dari {h_disp}...", BOLD + CYAN)
                        update_heartbeat(status="running", current_task=f"📦 Unduh Batch: {db_title} [{target_res}] ({h_disp})")
                        
                        # min_speed_mb=0.5 agar tidak terbunuh oleh watchdog saat mengunduh arsip batch besar dari Pixeldrain/Mega
                        dl_ok = await download_file(resolved_url, archive_path, target_res, min_speed_mb=0.5)
                        if dl_ok and archive_path.exists() and archive_path.stat().st_size >= 1024 * 1024:
                            download_success = True
                            chosen_h = h
                            break
                        else:
                            log("BATCH_WARN", f"Unduhan batch {db_title} [{target_res}] dari {h_disp} gagal/terputus. Mencoba hoster berikutnya...", YELLOW)
                            cleanup_file(archive_path)

                    if not download_success:
                        log("BATCH_ERR", f"Seluruh hoster batch {db_title} [{target_res}] ({pkg_title}) gagal diunduh. Mencoba resolusi lain...", YELLOW)
                        continue
                else:
                    chosen_h = {'hoster': 'LocalCache'}

                # 5. Baca daftar isi arsip tanpa ekstraksi total
                entries = await asyncio.to_thread(list_archive_contents, archive_path, candidate_passwords=["kusonime.com", "", "www.kusonime.com"])
                if not entries:
                    log("BATCH_ERR", f"Isi arsip batch {db_title} [{target_res}] tidak dapat dibaca atau kosong.", YELLOW)
                    free_gb = shutil.disk_usage(str(TEMP_DOWNLOAD_DIR)).free / (1024**3)
                    if free_gb < 3.0:
                        cleanup_file(archive_path)
                    continue

                log("BATCH_INFO", f"✓ Arsip batch {db_title} [{target_res}] terbaca ({len(entries)} episode). Memulai ekstraksi bertahap...", GREEN)

                processed_any = False
                for entry in entries:
                    ep_num = entry['episode']

                    # A. ACTIVE PREEMPTION GUARD (Ongoing Adalah Raja):
                    # Jika terdeteksi aktivitas ongoing aktif, segera jeda proses batch dan dahulukan ongoing!
                    if _ACTIVE_PROCESSING_TASKS > 1:
                        log("PREEMPTION", f"⚡ INTERUPSI ONGOING: Ada episode ongoing masuk! Menjeda batch {db_title} dan mendahulukan ongoing...", BOLD + YELLOW)
                        free_gb = shutil.disk_usage(str(TEMP_DOWNLOAD_DIR)).free / (1024**3)
                        if free_gb < 5.0:
                            cleanup_file(archive_path)
                        return True

                    # B. IDEMPOTENT DB CHECK: Cek apakah episode ep_num sudah memiliki target_res di DB Nipnime
                    ep_chk_payload = {'title': f"{db_title} Episode {ep_num}", 'episode_number': ep_num, 'auto_create_episode': True}
                    try:
                        ep_status, ep_data = await async_request_nipnime_api('POST', f"match-title?token={WORKER_TOKEN}", ep_chk_payload, headers=headers, timeout=12)
                        if ep_status != 200 or not isinstance(ep_data, dict):
                            async with session.post(f"{match_url}?token={WORKER_TOKEN}", json=ep_chk_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=12)) as ep_resp:
                                ep_data = await ep_resp.json()
                    except Exception:
                        ep_data = {}

                    ep_obj = ep_data.get('episode') or {}
                    episode_id = ep_obj.get('id')
                    tg_qualities = set(ep_obj.get('telegram_qualities') or [])

                    if target_res in tg_qualities:
                        continue  # Episode sudah memiliki resolusi ini, lewati

                    if not episode_id:
                        continue

                    # C. PROGRESSIVE EXTRACTION: Ekstrak TEPAT 1 episode ke temp disk dengan progress dashboard
                    entry_sz_str = format_bytes(entry.get('size', 0)) if format_bytes else f"{entry.get('size', 0)} B"
                    log("BATCH_EXTRACT", f"📦 Mengekstrak Ep {ep_num} ({entry['filename']}, {entry_sz_str}) dari arsip batch {db_title} [{target_res}]...", CYAN)
                    entry_sz = int(entry.get('size', 0) or 0)
                    extract_task_key = f"extract_{db_slug}_{ep_num}_{target_res}"
                    def _on_extract_progress(p, cur_m, tot_m, spd_m, eta_s, st_txt=""):
                        PROGRESS_MGR.update(
                            key=extract_task_key,
                            label=f"[Ekstrak {target_res}] {db_title} Ep {ep_num}",
                            cur_mb=round(cur_m, 1),
                            tot_mb=round(tot_m, 1),
                            pct=round(p, 1),
                            speed_mb=round(spd_m, 1),
                            eta_str=eta_s,
                            status_text=st_txt or f"Mengekstrak {entry['filename']}",
                            category="tamat"
                        )
                        update_heartbeat(status="running", current_task=f"[TAMAT] 📦 Ekstrak: {db_title} Ep {ep_num} [{target_res}]: {p:.0f}% ({cur_m:.1f}/{tot_m:.1f} MB) @ {spd_m:.1f} MB/s")

                    extracted_file = None
                    try:
                        extracted_file = await asyncio.to_thread(
                            extract_single_episode,
                            archive_path,
                            entry['internal_path'],
                            TEMP_DOWNLOAD_DIR,
                            progress_callback=_on_extract_progress,
                            expected_size=entry_sz
                        )
                    finally:
                        PROGRESS_MGR.remove(extract_task_key)

                    if not extracted_file or not extracted_file.exists():
                        log("EXTRACT_ERR", f"Gagal mengekstrak episode {ep_num} dari arsip {archive_path.name}.", YELLOW)
                        continue

                    video_file = None
                    wm_file = None
                    try:
                        # D. STREAM COMPATIBILITY GUARD: Remux MKV softsub ke MP4 untuk player web HTML5
                        video_file = await asyncio.to_thread(stream_compatibility_guard, extracted_file)

                        # E. WATERMARK BRANDING RESMI NIPNIME.COM
                        src_info = f"Kusonime Batch ({chosen_h['hoster']}) - {target_res} Tamat"
                        upload_target = video_file
                        if ENABLE_WATERMARK:
                            try:
                                log("BATCH_WM", f"🎨 Menyematkan watermark resmi NIPNIME.COM untuk {db_title} Ep {ep_num} [{target_res}]...", CYAN)
                                update_heartbeat(status="running", current_task=f"🎨 Watermark Batch: {db_title} Ep {ep_num} [{target_res}]")
                                wm_res = await apply_nipnime_watermark(video_file, target_res, src_info)
                                if wm_res and wm_res.exists() and wm_res != video_file:
                                    upload_target = wm_res
                                    wm_file = wm_res
                            except Exception as wme:
                                log("BATCH_WM_WARN", f"Gagal menerapkan watermark pada batch ({wme}). Mengunggah video asli.", YELLOW)

                        # F. UPLOAD KE TELEGRAM & DAFTARKAN KE DATABASE NIPNIME
                        update_heartbeat(status="running", current_task=f"📤 Unggah Batch: {db_title} Ep {ep_num} [{target_res}]")
                        msg_id = await upload_video_to_telegram(
                            tg_client, upload_target, db_title, ep_num, target_res, src_info,
                            skip_watermark=True, is_tamat=True, episode_id=episode_id
                        )

                        if msg_id:
                            await submit_to_nipnime(session, episode_id, target_res, msg_id, anime_title=db_title, ep_num=ep_num, dont_exit=True)
                            tg_qualities.add(target_res)
                            c_eps = set(item.get('completed_eps', []))
                            c_eps.add(ep_num)
                            item['completed_eps'] = sorted(list(c_eps))
                            item['last_checked_ep'] = max(item.get('last_checked_ep', 0), ep_num)
                            save_completed_state(state)
                            log("BATCH_DONE", f"✓ Berhasil memproses batch ber-watermark: {db_title} Ep {ep_num} [{target_res}] (Telegram Msg ID: {msg_id})!", BOLD + GREEN)
                            processed_any = True

                            if target_res == '1080p' and ENABLE_2K_UPSCALE:
                                if not should_worker_upscale_2k_locally():
                                    await delegate_2k_handover(session, anime_obj, ep_num, episode_id, msg_id)
                    finally:
                        # G. HAPUS FILE EKSTRAK & FILE WATERMARK DARI DISK LOKAL INSTAN
                        if wm_file:
                            cleanup_file(wm_file)
                        if video_file:
                            cleanup_file(video_file)
                        cleanup_file(extracted_file)

                    # H. TELEGRAM RATE-LIMIT COOLDOWN
                    await asyncio.sleep(3)

                # Hapus file arsip batch setelah seluruh episode selesai diproses
                cleanup_file(archive_path)
                if processed_any:
                    return True

        return False
    finally:
        await release_episode_lock(session, f"batch_{db_title}", 1)

async def delegate_2k_handover(
    session: aiohttp.ClientSession,
    anime_obj: dict,
    ep_num: int,
    episode_id: int,
    source_msg_id: int
) -> bool:
    """Mendelegasikan tugas render upscale 2K QHD ke worker cluster lain melalui Telegram CDN bus."""
    db_title = anime_obj.get('title', '')
    anime_id = anime_obj.get('id')
    db_slug = anime_obj.get('slug', '')
    payload = {
        'anime_id': anime_id,
        'anime_title': db_title,
        'anime_slug': db_slug,
        'episode_number': ep_num,
        'episode_id': episode_id,
        'source_msg_id': source_msg_id,
        'source_channel_id': TELEGRAM_CHANNEL_ID,
        'delegated_by': get_worker_id()
    }
    headers = {
        'X-Terop-Token': WORKER_TOKEN,
        'Content-Type': 'application/json'
    }
    try:
        url = f"{API_URL}/2k-handover/delegate?token={WORKER_TOKEN}"
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get('success'):
                    log("CLUSTER_2K", f"🚀 Berhasil delegasikan tugas 2K {db_title} Ep {ep_num} ke worker cluster lain via Telegram CDN (Job ID: {data.get('job_id')})", BOLD + CYAN)
                    return True
    except Exception as e:
        log("CLUSTER_2K_WARN", f"Gagal delegasi 2K: {e}", YELLOW)
    return False

async def check_and_process_2k_handover(tg_client: Client, session: aiohttp.ClientSession) -> bool:
    """
    Mengecek dan mengeksekusi tugas delegasi render 2K QHD dari worker lain di cluster (PRD Section 5.2).
    - Memeriksa endpoint /2k-handover/claim jika sisa disk >= 20.0 GB.
    - Menghormati CasaOS CPU Guard (server dilarang render tanpa GPU).
    - Staging Vault di Worker B: folder temp_downloads/staging_2k/, batas max 4 file master.
    - Status master dicatat secured_on_disk setelah unduh selesai.
    - Menjalankan render 2K dengan badge eksklusif NIPNIME.COM ❖ 2K ULTRA HD.
    - Setelah selesai diunggah, file staging dihapus dan tugas ditandai complete.
    """
    if not ENABLE_2K_UPSCALE:
        return False

    if get_device_role() == "server" and has_active_remote_workers():
        return False

    if get_device_role() == "server" and not check_has_nvenc():
        return False

    free_gb = shutil.disk_usage(str(TEMP_DOWNLOAD_DIR)).free / (1024**3)
    if free_gb < 20.0:
        return False

    render_q = get_render_queue()
    if render_q and render_q.qsize() > 0:
        return False

    staging_2k_dir = TEMP_DOWNLOAD_DIR / "staging_2k"
    staging_2k_dir.mkdir(parents=True, exist_ok=True)
    staged_files = [f for f in staging_2k_dir.iterdir() if f.is_file() and f.suffix.lower() == '.mp4']
    if len(staged_files) >= 4:
        log("STAGING_2K", f"⚠️ Staging vault 2K penuh ({len(staged_files)}/4 file). Menunda klaim tugas baru...", YELLOW)
        return False

    payload = {
        'worker_name': get_worker_id(),
        'free_disk_gb': round(free_gb, 2)
    }
    headers = {
        'X-Terop-Token': WORKER_TOKEN,
        'Content-Type': 'application/json'
    }

    master_dest = None
    out_2k = None
    try:
        url = f"{API_URL}/2k-handover/claim?token={WORKER_TOKEN}"
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return False
            data = await resp.json()
            job = data.get('job')
            if not job or not isinstance(job, dict):
                return False

            job_id = job.get('job_id')
            db_title = job.get('anime_title', '')
            ep_num = job.get('episode_number', 1)
            episode_id = job.get('episode_id')
            source_msg_id = job.get('source_msg_id')
            source_chan = job.get('source_channel_id') or TELEGRAM_CHANNEL_ID

            log("CLUSTER_2K", f"🎯 Mengklaim tugas 2K cluster: {db_title} Ep {ep_num} (Job: {job_id}) dari worker {job.get('delegated_by')}...", BOLD + CYAN)
            update_heartbeat(status="running", current_task=f"🎬 2K Upscale Cluster: {db_title} Ep {ep_num}")

            safe_slug = safe_file_slug(db_title, 40)
            master_dest = staging_2k_dir / f"master_1080p_{safe_slug}_ep{ep_num}.mp4"
            msg = await tg_client.get_messages(source_chan, message_ids=source_msg_id)
            if not msg or not (msg.video or msg.document):
                log("CLUSTER_2K_ERR", f"Pesan Telegram {source_msg_id} tidak ditemukan atau bukan video.", RED)
                return False

            media = msg.video or msg.document
            log("CLUSTER_2K_DL", f"📥 Mengunduh master 1080p ke Staging Vault ({round(media.file_size / 1048576, 2)} MB)...", CYAN)
            if SMART_DEBUGGER:
                SMART_DEBUGGER.update_phase("downloading_source", detail=f"Master 1080p for 2K: {db_title} Ep {ep_num}")

            dl_ok = await fast_download_media(tg_client, media, master_dest)
            if not dl_ok or not master_dest.exists() or master_dest.stat().st_size < 1024 * 1024:
                log("CLUSTER_2K_ERR", f"Gagal unduh master 1080p dari Telegram.", RED)
                cleanup_file(master_dest)
                return False

            log("CLUSTER_2K_STAGED", f"🔒 [STAGING VAULT] Master 1080p {db_title} Ep {ep_num} aman di disk ({round(master_dest.stat().st_size / 1048576, 1)} MB). Status: secured_on_disk", BOLD + GREEN)
            update_heartbeat(status="running", current_task=f"Secured on disk: {db_title} Ep {ep_num}")

            log("CLUSTER_2K_RENDER", f"🎨 Merender 2K QHD Eksklusif: {db_title} Ep {ep_num}...", BOLD + CYAN)
            if SMART_DEBUGGER:
                SMART_DEBUGGER.update_phase("rendering_ffmpeg", detail=f"2K QHD: {db_title} Ep {ep_num}")

            out_2k = await apply_nipnime_watermark(master_dest, "2k", f"Cluster Delegated 2K ({job.get('delegated_by')})")
            cleanup_file(master_dest)
            master_dest = None

            if not out_2k or not out_2k.exists() or out_2k.stat().st_size < 1024 * 1024:
                log("CLUSTER_2K_ERR", f"Gagal render 2K untuk {db_title} Ep {ep_num}.", RED)
                cleanup_file(out_2k)
                out_2k = None
                return False

            src_info = f"2K QHD Cluster ({get_worker_id()}) - Nipnime Stream"
            if SMART_DEBUGGER:
                SMART_DEBUGGER.update_phase("uploading_telegram", detail=f"2K QHD: {db_title} Ep {ep_num}")

            msg_id_2k = await upload_video_to_telegram(
                tg_client, out_2k, db_title, ep_num, "2K", src_info,
                skip_watermark=True, is_tamat=True, episode_id=episode_id
            )
            cleanup_file(out_2k)
            out_2k = None

            if msg_id_2k:
                await submit_to_nipnime(session, episode_id, "2K", msg_id_2k, anime_title=db_title, ep_num=ep_num, dont_exit=True)
                c_url = f"{API_URL}/2k-handover/complete?token={WORKER_TOKEN}"
                await session.post(c_url, json={'job_id': job_id, 'completed_by': get_worker_id(), 'msg_id_2k': msg_id_2k}, headers=headers)
                log("CLUSTER_2K_DONE", f"✓ Berhasil menyelesaikan tugas 2K cluster: {db_title} Ep {ep_num} (Msg ID 2K: {msg_id_2k})!", BOLD + GREEN)
                if SMART_DEBUGGER:
                    SMART_DEBUGGER.update_phase("idle")
                return True

    except Exception as e:
        log("CLUSTER_2K_ERR", f"Kendala pada tugas 2K handover: {e}", YELLOW)
    finally:
        if SMART_DEBUGGER:
            SMART_DEBUGGER.update_phase("idle")
        if master_dest:
            cleanup_file(master_dest)
        if out_2k:
            cleanup_file(out_2k)

    return False

async def try_process_kuramanime_batch(
    tg_client: Client,
    session: aiohttp.ClientSession,
    anime_obj: dict,
    item: dict,
    state: dict,
    state_lock: asyncio.Lock,
    headers: dict,
    match_url: str
) -> bool:
    """
    Mencari dan memproses paket batch dari Kuramanime untuk anime tamat.
    Mengurai tab Episode | Batch melalui endpoint /api/terop/resolve-batch-source.
    Mendukung direct download Pixeldrain, Mediafire, dan kDrive.
    """
    if not resolve_batch_direct_url:
        return False

    if not isinstance(item, dict):
        return False

    if isinstance(anime_obj, list):
        anime_obj = anime_obj[0] if (anime_obj and isinstance(anime_obj[0], dict)) else {}
    elif not isinstance(anime_obj, dict):
        anime_obj = {}

    db_title = anime_obj.get('title') or item.get('title', '')
    anime_id = anime_obj.get('id')
    db_slug = anime_obj.get('slug') or normalize_title(db_title).replace(' ', '-')
    total_eps = int(anime_obj.get('total_episodes') or 0)
    source_url = item.get('url', '')

    kura_cache = item.get('kuramanime_batch_info')
    if not isinstance(kura_cache, dict):
        kura_cache = {}
        item['kuramanime_batch_info'] = kura_cache
    if kura_cache.get('not_found_until', 0) > time.time():
        return False

    batch_url = None
    if 'kuramanime' in source_url:
        if '/batch/' in source_url:
            batch_url = source_url
        else:
            range_str = f"1-{total_eps}" if total_eps > 0 else "1-12"
            batch_url = f"{source_url.rstrip('/')}/batch/{range_str}"

    if not batch_url:
        aid = item.get('anime_id')
        aslug = item.get('anime_slug') or db_slug
        if aid and aslug:
            range_str = f"1-{total_eps}" if total_eps > 0 else "1-12"
            batch_url = f"https://v20.kuramanime.ing/anime/{aid}/{aslug}/batch/{range_str}"

    if not batch_url:
        return False

    claim_success = await claim_episode_lock(session, f"batch_{db_title}", 1, anime_id, ttl=3600)
    if not claim_success:
        return False

    try:
        log("KURAMA_BATCH", f"🔍 Memeriksa ketersediaan paket batch Kuramanime: {batch_url}...", CYAN)
        api_req = {'source': 'kuramanime', 'url': batch_url}
        status, data = await async_request_nipnime_api('POST', f"resolve-batch-source?token={WORKER_TOKEN}", api_req, headers=headers, timeout=50)

        if status != 200 or not isinstance(data, dict) or not data.get('success'):
            kura_cache['not_found_until'] = time.time() + 86400
            save_completed_state(state)
            log("KURAMA_BATCH_SKIP", f"Paket batch Kuramanime '{db_title}' tidak ditemukan di halaman {batch_url}.", GRAY)
            return False

        resolutions = data.get('resolutions', {})
        if isinstance(resolutions, list):
            res_dict = {}
            for itm in resolutions:
                if isinstance(itm, dict):
                    r_tag = (itm.get('resolution') or itm.get('res') or itm.get('quality') or '').lower()
                    if r_tag:
                        res_dict[r_tag] = itm
            resolutions = res_dict

        if not resolutions or not isinstance(resolutions, dict):
            kura_cache['not_found_until'] = time.time() + 86400
            save_completed_state(state)
            return False

        log("KURAMA_BATCH", f"📦 Ditemukan {len(resolutions)} varian resolusi batch Kuramanime untuk '{db_title}': {', '.join(resolutions.keys())}!", BOLD + GREEN)

        for target_res in ['1080p', '720p', '480p', '360p']:
            if target_res not in resolutions:
                continue

            p_end = total_eps if total_eps > 0 else 12
            is_complete_already = await check_batch_package_already_complete_in_db(
                session, headers, match_url, db_title, 1, p_end, target_res
            )
            if is_complete_already:
                log("BATCH_SKIP", f"✓ Seluruh episode (1-{p_end}) {db_title} [{target_res}] SUDAH LENGKAP di database. Melewati unduhan paket Kuramanime.", GREEN)
                continue

            res_info = resolutions.get(target_res)
            if not res_info:
                continue

            if isinstance(res_info, list):
                hosters = res_info
            elif isinstance(res_info, dict):
                hosters = res_info.get('hosters', [])
                if not hosters and 'url' in res_info:
                    hosters = [res_info]
            else:
                hosters = []

            safe_slug = safe_file_slug(db_slug or db_title, 40)
            archive_name = f"kura_batch_{safe_slug}_{target_res}.rar"
            archive_path = TEMP_DOWNLOAD_DIR / archive_name

            chosen_h = None
            if not archive_path.exists() or archive_path.stat().st_size < 1024 * 1024:
                download_success = False
                for h in hosters:
                    if isinstance(h, str):
                        h = {'url': h, 'hoster': 'Direct'}
                    elif not isinstance(h, dict):
                        continue
                    resolved_url, r_hdrs = await asyncio.to_thread(resolve_batch_direct_url, h)
                    if not resolved_url:
                        continue

                    h_disp = h.get('hoster', 'Direct') if isinstance(h, dict) else 'Direct'
                    log("BATCH_DL", f"📥 Mengunduh arsip batch Kuramanime {db_title} [{target_res}] dari {h_disp}...", BOLD + CYAN)
                    update_heartbeat(status="running", current_task=f"📦 Unduh Batch: {db_title} [{target_res}] ({h_disp})")
                    dl_ok = await download_file(resolved_url, archive_path, target_res, min_speed_mb=0.5)
                    if dl_ok and archive_path.exists() and archive_path.stat().st_size >= 1024 * 1024:
                        download_success = True
                        chosen_h = h
                        break
                    else:
                        log("BATCH_WARN", f"Unduhan batch Kuramanime [{target_res}] dari {h_disp} gagal. Mencoba hoster cadangan...", YELLOW)
                        cleanup_file(archive_path)

                if not download_success:
                    log("BATCH_ERR", f"Seluruh hoster arsip batch Kuramanime {db_title} [{target_res}] gagal diunduh.", YELLOW)
                    continue
            else:
                chosen_h = {'hoster': 'LocalCache'}

            entries = await asyncio.to_thread(list_archive_contents, archive_path, candidate_passwords=["", "kuramanime", "kuramanime.pro", "kusonime.com"])
            if not entries:
                log("BATCH_ERR", f"Isi arsip batch Kuramanime {db_title} [{target_res}] tidak dapat dibaca atau kosong.", YELLOW)
                free_gb = shutil.disk_usage(str(TEMP_DOWNLOAD_DIR)).free / (1024**3)
                if free_gb < 3.0:
                    cleanup_file(archive_path)
                continue

            log("BATCH_INFO", f"✓ Arsip batch Kuramanime {db_title} [{target_res}] terbaca ({len(entries)} episode). Memulai ekstraksi bertahap...", GREEN)

            processed_any = False
            for entry in entries:
                ep_num = entry['episode']

                if _ACTIVE_PROCESSING_TASKS > 1:
                    log("PREEMPTION", f"⚡ INTERUPSI ONGOING: Ada episode ongoing masuk! Menjeda batch {db_title} dan mendahulukan ongoing...", BOLD + YELLOW)
                    free_gb = shutil.disk_usage(str(TEMP_DOWNLOAD_DIR)).free / (1024**3)
                    if free_gb < 5.0:
                        cleanup_file(archive_path)
                    return True

                ep_chk_payload = {'title': f"{db_title} Episode {ep_num}", 'episode_number': ep_num, 'auto_create_episode': True}
                try:
                    ep_status, ep_data = await async_request_nipnime_api('POST', f"match-title?token={WORKER_TOKEN}", ep_chk_payload, headers=headers, timeout=12)
                    if ep_status != 200 or not isinstance(ep_data, dict):
                        async with session.post(f"{match_url}?token={WORKER_TOKEN}", json=ep_chk_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=12)) as ep_resp:
                            ep_data = await ep_resp.json()
                except Exception:
                    ep_data = {}

                ep_obj = ep_data.get('episode') or {}
                episode_id = ep_obj.get('id')
                tg_qualities = set(ep_obj.get('telegram_qualities') or [])

                if target_res in tg_qualities:
                    continue

                if not episode_id:
                    continue

                entry_sz = int(entry.get('size', 0) or 0)
                extract_task_key = f"extract_{db_slug}_{ep_num}_{target_res}"
                def _on_extract_progress_kura(p, cur_m, tot_m, spd_m, eta_s, st_txt=""):
                    PROGRESS_MGR.update(
                        key=extract_task_key,
                        label=f"[Ekstrak {target_res}] {db_title} Ep {ep_num}",
                        cur_mb=round(cur_m, 1),
                        tot_mb=round(tot_m, 1),
                        pct=round(p, 1),
                        speed_mb=round(spd_m, 1),
                        eta_str=eta_s,
                        status_text=st_txt or f"Mengekstrak {entry['filename']}",
                        category="tamat"
                    )
                    update_heartbeat(status="running", current_task=f"[TAMAT] 📦 Ekstrak: {db_title} Ep {ep_num} [{target_res}]: {p:.0f}% ({cur_m:.1f}/{tot_m:.1f} MB) @ {spd_m:.1f} MB/s")

                log("BATCH_EXTRACT", f"📦 Mengekstrak Ep {ep_num} dari arsip batch Kuramanime {db_title} [{target_res}]...", CYAN)
                extracted_file = None
                try:
                    extracted_file = await asyncio.to_thread(
                        extract_single_episode,
                        archive_path,
                        entry['internal_path'],
                        TEMP_DOWNLOAD_DIR,
                        progress_callback=_on_extract_progress_kura,
                        expected_size=entry_sz
                    )
                finally:
                    PROGRESS_MGR.remove(extract_task_key)
                if not extracted_file or not extracted_file.exists():
                    log("EXTRACT_ERR", f"Gagal mengekstrak episode {ep_num} dari arsip Kuramanime.", YELLOW)
                    continue

                video_file = None
                wm_file = None
                try:
                    video_file = await asyncio.to_thread(stream_compatibility_guard, extracted_file)

                    src_info = f"Kuramanime Batch ({chosen_h['hoster']}) - {target_res} Tamat"
                    upload_target = video_file
                    if ENABLE_WATERMARK:
                        try:
                            log("BATCH_WM", f"🎨 Menyematkan watermark resmi NIPNIME.COM untuk {db_title} Ep {ep_num} [{target_res}]...", CYAN)
                            update_heartbeat(status="running", current_task=f"🎨 Watermark Batch: {db_title} Ep {ep_num} [{target_res}]")
                            wm_res = await apply_nipnime_watermark(video_file, target_res, src_info)
                            if wm_res and wm_res.exists() and wm_res != video_file:
                                upload_target = wm_res
                                wm_file = wm_res
                        except Exception as wme:
                            log("BATCH_WM_WARN", f"Gagal menerapkan watermark ({wme}). Mengunggah video asli.", YELLOW)

                    update_heartbeat(status="running", current_task=f"📤 Unggah Batch: {db_title} Ep {ep_num} [{target_res}]")
                    msg_id = await upload_video_to_telegram(
                        tg_client, upload_target, db_title, ep_num, target_res, src_info,
                        skip_watermark=True, is_tamat=True, episode_id=episode_id
                    )

                    if msg_id:
                        await submit_to_nipnime(session, episode_id, target_res, msg_id, anime_title=db_title, ep_num=ep_num, dont_exit=True)
                        tg_qualities.add(target_res)
                        c_eps = set(item.get('completed_eps', []))
                        c_eps.add(ep_num)
                        item['completed_eps'] = sorted(list(c_eps))
                        item['last_checked_ep'] = max(item.get('last_checked_ep', 0), ep_num)
                        save_completed_state(state)
                        log("BATCH_DONE", f"✓ Berhasil memproses batch Kuramanime: {db_title} Ep {ep_num} [{target_res}] (Telegram Msg ID: {msg_id})!", BOLD + GREEN)
                        processed_any = True

                        if target_res == '1080p' and ENABLE_2K_UPSCALE:
                            if not should_worker_upscale_2k_locally():
                                await delegate_2k_handover(session, anime_obj, ep_num, episode_id, msg_id)
                finally:
                    if wm_file:
                        cleanup_file(wm_file)
                    if video_file:
                        cleanup_file(video_file)
                    cleanup_file(extracted_file)

                await asyncio.sleep(3)

            cleanup_file(archive_path)
            if processed_any:
                return True

        return False
    finally:
        await release_episode_lock(session, f"batch_{db_title}", 1)

async def try_process_otakudesu_batch(
    tg_client: Client,
    session: aiohttp.ClientSession,
    anime_obj: dict,
    item: dict,
    state: dict,
    state_lock: asyncio.Lock,
    headers: dict,
    match_url: str
) -> bool:
    """
    Mencari dan memproses paket batch dari Otakudesu untuk anime tamat.
    Mendukung direct download OtakuDrive & DesuDrive (Google Drive CDN), AceFile, Mega, dan Pixeldrain.
    """
    if not parse_otakudesu_batch_page or not resolve_batch_direct_url:
        return False

    if not isinstance(item, dict):
        return False

    if isinstance(anime_obj, list):
        anime_obj = anime_obj[0] if (anime_obj and isinstance(anime_obj[0], dict)) else {}
    elif not isinstance(anime_obj, dict):
        anime_obj = {}

    db_title = anime_obj.get('title') or item.get('title', '')
    anime_id = anime_obj.get('id')
    db_slug = anime_obj.get('slug') or normalize_title(db_title).replace(' ', '-')
    total_eps = int(anime_obj.get('total_episodes') or 0)
    source_url = item.get('url', '')

    otaku_cache = item.get('otakudesu_batch_info')
    if not isinstance(otaku_cache, dict):
        otaku_cache = {}
        item['otakudesu_batch_info'] = otaku_cache
    if otaku_cache.get('not_found_until', 0) > time.time():
        return False

    batch_url = None
    if 'otakudesu' in source_url:
        if '/batch/' in source_url:
            batch_url = source_url
        elif '/anime/' in source_url:
            status, a_html = await fetch_html_stealth(session, source_url)
            if status == 200 and a_html:
                m_b = re.findall(r'href="(https?://[^"]*otakudesu[^"]*/batch/[^"]+)"', a_html)
                if m_b:
                    batch_url = m_b[0]

    if not batch_url:
        return False

    claim_success = await claim_episode_lock(session, f"batch_{db_title}", 1, anime_id, ttl=3600)
    if not claim_success:
        return False

    try:
        log("OTAKU_BATCH", f"🔍 Memeriksa ketersediaan paket batch Otakudesu: {batch_url}...", CYAN)
        resolutions = await asyncio.to_thread(parse_otakudesu_batch_page, batch_url, 15)
        if not resolutions:
            otaku_cache['not_found_until'] = time.time() + 86400
            save_completed_state(state)
            return False

        # Anti-Halu 1080p: Deteksi resolusi yang nyata tersedia di paket batch Otakudesu
        found_res = [r for r in ['1080p', '720p', '480p', '360p'] if resolutions.get(r)]
        if found_res:
            item['available_resolutions'] = found_res
            save_completed_state(state)

        log("OTAKU_BATCH", f"📦 Ditemukan {len(resolutions)} varian resolusi batch Otakudesu untuk '{db_title}': {', '.join(resolutions.keys())}!", BOLD + GREEN)

        for target_res in ['1080p', '720p', '480p', '360p']:
            hosters = resolutions.get(target_res, [])
            if not hosters:
                continue

            p_end = total_eps if total_eps > 0 else 12
            is_complete_already = await check_batch_package_already_complete_in_db(
                session, headers, match_url, db_title, 1, p_end, target_res
            )
            if is_complete_already:
                log("BATCH_SKIP", f"✓ Seluruh episode (1-{p_end}) {db_title} [{target_res}] SUDAH LENGKAP di database. Melewati unduhan paket Otakudesu.", GREEN)
                continue

            safe_slug = safe_file_slug(db_slug or db_title, 40)
            archive_name = f"otaku_batch_{safe_slug}_{target_res}.rar"
            archive_path = TEMP_DOWNLOAD_DIR / archive_name

            chosen_h = None
            if not archive_path.exists() or archive_path.stat().st_size < 1024 * 1024:
                download_success = False
                for h in hosters:
                    if isinstance(h, str):
                        h = {'url': h, 'hoster': 'Direct'}
                    elif not isinstance(h, dict):
                        continue
                    resolved_url, r_hdrs = await asyncio.to_thread(resolve_batch_direct_url, h)
                    if not resolved_url:
                        continue

                    h_disp = h.get('hoster', 'Direct') if isinstance(h, dict) else 'Direct'
                    log("BATCH_DL", f"📥 Mengunduh arsip batch Otakudesu {db_title} [{target_res}] dari {h_disp}...", BOLD + CYAN)
                    update_heartbeat(status="running", current_task=f"📦 Unduh Batch: {db_title} [{target_res}] ({h_disp})")
                    dl_ok = await download_file(resolved_url, archive_path, target_res, min_speed_mb=0.5)
                    if dl_ok and archive_path.exists() and archive_path.stat().st_size >= 1024 * 1024:
                        download_success = True
                        chosen_h = h
                        break
                    else:
                        log("BATCH_WARN", f"Unduhan batch Otakudesu [{target_res}] dari {h_disp} gagal. Mencoba hoster cadangan...", YELLOW)
                        cleanup_file(archive_path)

                if not download_success:
                    log("BATCH_ERR", f"Seluruh hoster arsip batch Otakudesu {db_title} [{target_res}] gagal diunduh.", YELLOW)
                    continue
            else:
                chosen_h = {'hoster': 'LocalCache'}

            entries = await asyncio.to_thread(list_archive_contents, archive_path, candidate_passwords=["", "otakudesu.com", "www.otakudesu.com", "kusonime.com"])
            if not entries:
                log("BATCH_ERR", f"Isi arsip batch Otakudesu {db_title} [{target_res}] tidak dapat dibaca atau kosong.", YELLOW)
                free_gb = shutil.disk_usage(str(TEMP_DOWNLOAD_DIR)).free / (1024**3)
                if free_gb < 3.0:
                    cleanup_file(archive_path)
                continue

            log("BATCH_INFO", f"✓ Arsip batch Otakudesu {db_title} [{target_res}] terbaca ({len(entries)} episode). Memulai ekstraksi bertahap...", GREEN)

            processed_any = False
            for entry in entries:
                ep_num = entry['episode']

                if _ACTIVE_PROCESSING_TASKS > 1:
                    log("PREEMPTION", f"⚡ INTERUPSI ONGOING: Ada episode ongoing masuk! Menjeda batch {db_title} dan mendahulukan ongoing...", BOLD + YELLOW)
                    free_gb = shutil.disk_usage(str(TEMP_DOWNLOAD_DIR)).free / (1024**3)
                    if free_gb < 5.0:
                        cleanup_file(archive_path)
                    return True

                ep_chk_payload = {'title': f"{db_title} Episode {ep_num}", 'episode_number': ep_num, 'auto_create_episode': True}
                try:
                    ep_status, ep_data = await async_request_nipnime_api('POST', f"match-title?token={WORKER_TOKEN}", ep_chk_payload, headers=headers, timeout=12)
                    if ep_status != 200 or not isinstance(ep_data, dict):
                        async with session.post(f"{match_url}?token={WORKER_TOKEN}", json=ep_chk_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=12)) as ep_resp:
                            ep_data = await ep_resp.json()
                except Exception:
                    ep_data = {}

                ep_obj = ep_data.get('episode') or {}
                episode_id = ep_obj.get('id')
                tg_qualities = set(ep_obj.get('telegram_qualities') or [])

                if target_res in tg_qualities:
                    continue

                if not episode_id:
                    continue

                entry_sz = int(entry.get('size', 0) or 0)
                entry_sz_str = format_bytes(entry_sz) if format_bytes else f"{entry_sz} B"
                extract_task_key = f"extract_{db_slug}_{ep_num}_{target_res}"
                def _on_extract_progress_otk(p, cur_m, tot_m, spd_m, eta_s, st_txt=""):
                    PROGRESS_MGR.update(
                        key=extract_task_key,
                        label=f"[Ekstrak {target_res}] {db_title} Ep {ep_num}",
                        cur_mb=round(cur_m, 1),
                        tot_mb=round(tot_m, 1),
                        pct=round(p, 1),
                        speed_mb=round(spd_m, 1),
                        eta_str=eta_s,
                        status_text=st_txt or f"Mengekstrak {entry['filename']}",
                        category="tamat"
                    )
                    update_heartbeat(status="running", current_task=f"[TAMAT] 📦 Ekstrak: {db_title} Ep {ep_num} [{target_res}]: {p:.0f}% ({cur_m:.1f}/{tot_m:.1f} MB) @ {spd_m:.1f} MB/s")

                log("BATCH_EXTRACT", f"📦 Mengekstrak Ep {ep_num} ({entry['filename']}, {entry_sz_str}) dari arsip batch Otakudesu {db_title} [{target_res}]...", CYAN)
                extracted_file = None
                try:
                    extracted_file = await asyncio.to_thread(
                        extract_single_episode,
                        archive_path,
                        entry['internal_path'],
                        TEMP_DOWNLOAD_DIR,
                        progress_callback=_on_extract_progress_otk,
                        expected_size=entry_sz
                    )
                finally:
                    PROGRESS_MGR.remove(extract_task_key)
                if not extracted_file or not extracted_file.exists():
                    log("EXTRACT_ERR", f"Gagal mengekstrak episode {ep_num} dari arsip {archive_path.name}.", YELLOW)
                    continue

                video_file = None
                wm_file = None
                try:
                    video_file = await asyncio.to_thread(stream_compatibility_guard, extracted_file)

                    src_info = f"Otakudesu Batch ({chosen_h.get('hoster', 'Direct') if isinstance(chosen_h, dict) else 'Direct'}) - {target_res} Tamat"
                    upload_target = video_file
                    if ENABLE_WATERMARK:
                        try:
                            log("BATCH_WM", f"🎨 Menyematkan watermark resmi NIPNIME.COM untuk {db_title} Ep {ep_num} [{target_res}]...", CYAN)
                            update_heartbeat(status="running", current_task=f"🎨 Watermark Batch: {db_title} Ep {ep_num} [{target_res}]")
                            wm_res = await apply_nipnime_watermark(video_file, target_res, src_info)
                            if wm_res and wm_res.exists() and wm_res != video_file:
                                upload_target = wm_res
                                wm_file = wm_res
                        except Exception as wme:
                            log("BATCH_WM_WARN", f"Gagal menerapkan watermark pada batch Otakudesu ({wme}). Mengunggah video asli.", YELLOW)

                    update_heartbeat(status="running", current_task=f"📤 Unggah Batch: {db_title} Ep {ep_num} [{target_res}]")
                    msg_id = await upload_video_to_telegram(
                        tg_client, upload_target, db_title, ep_num, target_res, src_info,
                        skip_watermark=True, is_tamat=True, episode_id=episode_id
                    )

                    if msg_id:
                        await submit_to_nipnime(session, episode_id, target_res, msg_id, anime_title=db_title, ep_num=ep_num, dont_exit=True)
                        tg_qualities.add(target_res)
                        c_eps = set(item.get('completed_eps', []))
                        c_eps.add(ep_num)
                        item['completed_eps'] = sorted(list(c_eps))
                        item['last_checked_ep'] = max(item.get('last_checked_ep', 0), ep_num)
                        save_completed_state(state)
                        log("BATCH_UPLOAD_SUCCESS", f"🎉 Sukses upload Ep {ep_num} [{target_res}] dari paket batch Otakudesu {db_title} (Telegram Msg ID: {msg_id})!", BOLD + GREEN)
                        processed_any = True

                        if target_res == '1080p' and ENABLE_2K_UPSCALE:
                            if not should_worker_upscale_2k_locally():
                                await delegate_2k_handover(session, anime_obj, ep_num, episode_id, msg_id)
                finally:
                    if wm_file:
                        cleanup_file(wm_file)
                    if video_file:
                        cleanup_file(video_file)
                    cleanup_file(extracted_file)

                await asyncio.sleep(3)

            cleanup_file(archive_path)
            if processed_any:
                return True

        return False
    finally:
        await release_episode_lock(session, f"batch_{db_title}", 1)

async def try_process_multi_source_batch(
    tg_client: Client,
    session: aiohttp.ClientSession,
    anime_obj: dict,
    item: dict,
    state: dict,
    state_lock: asyncio.Lock,
    headers: dict,
    match_url: str
) -> bool:
    """
    PRIORITAS 1 MUTLAK BATCH INGESTION (Anime Tamat):
    Mencoba secara bertingkat:
    1. Kuramanime Batch (kDrive, Mediafire, Pixeldrain)
    2. Kusonime Batch (Google Drive CDN, Acefile, Pixeldrain)
    3. Otakudesu Batch (OtakuDrive & DesuDrive Google CDN, AceFile, Mega, Pixeldrain)
    DILARANG mengunduh episode satu per satu jika paket batch tersedia.
    """
    if get_device_role() == "server" and has_active_remote_workers():
        return False
    try:
        if await try_process_kuramanime_batch(tg_client, session, anime_obj, item, state, state_lock, headers, match_url):
            return True
    except Exception as ke:
        lineno = getattr(getattr(ke, '__traceback__', None), 'tb_lineno', '?')
        log("KURAMA_BATCH_ERR", f"Kendala saat proses Kuramanime batch: {ke} (Line: {lineno})", YELLOW)

    try:
        if await try_process_kusonime_batch(tg_client, session, anime_obj, item, state, state_lock, headers, match_url):
            return True
    except Exception as kuse:
        lineno = getattr(getattr(kuse, '__traceback__', None), 'tb_lineno', '?')
        log("KUSONIME_BATCH_ERR", f"Kendala saat proses Kusonime batch: {kuse} (Line: {lineno})", YELLOW)

    try:
        if await try_process_otakudesu_batch(tg_client, session, anime_obj, item, state, state_lock, headers, match_url):
            return True
    except Exception as oe:
        lineno = getattr(getattr(oe, '__traceback__', None), 'tb_lineno', '?')
        log("OTAKU_BATCH_ERR", f"Kendala saat proses Otakudesu batch: {oe} (Line: {lineno})", YELLOW)

    return False

async def process_completed_anime_step(tg_client: Client, session: aiohttp.ClientSession, concurrency: int = 1) -> bool:
    """Memeriksa dan melengkapi episode anime tamat saat tidak ada antrian ongoing yang aktif."""
    if get_device_role() == "server" and has_active_remote_workers():
        return False
    state = load_completed_state()
    queue = state.setdefault('queue', [])
    history = state.setdefault('history', {})

    # 1. Jika antrian kosong, coba sinkronkan dari server atau scrape daftar anime tamat
    pending = [it for it in queue if it.get('status') in ('pending', 'in_progress')]
    if not pending:
        if get_device_role() in REMOTE_ROLES:
            sync_res = sync_state_from_server()
            if sync_res and sync_res.get('completed_state'):
                state = ensure_completed_state_dict(sync_res['completed_state'])
                queue = state.get('queue', [])
    # HARD QUEUE FREEZE: Jika antrean sudah memiliki item (len(queue) > 0), DILARANG KERAS menambah / scrape antrian baru!
    # Fokus tuntaskan antrean yang ada satu per satu sampai 100% Selesai.
    if len(queue) == 0:
        source_turn = state.get('source_turn', 'kusonime')
        added = 0
        if source_turn == 'kusonime':
            page = state.get('kusonime_page', 1)
            url = f"https://kusonime.com/page/{page}/"
            log("TAMAT", f"🔍 Memindai arsip anime tamat dari Kusonime (Halaman {page})...", CYAN)
            status, html = await fetch_html_stealth(session, url)
            if status == 200 and html:
                matches = re.findall(r'<h2[^>]*class=["\']episodeye["\'][^>]*>\s*<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, flags=re.I)
                for a_url, raw_t in matches:
                    title = re.sub(r'<[^>]+>', '', raw_t).strip()
                    norm = normalize_title(title)
                    if norm not in history and not any(it['title'].lower() == title.lower() for it in queue):
                        queue.append({
                            'title': title,
                            'url': a_url,
                            'source': 'Kusonime',
                            'status': 'pending',
                            'last_checked_ep': 0
                        })
                        added += 1
                state['kusonime_page'] = page + 1
            else:
                log("TAMAT_WARN", f"Scrape Kusonime (Halaman {page}) [HTTP {status}].", YELLOW)
            state['source_turn'] = 'otakudesu'
        elif source_turn == 'otakudesu':
            page = state.get('otakudesu_page', 1)
            url = f"https://otakudesu.blog/complete-anime/page/{page}/"
            log("TAMAT", f"🔍 Memindai arsip anime tamat dari Otakudesu (Halaman {page})...", CYAN)
            status, html = await fetch_html_stealth(session, url)
            if status == 200 and html:
                matches = re.findall(r'<div[^>]*class="thumb"[^>]*>\s*<a\s+href="([^"]+)"[^>]*>[\s\S]*?<h2[^>]*class="jdlflm"[^>]*>(.*?)</h2>', html, flags=re.I)
                for a_url, raw_t in matches:
                    title = raw_t.strip()
                    norm = normalize_title(title)
                    if norm not in history and not any(it['title'].lower() == title.lower() for it in queue):
                        queue.append({
                            'title': title,
                            'url': a_url,
                            'source': 'Otakudesu',
                            'status': 'pending',
                            'last_checked_ep': 0
                        })
                        added += 1
                state['otakudesu_page'] = page + 1
            else:
                log("TAMAT_WARN", f"Scrape Otakudesu (Halaman {page}) [HTTP {status}].", YELLOW)
            state['source_turn'] = 'kuramanime'
        else:
            page = state.get('kuramanime_page', 1)
            url = f"https://v20.kuramanime.ing/quick/finished?order_by=updated&page={page}"
            log("TAMAT", f"🔍 Memindai arsip anime tamat dari Kuramanime (Halaman {page})...", CYAN)
            status, html = await fetch_html_stealth(session, url)
            if status == 200 and html:
                matches = re.findall(r'<h5[^>]*>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.I)
                if not matches:
                    matches = re.findall(r'<a\s+href="(https?://[^"]*kuramanime[^"]*/anime/\d+/[^"]+)"[^>]*>([^<]+)</a>', html, flags=re.I)
                for a_url, raw_t in matches:
                    title = raw_t.strip()
                    norm = normalize_title(title)
                    if norm not in history and not any(it['title'].lower() == title.lower() for it in queue):
                        queue.append({
                            'title': title,
                            'url': a_url,
                            'source': 'Kuramanime',
                            'status': 'pending',
                            'last_checked_ep': 0
                        })
                        added += 1
                state['kuramanime_page'] = page + 1
            else:
                log("TAMAT_WARN", f"Scrape Kuramanime (Halaman {page}) [HTTP {status}].", YELLOW)
            state['source_turn'] = 'kusonime'

        save_completed_state(state)
        if added:
            log("TAMAT", f"📦 Ditambahkan {added} anime tamat ke antrian pemrosesan idle.", GREEN)

    now_ts = time.time()
    # Anti-False Completion: Jika anime berstatus in_progress atau pending, pastikan dihapus dari history
    # agar tidak dibajak oleh history lama yang belum selesai.
    for it in queue:
        norm = normalize_title(it.get('title', ''))
        if it.get('status') in ('in_progress', 'pending'):
            history.pop(norm, None)
        elif it.get('status') == 'complete':
            history[norm] = 'complete'

    pending = [
        it for it in queue 
        if it.get('status') in ('pending', 'in_progress')
        and (not it.get('retry_after') or now_ts >= it['retry_after'])
    ]
    if not pending:
        if get_device_role() in REMOTE_ROLES:
            sync_res = sync_state_from_server()
            if sync_res and sync_res.get('completed_state'):
                state = ensure_completed_state_dict(sync_res['completed_state'])
                queue = state.get('queue', [])
                history = state.get('history', {})
                for it in queue:
                    norm = normalize_title(it.get('title', ''))
                    if it.get('status') in ('in_progress', 'pending'):
                        history.pop(norm, None)
                    elif it.get('status') == 'complete':
                        history[norm] = 'complete'
        pending = [
            it for it in queue 
            if it.get('status') in ('pending', 'in_progress')
            and (not it.get('retry_after') or now_ts >= it['retry_after'])
        ]
    if not pending:
        return False

    # CLUSTER FOCUS DISCIPLINE: Urutkan antrean berdasarkan persentase kelengkapan tertinggi ke terendah
    # agar seluruh worker berkonvergensi menuntaskan anime yang paling dekat ke 100% Selesai!
    def _get_anime_sort_score(it):
        pct = float(it.get('pct', 0) or 0)
        done_count = len(it.get('completed_eps', []))
        total_e = max(1, int(it.get('total_episodes') or 12))
        return (pct, done_count / total_e, done_count)

    pending.sort(key=_get_anime_sort_score, reverse=True)

    chosen_item = None
    chosen_candidates = []
    chosen_db_title = ""
    chosen_db_slug = ""
    state_lock = asyncio.Lock()

    match_url = f"{API_URL}/match-title"
    headers = {
        'X-Terop-Token': WORKER_TOKEN,
        'Authorization': f"Bearer {WORKER_TOKEN}",
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': DEFAULT_UA
    }

    # --------------------------------------------------------------------------
    # PASS 1: Prioritas Shard Utama
    # Pindai antrian anime untuk mencari episode yang sesuai shard worker ini.
    # Jika anime A tidak ada sisa episode untuk shard ini, lanjut ke anime B, C, dst.
    # --------------------------------------------------------------------------
    for item in pending[:40]:
        anime_title = item.get('title', '')
        norm_title = normalize_title(anime_title)
        known_done = set(item.get('completed_eps', []))

        # Cek cepat: jika total_episodes sudah tercatat dan semua episode shard sudah beres, lewati
        total_eps_hint = int(item.get('total_episodes') or 0)
        if total_eps_hint > 0 and WORKER_SHARD not in ('all', 'semua', 'none', '*', ''):
            shard_eps = [e for e in range(1, total_eps_hint + 1) if is_episode_in_shard(e)]
            if shard_eps and all(e in known_done for e in shard_eps):
                continue

        match_payload = {'title': anime_title, 'episode_number': 1, 'auto_create_episode': False}
        m_status, m_data = await async_request_nipnime_api('POST', f"match-title?token={WORKER_TOKEN}", match_payload, headers=headers, timeout=15)
        if m_status != 200 or not isinstance(m_data, dict):
            try:
                async with session.post(f"{match_url}?token={WORKER_TOKEN}", json=match_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as m_resp:
                    m_status = m_resp.status
                    m_data = await m_resp.json()
            except Exception as me:
                log("TAMAT_WARN", f"Gagal mencocokkan anime tamat '{anime_title}': {me}", YELLOW)
                continue

        if not isinstance(m_data, dict) or not m_data.get('matched'):
            if m_status != 200:
                retry_sec = 60
                if isinstance(m_data, dict) and m_data.get('retry_after'):
                    try: retry_sec = int(m_data.get('retry_after'))
                    except Exception: pass
                item['retry_after'] = time.time() + retry_sec
                save_completed_state(state)
                log("TAMAT_ERR", f"Gagal API mencocokkan '{anime_title}' [HTTP {m_resp.status}: {m_data}]. Menunda coba ulang {retry_sec}s...", YELLOW)
                if m_resp.status == 429:
                    await asyncio.sleep(min(retry_sec, 10))
                continue
            log("TAMAT_SKIP", f"Anime tamat '{anime_title}' tidak ditemukan di database Nipnime. Melewati...", GRAY)
            item['status'] = 'not_in_db'
            history[norm_title] = 'not_in_db'
            save_completed_state(state)
            continue

        anime_obj = m_data.get('anime', {})
        if isinstance(anime_obj, list):
            anime_obj = anime_obj[0] if (anime_obj and isinstance(anime_obj[0], dict)) else {}
        elif not isinstance(anime_obj, dict):
            anime_obj = {}
        db_title = anime_obj.get('title') or anime_title
        db_slug = anime_obj.get('slug') or normalize_title(db_title).replace(' ', '-')
        total_eps = int(anime_obj.get('total_episodes') or 0)

        source_url = item.get('url', '')
        ep_links_map = ensure_ep_links_dict(item.get('ep_links_map'))
        if not ep_links_map and source_url and 'otakudesu' in source_url:
            status, a_html = await fetch_html_stealth(session, source_url)
            if status == 200 and a_html:
                ep_links = re.findall(r'<a\s+href="(https?://[^"]*otakudesu[^"]*/episode/[^"]+)"[^>]*>(.*?)</a>', a_html)
                for e_url, e_txt in ep_links:
                    num_m = re.search(r'episode\s*(\d+)', e_txt, re.I)
                    if num_m:
                        ep_links_map[str(int(num_m.group(1)))] = e_url
                item['ep_links_map'] = ep_links_map
                save_completed_state(state)
        item['ep_links_map'] = ep_links_map

        if not total_eps and ep_links_map:
            total_eps = max([int(k) for k in ep_links_map.keys()])
        if not total_eps:
            total_eps = 12
        item['total_episodes'] = total_eps

        # ----------------------------------------------------------------------
        # PRIORITAS 1 MUTLAK: MULTI-SOURCE BATCH INGESTION (Kuramanime & Kusonime)
        # Sesuai aturan: Worker DILARANG mengunduh episode satu per satu untuk anime tamat
        # jika paket batch tersedia di salah satu repositori batch!
        # ----------------------------------------------------------------------
        try:
            batch_handled = await try_process_multi_source_batch(
                tg_client, session, anime_obj, item, state, state_lock, headers, match_url
            )
            if batch_handled:
                return True
        except Exception as batch_err:
            log("BATCH_ERR", f"Kendala saat proses multi-source batch '{db_title}': {batch_err}", YELLOW)

        known_done = set()
        item_candidates = []

        for ep_num in range(1, total_eps + 1):
            failed_eps = item.get('failed_eps')
            if not isinstance(failed_eps, dict):
                failed_eps = {}
                item['failed_eps'] = failed_eps
            if str(ep_num) in failed_eps:
                if now_ts < failed_eps[str(ep_num)]:
                    continue
                else:
                    failed_eps.pop(str(ep_num), None)

            # Cek partisi shard terlebih dahulu sebelum melakukan HTTP request ke API Nipnime
            if not is_episode_in_shard(ep_num):
                continue

            ep_chk_payload = {'title': f"{db_title} Episode {ep_num}", 'episode_number': ep_num, 'auto_create_episode': True}
            try:
                ep_status, ep_data = await async_request_nipnime_api('POST', f"match-title?token={WORKER_TOKEN}", ep_chk_payload, headers=headers, timeout=15)
                if ep_status == 429:
                    log("TAMAT_WARN", f"Rate limit [429] saat cek episode {ep_num}. Jeda sejenak...", YELLOW)
                    await asyncio.sleep(5)
                    continue
                if ep_status != 200 or not isinstance(ep_data, dict):
                    async with session.post(f"{match_url}?token={WORKER_TOKEN}", json=ep_chk_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as ep_resp:
                        if ep_resp.status == 429:
                            log("TAMAT_WARN", f"Rate limit [429] saat cek episode {ep_num}. Jeda sejenak...", YELLOW)
                            await asyncio.sleep(5)
                            continue
                        ep_data = await ep_resp.json()
            except Exception:
                continue

            if not isinstance(ep_data, dict) or not ep_data.get('matched'):
                continue

            ep_obj = ep_data.get('episode') or {}
            episode_id = ep_obj.get('id')
            tg_qualities = set(ep_obj.get('telegram_qualities') or [])

            has_2k = '2k' in tg_qualities or '1440p' in tg_qualities
            avail_res = item.get('available_resolutions') or []
            has_1080p_in_batch = ('1080p' in avail_res) if avail_res else True

            # Anti-Halu 1080p: jika batch tidak menyediakan 1080p, maka 720p sudah memenuhi HD!
            if not has_1080p_in_batch:
                has_hd = ('720p' in tg_qualities or '1080p' in tg_qualities)
            else:
                has_hd = ('1080p' in tg_qualities or '720p' in tg_qualities)

            if is_2k_required():
                is_ep_complete = (has_hd and has_2k) or (tg_qualities and has_2k and not has_hd)
            else:
                is_ep_complete = has_hd

            if is_ep_complete:
                log("TAMAT_EXIST", f"[COMPLETED] {db_title} Ep {ep_num} sudah lengkap di Telegram ({', '.join(tg_qualities)}).", GRAY)
                known_done.add(ep_num)
                item['completed_eps'] = sorted(list(known_done))
                item['last_checked_ep'] = max(item.get('last_checked_ep', 0), ep_num)
                save_completed_state(state)
                continue

            if not episode_id:
                continue

            claimed = await claim_episode_lock(session, db_title, ep_num, anime_obj.get('id'))
            if not claimed:
                continue

            item_candidates.append((ep_num, episode_id, tg_qualities, False))
            if len(item_candidates) >= max(1, concurrency):
                break

        if len(known_done) >= total_eps:
            item['status'] = 'complete'
            item['completed_eps'] = sorted(list(known_done))
            history[norm_title] = 'complete'
            save_completed_state(state)
            log("TAMAT_FINISH", f"[COMPLETE] Seluruh episode anime tamat '{db_title}' ({len(known_done)}/{total_eps}) telah selesai!", BOLD + GREEN)
        else:
            if known_done:
                item['completed_eps'] = sorted(list(known_done))
            item['status'] = 'in_progress'
            history.pop(norm_title, None)
            save_completed_state(state)

        if item_candidates:
            chosen_item = item
            chosen_candidates = item_candidates
            chosen_db_title = db_title
            chosen_db_slug = db_slug
            break

    # --------------------------------------------------------------------------
    # PASS 2: GOTONG ROYONG / WORK-STEALING (Anti-Nganggur Cluster)
    # Jika worker ini tidak memiliki episode tersisa di shard utamanya pada SEMUA
    # anime dalam antrean, worker akan membantu (steal) episode yang belum selesai
    # dari anime teratas agar tidak ada worker yang nganggur.
    # --------------------------------------------------------------------------
    if not chosen_candidates:
        for item in pending[:25]:
            anime_title = item.get('title', '')
            norm_title = normalize_title(anime_title)
            known_done = set()

            match_payload = {'title': anime_title, 'episode_number': 1, 'auto_create_episode': False}
            m_status, m_data = await async_request_nipnime_api('POST', f"match-title?token={WORKER_TOKEN}", match_payload, headers=headers, timeout=15)
            if m_status != 200 or not isinstance(m_data, dict):
                try:
                    async with session.post(f"{match_url}?token={WORKER_TOKEN}", json=match_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as m_resp:
                        m_data = await m_resp.json()
                except Exception:
                    continue

            if not isinstance(m_data, dict) or not m_data.get('matched'):
                continue

            anime_obj = m_data.get('anime', {})
            db_title = anime_obj.get('title') or anime_title
            db_slug = anime_obj.get('slug') or normalize_title(db_title).replace(' ', '-')
            total_eps = int(anime_obj.get('total_episodes') or 0)
            if not total_eps:
                total_eps = 12

            item_candidates = []
            for ep_num in range(1, total_eps + 1):

                failed_eps = item.get('failed_eps', {})
                if str(ep_num) in failed_eps and now_ts < failed_eps[str(ep_num)]:
                    continue

                ep_chk_payload = {'title': f"{db_title} Episode {ep_num}", 'episode_number': ep_num, 'auto_create_episode': True}
                try:
                    ep_status, ep_data = await async_request_nipnime_api('POST', f"match-title?token={WORKER_TOKEN}", ep_chk_payload, headers=headers, timeout=15)
                    if ep_status != 200 or not isinstance(ep_data, dict):
                        async with session.post(f"{match_url}?token={WORKER_TOKEN}", json=ep_chk_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as ep_resp:
                            ep_data = await ep_resp.json()
                except Exception:
                    continue

                if not isinstance(ep_data, dict) or not ep_data.get('matched'):
                    continue

                ep_obj = ep_data.get('episode') or {}
                episode_id = ep_obj.get('id')
                tg_qualities = set(ep_obj.get('telegram_qualities') or [])

                has_2k = '2k' in tg_qualities or '1440p' in tg_qualities
                avail_res = item.get('available_resolutions') or []
                has_1080p_in_batch = ('1080p' in avail_res) if avail_res else True

                # Anti-Halu 1080p: jika batch tidak menyediakan 1080p, maka 720p sudah memenuhi HD!
                if not has_1080p_in_batch:
                    has_hd = ('720p' in tg_qualities or '1080p' in tg_qualities)
                else:
                    has_hd = ('1080p' in tg_qualities or '720p' in tg_qualities)

                if is_2k_required():
                    is_ep_complete = (has_hd and has_2k) or (tg_qualities and has_2k and not has_hd)
                else:
                    is_ep_complete = has_hd

                if is_ep_complete:
                    known_done.add(ep_num)
                    continue

                if not episode_id:
                    continue

                claimed = await claim_episode_lock(session, db_title, ep_num, anime_obj.get('id'))
                if not claimed:
                    continue

                log("GOTONG_ROYONG", f"[GOTONG_ROYONG] Shard [{get_shard_description()}] membantu {db_title} Ep {ep_num} agar tidak ada worker nganggur...", BOLD + CYAN)
                item_candidates.append((ep_num, episode_id, tg_qualities, True))
                if len(item_candidates) >= max(1, concurrency):
                    break

            if item_candidates:
                chosen_item = item
                chosen_candidates = item_candidates
                chosen_db_title = db_title
                chosen_db_slug = db_slug
                break

    if not chosen_candidates:
        return False

    chosen_item['status'] = 'in_progress'
    save_completed_state(state)

    state_lock = asyncio.Lock()
    if len(chosen_candidates) == 1:
        ep_n, ep_id, tg_q, is_gr = chosen_candidates[0]
        return await ingest_single_completed_episode(ep_n, chosen_item, state, tg_client, session, chosen_db_title, chosen_db_slug, ep_id, tg_q, state_lock, is_gotong_royong=is_gr)
    else:
        log("TURBO", f"[TURBO] Memproses {len(chosen_candidates)} episode {chosen_db_title} serentak secara paralel [Turbo {len(chosen_candidates)}x]...", BOLD + CYAN)
        c_sem = asyncio.Semaphore(len(chosen_candidates))
        async def _run_c(ep_n, ep_id, tg_q, is_gr):
            async with c_sem:
                return await ingest_single_completed_episode(ep_n, chosen_item, state, tg_client, session, chosen_db_title, chosen_db_slug, ep_id, tg_q, state_lock, is_gotong_royong=is_gr)

        tasks = [asyncio.create_task(_run_c(n, i, q, gr)) for n, i, q, gr in chosen_candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return any(r is True for r in results)


async def start_relay_queue_processor(client: Client, session: aiohttp.ClientSession):
    """
    Background Task di Server CasaOS:
    Memantau direktori 'relay_uploads/' secara berkelanjutan. Jika remote worker (misal PC Warnet GPU)
    telah mengunggah video rendered via HTTPS API upload-relay, server CasaOS yang memiliki koneksi
    penuh ke Telegram MTProto akan otomatis mengunggah video tersebut ke Telegram channel,
    mendapatkan Message ID, dan mendaftarkannya ke database Nipnime agar langsung tayang di website!
    """
    relay_dir = SCRIPT_DIR / 'relay_uploads'
    relay_dir.mkdir(parents=True, exist_ok=True)
    log("RELAY_PROCESSOR", "🚀 Antrean Upload Relay CasaOS aktif (Memantau delegasi GPU remote worker)...", BOLD + GREEN)
    active_relay_files = set()

    while True:
        try:
            meta_files = sorted(list(relay_dir.glob('*.json')), key=lambda f: f.stat().st_mtime)
            for m_file in meta_files:
                if m_file.name.startswith('.tmp') or m_file.name in active_relay_files:
                    continue

                try:
                    with open(m_file, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                except Exception as je:
                    log("RELAY_ERR", f"Gagal membaca meta JSON {m_file.name}: {je}", YELLOW)
                    continue

                video_path_str = str(m_file)[:-5]
                video_file = Path(video_path_str)
                if not video_file.exists():
                    continue

                # Pastikan file video sudah selesai ditulis (mtime > 2 detik)
                if (time.time() - video_file.stat().st_mtime) < 2:
                    continue

                active_relay_files.add(m_file.name)
                try:
                    anime_title = meta.get('anime_title', '')
                    episode_num = meta.get('episode_num', '')
                    episode_id = meta.get('episode_id', 0)
                    quality = meta.get('quality', '1080p')
                    source_info = meta.get('source_info', 'Nipnime Render')
                    is_tamat = meta.get('is_tamat', False)
                    worker_id = meta.get('worker_id', 'remote')
                    server_name_custom = meta.get('server_name')
                    overwrite = meta.get('overwrite', True)

                    log("RELAY_UP", f"📤 [CASAOS RELAY] Mengunggah hasil render GPU dari {worker_id} ke Telegram: {anime_title} Ep {episode_num} [{quality}]...", BOLD + CYAN)

                    # Unggah video ke Telegram menggunakan koneksi MTProto server CasaOS
                    # Karena video sudah ber-watermark dari GPU remote, skip_watermark=True!
                    tg_msg_id = await upload_video_to_telegram(
                        client=client,
                        file_path=video_file,
                        anime_title=anime_title,
                        episode_num=episode_num,
                        quality=quality,
                        source_info=f"{source_info} [{worker_id}]",
                        skip_watermark=True,
                        is_tamat=is_tamat,
                        episode_id=episode_id
                    )

                    if tg_msg_id and tg_msg_id != -999:
                        log("RELAY_DONE", f"✓ [CASAOS RELAY] Video {anime_title} Ep {episode_num} [{quality}] sukses diunggah ke Telegram (Msg ID: {tg_msg_id})!", BOLD + GREEN)

                        # Cari atau pastikan episode_id jika bernilai 0
                        if not episode_id:
                            try:
                                headers = {'X-Terop-Token': WORKER_TOKEN, 'Accept': 'application/json'}
                                payload = {'title': f"{anime_title} Episode {episode_num}", 'auto_create_episode': True, 'episode_number': episode_num}
                                ep_status, m_data = await async_request_nipnime_api('POST', f"match-title?token={WORKER_TOKEN}", payload, headers=headers, timeout=15)
                                if (ep_status != 200 or not isinstance(m_data, dict)) and session:
                                    async with session.post(match_url, json=payload, headers=headers) as m_resp:
                                        if m_resp.status == 200:
                                            m_data = await m_resp.json()
                                if m_data and isinstance(m_data, dict):
                                    ep_obj = m_data.get('episode')
                                    if ep_obj:
                                        episode_id = ep_obj.get('id')
                            except Exception as me:
                                log("RELAY_MATCH_ERR", f"Gagal mencocokkan episode_id untuk {anime_title}: {me}", YELLOW)

                        if episode_id:
                            await submit_to_nipnime(
                                session=session,
                                episode_id=episode_id,
                                quality=quality,
                                message_id=tg_msg_id,
                                anime_title=anime_title,
                                ep_num=episode_num,
                                server_name_custom=server_name_custom,
                                dont_exit=True,
                                overwrite=overwrite
                            )
                            log("RELAY_REGISTERED", f"🎉 [WEB PUBLISHED] {anime_title} Ep {episode_num} [{quality}] SUDAH TAYANG DI SITUS NIPNIME!", BOLD + GREEN)

                        # Bersihkan file video dan meta dari disk server
                        try: video_file.unlink()
                        except Exception: pass
                        try: m_file.unlink()
                        except Exception: pass
                    else:
                        log("RELAY_ERR", f"Gagal mengunggah video relay {video_file.name} ke Telegram.", RED)
                finally:
                    active_relay_files.discard(m_file.name)

        except asyncio.CancelledError:
            break
        except Exception as e:
            log("RELAY_LOOP_ERR", f"Kendala pada processor antrean relay: {e}", YELLOW)

        await asyncio.sleep(5)


# ==============================================================================
# 6. MAIN DAEMON LOOP
# ==============================================================================
async def run_ongoing_daemon(interval_sec: int = 60, concurrency: int = 1):
    if not check_credentials():
        return

    session_dir = SCRIPT_DIR / '.tg_sessions'
    session_dir.mkdir(parents=True, exist_ok=True)

    device_role = get_device_role()
    if device_role in REMOTE_ROLES:
        start_lease_keeper(device_role)
        sync_state_from_server()
    safe_wid = re.sub(r'[^a-zA-Z0-9_-]', '_', get_worker_id())
    session_name = os.getenv('TG_SESSION_NAME', f'nipnime_{safe_wid}')

    tg_proxy = get_telegram_proxy_config()
    client_kwargs = {
        'name': session_name,
        'api_id': int(API_ID),
        'api_hash': API_HASH,
        'bot_token': BOT_TOKEN,
        'workdir': str(session_dir),
        'max_concurrent_transmissions': 8,
        'ipv6': False
    }
    if tg_proxy:
        client_kwargs['proxy'] = tg_proxy
        log("PROXY", f"⚡ Menggunakan Proxy Telegram MTProto: {tg_proxy['scheme']}://{tg_proxy['hostname']}:{tg_proxy['port']}", CYAN)

    TARGET_DCS = [
        ("91.108.56.130", 443, "DC 5 Singapura (Asia) Port 443"),
        ("91.108.56.130", 80,  "DC 5 Singapura (Asia) Port 80"),
        ("91.108.56.130", 5222,"DC 5 Singapura (Asia) Port 5222"),
        ("149.154.167.91", 443, "DC 4 Eropa Port 443"),
        ("149.154.175.53", 443, "DC 1 Miami Port 443"),
        ("149.154.167.51", 443, "DC 2 Belanda Port 443"),
        ("149.154.167.51", 80,  "DC 2 Belanda Port 80"),
        ("149.154.167.51", 5222,"DC 2 Belanda Port 5222"),
    ]
    global _RELAY_UPLOAD_MODE, FAST_RELEASE_FIRST
    tg_connected = False
    attempt = 0
    client = None
    failed_proxy_counts = {}

    if _RELAY_UPLOAD_MODE and device_role in REMOTE_ROLES:
        log("RELAY_MODE", "🌐 [CLUSTER UPLOAD RELAY] Mode Upload Relay HTTPS aktif dari konfigurasi/lingkungan.", BOLD + GREEN)
        client = None
        tg_connected = True
        FAST_RELEASE_FIRST = False

    while not tg_connected:
        attempt += 1
        # Alternasikan antara Proxy (pada percobaan ganjil) dan Direct Obfuscated (pada percobaan genap)
        # Ini memastikan jika proxy lokal macet/hang, worker otomatis mencoba Direct ke DC Singapore/Eropa!
        use_proxy_this_round = (attempt % 2 == 1)
        detected_proxy = get_telegram_proxy_config(attempt) if use_proxy_this_round else None

        # Jika proxy ini sudah gagal >= 2 kali, lewati proxy tersebut
        if detected_proxy:
            pkey = f"{detected_proxy['scheme']}://{detected_proxy['hostname']}:{detected_proxy['port']}"
            if failed_proxy_counts.get(pkey, 0) >= 2:
                detected_proxy = None
                log("PROXY_SKIP", f"⚡ Melewati proxy {pkey} karena tidak merespons MTProto -> Mencoba koneksi Direct Obfuscated MTProto!", YELLOW)

        if detected_proxy:
            proxy_clean = {k: v for k, v in detected_proxy.items() if not k.startswith('_')}
            if client_kwargs.get('proxy') != proxy_clean:
                client_kwargs['proxy'] = proxy_clean
                lbl = detected_proxy.get('_label', f"{proxy_clean['scheme']}://{proxy_clean['hostname']}:{proxy_clean['port']}")
                log("PROXY_AUTO", f"⚡ Terdeteksi proxy bypass aktif: {lbl} -> Mengalihkan MTProto Telegram lewat proxy!", BOLD + GREEN)
            tg_proxy = proxy_clean
        else:
            if 'proxy' in client_kwargs:
                client_kwargs.pop('proxy', None)
                tg_proxy = None
            if attempt > 1 and not use_proxy_this_round:
                log("DIRECT_MODE", "⚡ Mencoba koneksi LANGSUNG Obfuscated MTProto (Bypass DPI Anti-Blokir)...", CYAN)

        dc_idx = ((attempt - 1) // 2) % len(TARGET_DCS) if attempt > 1 else 0
        target_ip, current_port, dc_desc = TARGET_DCS[dc_idx]
        set_telegram_dc_target(target_ip, current_port)
        client_kwargs['ipv6'] = False

        p_cfg = client_kwargs.get('proxy')
        proxy_desc = f" via Proxy {p_cfg['scheme']}://{p_cfg['hostname']}:{p_cfg['port']}" if p_cfg else " (Direct Obfuscated MTProto)"
        att_str = f" [Percobaan #{attempt} | {dc_desc}{proxy_desc}]"
        log("START", f"Memulai Client Telegram MTProto ({device_role.upper()})...{att_str}", CYAN)
        update_heartbeat(status="running", current_task=f"[START] Menghubungkan Telegram ({device_role.upper()}) [{dc_desc}{proxy_desc}]...")
        
        client = Client(**client_kwargs)
        try:
            await asyncio.wait_for(client.start(), timeout=18.0)
            tg_connected = True
            log("PORT_SUCCESS", f"✓ Sukses terhubung ke Telegram MTProto menggunakan {dc_desc}{proxy_desc}! ({device_role.upper()})", BOLD + GREEN)
            break
        except (asyncio.TimeoutError, Exception) as conn_err:
            try:
                if client and client.is_connected:
                    await client.stop()
            except Exception:
                pass
            
            if p_cfg:
                failed_pkey = f"{p_cfg['scheme']}://{p_cfg['hostname']}:{p_cfg['port']}"
                failed_proxy_counts[failed_pkey] = failed_proxy_counts.get(failed_pkey, 0) + 1

            err_type = conn_err.__class__.__name__
            err_details = f"{err_type}: {conn_err}" if str(conn_err) else f"{err_type} (Timeout 18 detik)"
            next_dc = TARGET_DCS[(dc_idx + 1) % len(TARGET_DCS)]
            log("BLOCKED", f"⚠️ Koneksi ke Telegram {dc_desc}{proxy_desc} gagal ({err_details}). Beralih mencoba {next_dc[2]}...", YELLOW)
            
            if attempt % 3 == 0:
                win_proxy_val = _get_windows_system_proxy() or "Nonaktif"
                psi_ports = _find_psiphon_ports()
                psi_str = f"Aktif di port {psi_ports}" if psi_ports else "Tidak Berjalan"
                log("DIAGNOSA", f"🔍 Status Sistem: Windows Proxy=[{win_proxy_val}], Psiphon=[{psi_str}]", YELLOW)

            # Jika MTProto diblokir di PC Remote (Warnet/Laptop), otomatis aktifkan mode Cluster Upload Relay!
            if device_role in REMOTE_ROLES and attempt >= 3:
                log("RELAY_MODE", "🌐 [CLUSTER UPLOAD RELAY AKTIF] Telegram MTProto diblokir oleh Mikrotik/ISP jaringan ini.", BOLD + YELLOW)
                log("RELAY_MODE", "⚡ Beralih otomatis ke Mode Render GPU NVENC + Delegasi Upload HTTPS ke Server CasaOS!", BOLD + GREEN)
                _RELAY_UPLOAD_MODE = True
                FAST_RELEASE_FIRST = False
                client = None
                tg_connected = True
                break

            if attempt >= len(TARGET_DCS):
                log("DIAGNOSA", "❌ Seluruh port Telegram MTProto (443, 80, 5222) diblokir oleh Mikrotik/ISP Warnet!", BOLD + RED)
                log("SOLUSI", "💡 CARA MENGATASI DI PC WARNET:", BOLD + GREEN)
                log("SOLUSI", "   1. Buka aplikasi Psiphon di PC warnet sampai statusnya HIJAU (Connected)", CYAN)
                log("SOLUSI", "   2. Atau di Cloudflare WARP, klik Gear ⚙️ -> Pilih '1.1.1.1 with WARP'", CYAN)
                log("SOLUSI", "   3. Atau ubah WARP ke proxy: warp-cli set-mode proxy && warp-cli connect", CYAN)
                update_heartbeat(status="running", current_task="[BLOCKED] Telegram diblokir Mikrotik (Buka Psiphon/WARP)")

            # Cek apakah server mengirim pembaruan skrip saat worker mencoba koneksi
            if _PENDING_AUTO_UPDATE_URL and _PENDING_AUTO_UPDATE_HASH:
                log("AUTO_UPDATE", "🔄 Pembaruan skrip terdeteksi! Memperbarui worker sekarang...", BOLD + YELLOW)
                threading.Thread(target=perform_self_update, args=(_PENDING_AUTO_UPDATE_URL, _PENDING_AUTO_UPDATE_HASH), daemon=False).start()
                return

            await asyncio.sleep(2)

    global _GLOBAL_TG_CLIENT
    _GLOBAL_TG_CLIENT = client
    if client:
        log("AUTH", f"Telegram terhubung! Channel: {CHANNEL_ID} ({device_role.upper()})", GREEN)
        if HAS_TGCRYPTO:
            log("TURBO_CRYPTO", "⚡ AKSELERASI MTPROTO TGCRYPTO AKTIF: Enkripsi hardware C/AES-NI siap upload maksimal (15-40+ MB/s)!", BOLD + GREEN)
        else:
            log("TURBO_CRYPTO", "⚠️ TgCrypto TIDAK AKTIF: Enkripsi berjalan lambat (fallback pure-Python ~0.3 MB/s).", BOLD + YELLOW)
    else:
        log("AUTH", f"🌐 Worker berjalan dalam Mode Delegasi Upload Relay HTTPS ({device_role.upper()}) - Siap Render GPU!", BOLD + GREEN)
        update_heartbeat(status="running", current_task=f"Mode Render GPU + Upload Relay HTTPS ({device_role.upper()})")

    concurrency_text = f" [Paralel {concurrency} Task]" if concurrency > 1 else ""
    log("READY", f"Mode Ongoing Auto-Watcher Aktif ({device_role.upper()})!{concurrency_text}", BOLD + GREEN)
    if WORKER_SHARD not in ('all', 'semua', 'none', '*', ''):
        log("SHARD", f"⚡ PARTISI EPISODE AKTIF: Shard [{get_shard_description().upper()}]", BOLD + CYAN)
        if WORKER_SHARD in ('odd', 'ganjil', '1', '1/2'):
            log("SHARD", "🎯 Worker ini KHUSUS memproses Episode GANJIL (1, 3, 5, 7, 9, ...)", CYAN)
        elif WORKER_SHARD in ('even', 'genap', '2', '2/2'):
            log("SHARD", "🎯 Worker ini KHUSUS memproses Episode GENAP (2, 4, 6, 8, 10, ...)", CYAN)
    if FAST_RELEASE_FIRST:
        log("PIPELINE", "⚡ SISTEM RILIS 2-TAHAP AKTIF: Video raw di-upload instan agar web langsung tayang, lalu render resmi & ganti susulan!", BOLD + GREEN)
    if HAS_CURL_CFFI:
        log("ENGINE", "✓ Engine HTTP Stealth (curl_cffi) aktif untuk bypass Cloudflare & resolver video.", GREEN)
    else:
        log("WARN", "⚠️ Paket 'curl_cffi' TIDAK aktif! Pasang dengan: pip install curl_cffi", YELLOW)

    # Bersihkan file sampah / temporary dari proses sebelumnya
    for tmp_f in TEMP_DOWNLOAD_DIR.glob('*.tmp'):
        try: tmp_f.unlink()
        except Exception: pass

    # Reset cooldown & status not_in_db anime tamat pada startup Colab/Laptop/Azure/AWS agar langsung diproses
    if device_role in REMOTE_ROLES:
        try:
            init_comp = load_completed_state()
            if init_comp and init_comp.get('queue'):
                cleared = 0
                for it in init_comp['queue']:
                    if 'retry_after' in it or 'failed_eps' in it or it.get('status') == 'not_in_db':
                        it.pop('retry_after', None)
                        it.pop('failed_eps', None)
                        if it.get('status') == 'not_in_db':
                            it['status'] = 'pending'
                        cleared += 1
                if 'history' in init_comp and isinstance(init_comp['history'], dict):
                    init_comp['history'] = {k: v for k, v in init_comp['history'].items() if v != 'not_in_db'}
                if cleared:
                    save_completed_state(init_comp)
                    log("STARTUP", f"🔄 Mereset status {cleared} antrian anime tamat agar langsung diproses sekarang.", CYAN)
        except Exception:
            pass

    state = load_ongoing_state()

    # Jalankan background lease & heartbeat keeper agar status worker selalu segar setiap 10 detik
    start_lease_keeper(device_role)

    try:
        async with aiohttp.ClientSession() as session:
            bg_render_task = asyncio.create_task(background_render_worker(client, session))
            if client and getattr(client, 'is_connected', False):
                asyncio.create_task(start_relay_queue_processor(client, session))
            # Pulihkan tugas render watermark dari episode yang baru tayang mentah (Fast Raw) dari sesi sebelumnya
            try:
                await recover_pending_watermarks(client, session, state)
            except Exception as e:
                log("RECOVER_WARN", f"Kendala saat pemulihan watermark pending: {e}", YELLOW)
            was_standby = False
            was_paused = False
            while True:
                try:
                    # 0. Remote Pause Switch dari Web Dashboard (Pause / Standby tanpa uninstall)
                    if is_remotely_paused():
                        if not was_paused:
                            log("STANDBY", "⏸️ [WEB REMOTE] Worker dijeda oleh Admin via Web. Masuk ke mode siaga hemat daya (pemasangan tetap utuh)...", YELLOW)
                            was_paused = True
                        update_heartbeat(status="paused", current_task="⏸️ Worker dijeda oleh Admin via Web (Mode Siaga)")
                        if _PENDING_AUTO_UPDATE_URL and not _AUTO_UPDATE_IN_PROGRESS:
                            log("AUTO_UPDATE", "🎯 Worker dalam mode jeda & bebas tugas. Menjalankan pembaruan otomatis...", BOLD + GREEN)
                            threading.Thread(target=perform_self_update, args=(_PENDING_AUTO_UPDATE_URL, _PENDING_AUTO_UPDATE_HASH), daemon=False).start()
                        await asyncio.sleep(5)
                        continue
                    else:
                        if was_paused:
                            log("RESUME", "▶️ [WEB REMOTE] Sinyal AKTIF diterima dari Web! Worker bangun dan melanjutkan tugas...", BOLD + GREEN)
                            was_paused = False

                    # 0b. Prioritas Auto-Update: Jika ada pembaruan kode baru tertunda dan worker bebas
                    if _PENDING_AUTO_UPDATE_URL and not _AUTO_UPDATE_IN_PROGRESS and is_worker_idle():
                        log("AUTO_UPDATE", "🎯 Versi kode baru terdeteksi! Memperbarui worker sekarang sebelum memindai antrean baru...", BOLD + GREEN)
                        threading.Thread(target=perform_self_update, args=(_PENDING_AUTO_UPDATE_URL, _PENDING_AUTO_UPDATE_HASH), daemon=False).start()
                        await asyncio.sleep(5)
                        continue

                    # Logika Auto-Handover / Failover Pintar antara Remote Worker (Laptop / Colab / Warnet / Azure / AWS) & Server CasaOS
                    if device_role in REMOTE_ROLES:
                        update_worker_lease(device_role)
                    elif device_role == "server":
                        if has_active_remote_workers():
                            if not was_standby:
                                log("STANDBY", "💤 Cluster Remote Worker terdeteksi aktif. Server CasaOS 100% STANDBY SIAGA (tidak melakukan apapun)...", YELLOW)
                                was_standby = True
                            update_heartbeat(status="standby", current_task="💤 Standby Siaga (Cluster Remote Worker Aktif)")
                            await asyncio.sleep(15)
                            continue
                        else:
                            if was_standby:
                                log("TAKEOVER", "⚡ Seluruh remote worker offline. Server CasaOS otomatis mengambil alih pemantauan 24/7!", BOLD + GREEN)
                                was_standby = False
                            update_worker_lease("server")

                    # Sinkronkan state memori dengan disk & server (Smart Merge resolusi antar-worker)
                    disk_state = load_ongoing_state()
                    for dk, dv in disk_state.items():
                        if dk not in state:
                            state[dk] = dv
                        else:
                            disk_comp = set(dv.get('completed_qualities', []))
                            mem_comp = set(state[dk].get('completed_qualities', []))
                            merged_comp = disk_comp.union(mem_comp)
                            state[dk]['completed_qualities'] = list(merged_comp)
                            if dv.get('status') == 'complete':
                                state[dk]['status'] = 'complete'
                                state[dk]['missing_qualities'] = []
                            elif state[dk].get('status') != 'complete':
                                target_q = get_target_qualities()
                                rem_q = [q for q in target_q if q not in merged_comp]
                                state[dk]['missing_qualities'] = rem_q
                                if not rem_q:
                                    state[dk]['status'] = 'complete'

                    log("SCAN", "Memindai rilisan terbaru dari Kuramanime, Samehadaku, AnimeSail, Oploverz, Otakudesu, NontonAnimeID...", CYAN)

                    # Jalankan scan feed rilisan serentak dari 6 sumber anime
                    km_task = asyncio.create_task(scan_kuramanime_latest(session))
                    sm_task = asyncio.create_task(scan_samehadaku_latest(session))
                    as_task = asyncio.create_task(scan_animesail_latest(session))
                    op_task = asyncio.create_task(scan_oploverz_latest(session))
                    ot_task = asyncio.create_task(scan_otakudesu_latest(session))
                    na_task = asyncio.create_task(scan_nontonanimeid_latest(session))

                    results = await asyncio.gather(km_task, sm_task, as_task, op_task, ot_task, na_task, return_exceptions=True)

                    all_new_releases = []
                    for r in results:
                        if isinstance(r, list):
                            all_new_releases.extend(r)

                    # Deduplikasi feed: Pastikan 1 anime & episode HANYA diproses oleh 1 task worker!
                    # Prioritaskan sumber bersih tanpa watermark: AnimeSail > Samehadaku > Otakudesu > Oploverz > Kuramanime > NontonAnimeID
                    source_priority = {'AnimeSail': 6, 'Samehadaku': 5, 'Otakudesu': 4, 'Oploverz': 3, 'Kuramanime': 2, 'NontonAnimeID': 1}
                    unique_releases = {}
                    for r in all_new_releases:
                        if not isinstance(r, dict) or 'anime_title' not in r or 'episode_number' not in r:
                            continue
                        r_key = f"{normalize_title(r['anime_title'])}:{r['episode_number']}"
                        if r_key not in unique_releases:
                            unique_releases[r_key] = r
                        else:
                            curr_src = unique_releases[r_key].get('source', '')
                            new_src = r.get('source', '')
                            if source_priority.get(new_src, 0) > source_priority.get(curr_src, 0):
                                unique_releases[r_key] = r

                    all_candidates = list(unique_releases.values())
                    target_releases = []

                    # Saring rilisan feed yang BELUM selesai (belum status complete)
                    # dan klaim lock secara atomic ke server agar tidak tabrakan antar-worker
                    max_rel_claim = max(1, concurrency)
                    now_loop_ts = time.time()
                    for r in all_candidates:
                        r_title = r.get('anime_title', '')
                        r_ep = r.get('episode_number', 1)
                        r_key = f"{normalize_title(r_title)}:{r_ep}"
                        
                        r_state = state.get(r_key, {})
                        if r_state.get('status') == 'complete':
                            continue
                        r_retry = r_state.get('retry_after', 0)
                        if r_retry and now_loop_ts < r_retry:
                            continue
                        if r_state.get('status') == 'partial':
                            r_chk = r_state.get('last_checked_at', 0)
                            if now_loop_ts - r_chk < 300:
                                continue

                        claimed = await claim_episode_lock(session, r_title, r_ep)
                        if claimed:
                            target_releases.append(r)
                            if len(target_releases) >= max_rel_claim:
                                break
                        else:
                            log("CLAIMED", f"Episode {r_title} Ep {r_ep} sedang dikerjakan worker lain. Melewati...", GRAY)

                    log("FEED", f"Ditemukan {len(all_new_releases)} rilisan ({len(target_releases)} baru & aktif dikerjakan worker ini) dari seluruh sumber.", GRAY)

                    ongoing_activity = 0
                    completed_did_work = False

                    global _ACTIVE_PROCESSING_TASKS
                    _ACTIVE_PROCESSING_TASKS += 1
                    try:
                        # 1. Proses rilisan yang baru tayang (siapa tercepat rilis)
                        if target_releases:
                            if concurrency <= 1:
                                for release in target_releases:
                                    r_t = release.get('anime_title', '')
                                    r_e = release.get('episode_number', 1)
                                    try:
                                        cnt = await process_new_ongoing_release(client, session, release, state)
                                        ongoing_activity += (cnt or 0)
                                    except Exception as pe:
                                        log("ERR_RELEASE", f"Gagal proses rilis: {pe}", RED)
                                    finally:
                                        await release_episode_lock(session, r_t, r_e)
                            else:
                                rel_sem = asyncio.Semaphore(concurrency)
                                async def rel_worker(r):
                                    nonlocal ongoing_activity
                                    r_t = r.get('anime_title', '')
                                    r_e = r.get('episode_number', 1)
                                    async with rel_sem:
                                        try:
                                            cnt = await process_new_ongoing_release(client, session, r, state)
                                            ongoing_activity += (cnt or 0)
                                        except Exception as pe:
                                            log("ERR_RELEASE", f"Gagal proses rilis: {pe}", RED)
                                        finally:
                                            await release_episode_lock(session, r_t, r_e)
                                rel_tasks = [asyncio.create_task(rel_worker(r)) for r in target_releases]
                                await asyncio.gather(*rel_tasks, return_exceptions=True)

                        # 2. Backfill resolusi yang belum lengkap untuk episode yang sudah rilis
                        try:
                            bf_cnt = await backfill_missing_resolutions(client, session, state, concurrency=concurrency)
                            ongoing_activity += (bf_cnt or 0)
                        except Exception as be:
                            log("ERR_BACKFILL", f"Gagal cek resolusi susulan: {be}", RED)

                        # 3. Mode Anime Tamat (Gotong Royong & Anti-Idle):
                        # Jika di siklus saat ini tidak ada aktivitas ongoing aktif yang bisa diproses
                        # (misalnya: rilis baru belum tayang, resolusi yang belum lengkap sedang dalam masa cooldown
                        #  menunggu situs fansub merilisnya, atau sedang dikerjakan worker lain):
                        # JANGAN BIARKAN WORKER MENGANGGUR! Worker LANGSUNG mengambil dan memproses episode Anime Tamat.
                        # Begitu resolusi ongoing yang ditunggu sudah rilis di situs sumber atau cooldown selesai di siklus berikutnya,
                        # worker otomatis memprioritaskan ongoing kembali!
                        if ongoing_activity == 0:
                            if device_role == "server" and has_active_remote_workers():
                                if not was_standby:
                                    log("STANDBY", "💤 Cluster Remote Worker terdeteksi aktif. Server CasaOS 100% STANDBY SIAGA (tidak mengambil anime tamat)...", YELLOW)
                                    was_standby = True
                                update_heartbeat(status="standby", current_task="💤 Standby Siaga (Cluster Remote Worker Aktif)")
                                await asyncio.sleep(15)
                                continue

                            # 2.5. Tugas Delegasi 2K Cluster (Storage-Aware Work Stealing):
                            # Jika worker memiliki GPU & disk lapang (>= 20 GB), ambil tugas 2K pending dari worker lain!
                            try:
                                h2k_done = await check_and_process_2k_handover(client, session)
                                if h2k_done:
                                    continue
                            except Exception as h2k_e:
                                log("ERR_2K_HANDOVER", f"Kendala 2K cluster handover: {h2k_e}", YELLOW)

                            try:
                                completed_did_work = await process_completed_anime_step(client, session, concurrency=concurrency)
                            except Exception as ce:
                                log("ERR_COMPLETED", f"Kendala pada pengecekan anime tamat: {ce}", YELLOW)
                    finally:
                        _ACTIVE_PROCESSING_TASKS = max(0, _ACTIVE_PROCESSING_TASKS - 1)

                except asyncio.CancelledError:
                    break
                except Exception as loop_err:
                    log("LOOP_ERR", f"Kendala sementara pada siklus: {loop_err}", YELLOW)
                    log("RETRY", "Melanjutkan otomatis ke siklus berikutnya...", GRAY)

                # Cek pembaruan kode otomatis jika ada antrean update atau kode berubah di disk
                if _PENDING_AUTO_UPDATE_URL and not _AUTO_UPDATE_IN_PROGRESS and is_worker_idle():
                    log("AUTO_UPDATE", "🎯 Seluruh tugas aktif selesai dan worker bebas. Menjalankan pembaruan otomatis...", BOLD + GREEN)
                    threading.Thread(target=perform_self_update, args=(_PENDING_AUTO_UPDATE_URL, _PENDING_AUTO_UPDATE_HASH), daemon=False).start()
                    await asyncio.sleep(5)
                    continue

                if device_role == "server" and is_worker_idle():
                    disk_h = get_current_script_hash()
                    if disk_h and _CURRENT_SCRIPT_HASH and disk_h != _CURRENT_SCRIPT_HASH:
                        log("AUTO_RELOAD", "🔄 Kode server diperbarui di disk! Me-reload worker lokal CasaOS...", BOLD + GREEN)
                        restart_worker_process()

                # Jika idle (tidak ada unduhan rilis baru maupun proses anime tamat),
                # beri jeda sejenak (8 detik) agar tidak membanjiri scraping & server API.
                # Namun jika sedang ada aktivitas aktif, lanjutkan dengan jeda mikro 1.5 detik.
                if ongoing_activity == 0 and not completed_did_work:
                    await asyncio.sleep(8)
                else:
                    await asyncio.sleep(1.5)
    finally:
        if 'bg_render_task' in locals() and bg_render_task and not bg_render_task.done():
            bg_render_task.cancel()
        try:
            if client and client.is_connected:
                await client.stop()
        except Exception:
            pass

async def test_scan_sources():
    async with aiohttp.ClientSession() as session:
        log("SCAN", "Menguji pemindaian feed rilisan dari 3 sumber...", CYAN)
        as_eps = await scan_animesail_latest(session)
        km_eps = await scan_kuramanime_latest(session)
        na_eps = await scan_nontonanimeid_latest(session)

        print(f"\n{BOLD}{CYAN}=== HASIL PEMINDAIAN RILISAN ONGOING ==={RESET}")
        print(f"{GREEN}✓ AnimeSail    :{RESET} Ditemukan {len(as_eps)} episode terbaru")
        for ep in as_eps[:3]:
            print(f"   • {ep['anime_title']} - Ep {ep['episode_number']} ({ep.get('released_at')})")

        print(f"\n{GREEN}✓ Kuramanime   :{RESET} Ditemukan {len(km_eps)} episode terbaru")
        for ep in km_eps[:3]:
            print(f"   • {ep['anime_title']} - Ep {ep['episode_number']}")

        print(f"\n{GREEN}✓ NontonAnimeID:{RESET} Ditemukan {len(na_eps)} episode terbaru")
        for ep in na_eps[:3]:
            print(f"   • {ep['anime_title']} - Ep {ep['episode_number']}")
        print(f"{BOLD}{CYAN}========================================{RESET}\n")

async def test_telegram_connection():
    if not check_credentials():
        return
    log("TEST", f"Menguji koneksi Telegram MTProto ke Channel {CHANNEL_ID}...", CYAN)
    tg_proxy = get_telegram_proxy_config()
    client_kwargs = {
        'name': "test_session",
        'api_id': int(API_ID),
        'api_hash': API_HASH,
        'bot_token': BOT_TOKEN,
        'in_memory': True
    }
    if tg_proxy:
        client_kwargs['proxy'] = tg_proxy
    client = Client(**client_kwargs)
    try:
        await asyncio.wait_for(client.start(), timeout=25.0)
        me = await client.get_me()
        chat = await client.get_chat(int(CHANNEL_ID))
        log("SUCCESS", f"Bot @{me.username} berhasil terhubung ke Channel: '{chat.title}'!", GREEN)
        await client.stop()
    except Exception as e:
        log("ERROR", f"Gagal menguji koneksi Telegram: {e}", RED)

def show_ongoing_state():
    state = load_ongoing_state()
    if not state:
        print("\nBelum ada riwayat status (.ongoing_quality_state.json belum dibuat atau kosong).")
        print("Jalankan pemantau otomatis [Menu 1] untuk mulai memantau rilisan anime ongoing!\n")
        return
    print(f"\n{BOLD}{CYAN}=== STATUS RESOLUSI ANIME ONGOING ({len(state)} Anime/Episode Dipantau) ==={RESET}")
    for k, v in list(state.items())[-20:]:
        title = v.get('anime_title', k)
        ep = v.get('episode_number', '?')
        status = v.get('status', 'unknown')
        done = ', '.join(v.get('completed_qualities', [])) or 'Belum ada'
        missing = ', '.join(v.get('missing_qualities', [])) or 'Lengkap'
        color = GREEN if status == 'complete' else YELLOW
        print(f"• {BOLD}{title}{RESET} - Ep {ep} | Status: {color}{status.upper()}{RESET}")
        print(f"  {GRAY}Selesai : [{done}] | Menunggu: [{missing}]{RESET}")
    print(f"{BOLD}{CYAN}======================================================================{RESET}\n")

def main():
    is_colab = (
        os.path.exists('/content') or 
        'google.colab' in sys.modules or 
        os.path.exists('/work') or 
        os.getenv('WORKER_ROLE') in CLOUD_ROLES or 
        get_device_role() in CLOUD_ROLES
    )
    env_concurrency = os.getenv('CONCURRENCY')
    if env_concurrency:
        default_concurrency = int(env_concurrency)
    elif is_colab:
        default_concurrency = 5  # Cloud VM berkecepatan tinggi (1 Gbps), default unduh 5 video paralel!
    elif sys.platform == 'win32':
        default_concurrency = 2  # Laptop Windows
    else:
        default_concurrency = 1  # Server CasaOS

    parser = argparse.ArgumentParser(description="Nipnime Ongoing Multi-Source First-Release & Backfill Worker")
    parser.add_argument('--daemon', action='store_true', help="Jalankan dalam mode pemantau rilisan otomatis")
    parser.add_argument('--interval', type=int, default=0, help="Interval jeda pemindaian dalam detik (default: 0 / Non-stop)")
    parser.add_argument('--concurrency', type=int, default=default_concurrency, help=f"Jumlah episode yang diproses / diunduh serentak (default: {default_concurrency})")
    parser.add_argument('--render-concurrency', type=int, default=int(os.getenv('RENDER_CONCURRENCY', '1')), help="Jumlah video yang dirender serentak di GPU (default: 1, atau 2 untuk dual-NVENC)")
    parser.add_argument('--shard', type=str, default=os.getenv('WORKER_SHARD', 'all'), help="Partisi sharding episode (odd/ganjil: Ep 1,3,5... | even/genap: Ep 2,4,6...)")
    parser.add_argument('--limit', type=int, default=int(os.getenv('TEST_LIMIT', '0')), help="Batasi total video yang diproses sebelum berhenti otomatis (misal: --limit 5)")
    parser.add_argument('--render-first', action='store_true', help="Tunggu render selesai sebelum upload ke web (mode lama)")
    parser.add_argument('--fast-release', action='store_true', default=True, help="Upload video raw dulu agar web langsung rilis, lalu render & ganti susulan (default: aktif)")
    parser.add_argument('--role', type=str, default=None, help="Peran worker (colab, laptop, warnet, azure, aws, codespace, server)")
    parser.add_argument('--single-test', action='store_true', help="Uji coba 1 video dengan watermark NIPNIME.COM lalu berhenti")
    parser.add_argument('--no-watermark', action='store_true', help="Nonaktifkan penyematan watermark")
    parser.add_argument('--test-scan', action='store_true', help="Uji pemindaian feed rilisan 3 sumber")
    parser.add_argument('--test-conn', action='store_true', help="Uji koneksi bot dan channel Telegram")
    parser.add_argument('--view-state', action='store_true', help="Tampilkan status episode dan resolusi ongoing")
    args = parser.parse_args()

    if args.render_concurrency:
        os.environ['RENDER_CONCURRENCY'] = str(args.render_concurrency)

    global WATERMARK_SINGLE_TEST, ENABLE_WATERMARK, MAX_TEST_COUNT
    if args.limit > 0:
        MAX_TEST_COUNT = args.limit
        ENABLE_WATERMARK = True
        WATERMARK_SINGLE_TEST = True
        if not env_concurrency:
            args.concurrency = min(args.limit, 5)
        log("CONFIG", f"🎯 MODE UJI COBA BATCH AKTIF: Worker akan memproses {MAX_TEST_COUNT} VIDEO secara serentak/paralel (Concurrency: {args.concurrency}) dengan watermark NIPNIME.COM lalu otomatis berhenti.", BOLD + YELLOW)
    elif args.single_test or os.getenv('WATERMARK_SINGLE_TEST', '0').strip() in ('1', 'true', 'yes'):
        MAX_TEST_COUNT = 1
        WATERMARK_SINGLE_TEST = True
        ENABLE_WATERMARK = True
        args.concurrency = 1
        log("CONFIG", "🎯 MODE UJI COBA AKTIF: Worker akan memproses TEPAT 1 VIDEO dengan watermark NIPNIME.COM lalu otomatis berhenti.", BOLD + YELLOW)

    if args.no_watermark:
        ENABLE_WATERMARK = False

    if args.role:
        os.environ['WORKER_ROLE'] = args.role

    global WORKER_SHARD, _manual_shard_locked
    WORKER_SHARD = 'all'
    _manual_shard_locked = False
    log("CONFIG", "⚡ MODE GOTONG ROYONG PENUH AKTIF: Seluruh episode dipantau bersama dengan koordinasi Distributed Claim Lock anti-tabrakan.", BOLD + GREEN)
    if FAST_RELEASE_FIRST:
        log("CONFIG", "⚡ SISTEM RILIS DUA TAHAP AKTIF: Video raw di-upload dulu agar web langsung tayang, lalu render resmi & ganti susulan!", BOLD + CYAN)

    # Deteksi Google Colab / Cloud environment
    is_colab_runtime = (
        (args.role and args.role.lower() == 'colab') or
        os.getenv('WORKER_ROLE') == 'colab' or
        get_device_role() == 'colab' or
        os.path.exists('/content') or
        'google.colab' in sys.modules
    )

    ensure_gpu_and_ffmpeg_ready()

    # Di Google Colab, bandwidth 1 Gbps. Jika concurrency <= 2 (default laptop/script bat),
    # otomatis naikkan ke 5 task paralel (Turbo 5x) serentak jika BUKAN dalam mode single-test!
    if is_colab_runtime and not env_concurrency and args.concurrency <= 2 and (not WATERMARK_SINGLE_TEST or MAX_TEST_COUNT > 1):
        args.concurrency = 5

    if args.test_scan:
        asyncio.run(test_scan_sources())
    elif args.test_conn:
        asyncio.run(test_telegram_connection())
    elif args.view_state:
        show_ongoing_state()
    else:
        asyncio.run(run_ongoing_daemon(interval_sec=args.interval, concurrency=args.concurrency))

if __name__ == '__main__':
    main()

