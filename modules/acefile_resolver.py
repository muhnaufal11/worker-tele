import sys
import os
import json
import ssl
import time
import re
import base64
import urllib.request
import urllib.parse
from urllib.parse import urlencode
from pathlib import Path

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

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
                    print("[ACEFILE] Link utama limit kuota / butuh login. Mencari mirror alternatif...", file=sys.stderr)
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
                        print("[ACEFILE] Stream link utama tidak valid (HTML / 404). Mencari mirror...", file=sys.stderr)
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
                                    print(f"[ACEFILE_MIRROR] ✓ Berhasil mengurai stream dari mirror Google Drive ({gdrive_id})!", file=sys.stderr)
                                    return candidate, gdrive_cookie
                        except Exception:
                            pass
            except Exception:
                pass

    except Exception as e:
        print(f"[ACEFILE_ERR] Error resolve_acefile: {e}", file=sys.stderr)

    return None, None

if __name__ == '__main__':
    if len(sys.argv) > 1:
        u, c = resolve_acefile_to_direct(sys.argv[1])
        print(json.dumps({'direct_url': u, 'cookie': c}))
    else:
        print(json.dumps({'error': 'No URL provided'}))
