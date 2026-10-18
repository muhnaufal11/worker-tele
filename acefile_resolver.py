import sys
import os
import json
import ssl
import time
import re
import urllib.request
import urllib.parse
from urllib.parse import urlencode
from pathlib import Path

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def resolve_acefile_to_direct(acefile_url: str) -> tuple[str, str]:
    """Mengurai tautan Acefile (https://acefile.co/f/... atau /d/...) menjadi direct Google Drive CDN stream super cepat (10-30+ MB/s)."""
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

        if not cookie_file:
            print("[ACEFILE_ERR] File .acefile_cookies.json tidak ditemukan!", file=sys.stderr)
            return None, None

        with open(cookie_file, 'r', encoding='utf-8') as f:
            cookies = json.load(f)

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
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

        target_d_url = acefile_url
        if '/f/' in acefile_url:
            req_f = urllib.request.Request(acefile_url, headers=headers)
            with opener.open(req_f) as r_f:
                f_html = r_f.read().decode('utf-8', errors='ignore')
            tokens = re.findall(r'https://acefile\.co/d/([a-zA-Z0-9_-]+)', f_html)
            if not tokens:
                print(f"[ACEFILE_ERR] Tidak ditemukan link unduh /d/ di halaman Acefile (status HTML {len(f_html)}b).", file=sys.stderr)
                return None, None
            target_d_url = f"https://acefile.co/d/{tokens[0]}"

        for attempt in range(8):
            try:
                # Refresh token dari halaman /f/ setiap kali percobaan jika percobaan sebelumnya belum berhasil
                if attempt > 0 and '/f/' in acefile_url:
                    try:
                        req_f = urllib.request.Request(acefile_url, headers=headers)
                        with opener.open(req_f, timeout=10) as r_f:
                            f_html = r_f.read().decode('utf-8', errors='ignore')
                        fresh_tokens = re.findall(r'https://acefile\.co/d/([a-zA-Z0-9_-]+)', f_html)
                        if fresh_tokens:
                            target_d_url = f"https://acefile.co/d/{fresh_tokens[0]}"
                    except Exception:
                        pass

                req_d = urllib.request.Request(target_d_url, headers=headers)
                with opener.open(req_d, timeout=15) as r_d:
                    final_url = r_d.geturl()
                    body = r_d.read().decode('utf-8', errors='ignore')

                if "drive.usercontent.google.com" in final_url or "drive.google.com" in final_url:
                    google_cookies = [f"{c.name}={c.value}" for c in cj if 'google.com' in c.domain]
                    gdrive_cookie = "; ".join(google_cookies) if google_cookies else "; ".join([f"{c.name}={c.value}" for c in cj])
                    form_m = re.search(r'<form[^>]*id="download-form"[^>]*>([\s\S]*?)</form>', body)
                    if form_m:
                        inputs = dict(re.findall(r'<input\s+type="hidden"\s+name="([^"]+)"\s+value="([^"]*)"', form_m.group(1)))
                        if inputs:
                            return f"https://drive.usercontent.google.com/download?{urlencode(inputs)}", gdrive_cookie
                    return final_url, gdrive_cookie
                elif "notFound" in body or "File not found" in body:
                    print(f"[ACEFILE_NOTICE] File di Google Drive tidak ditemukan (notFound).", file=sys.stderr)
                    break
                else:
                    reason = "kuota limit (rateLimitExceeded)" if ("rateLimitExceeded" in body or "quota" in body.lower()) else "menunggu antrian Google Drive"
                    print(f"[ACEFILE_NOTICE] Acefile {reason} ({attempt+1}/8). Mencoba ulang...", file=sys.stderr)
                    time.sleep(2.0)
                    continue
            except Exception as e:
                print(f"[ACEFILE_ERR] Percobaan resolve {attempt+1}/8 gagal: {e}", file=sys.stderr)
                time.sleep(1.5)
    except Exception as e:
        print(f"[ACEFILE_ERR] Error resolve_acefile: {type(e).__name__}: {e}", file=sys.stderr)
    return None, None

if __name__ == '__main__':
    if len(sys.argv) > 1:
        u, c = resolve_acefile_to_direct(sys.argv[1])
        print(json.dumps({'direct_url': u, 'cookie': c}))
    else:
        print(json.dumps({'error': 'No URL provided'}))
