#!/usr/bin/env python3
"""
Nipnime Kusonime Batch Anime Scraper & Direct Download Resolver
=============================================================================
Fitur:
1. Pencarian Cerdas & Normalisasi Judul (Mendukung Season Romawi <-> Arab).
2. Parsing Tabel Unduhan Batch (.smokedd / .smokeddlrh) termasuk Multi-Part / Split-Cour.
3. Pengelompokan Resolusi Lengkap: 1080p, 720p, 480p, 360p.
4. Direct Stream Resolver:
   - Pixeldrain (/u/id & /l/id album list) -> Direct API https://pixeldrain.com/api/file/{id}?download
   - Acefile (/f/id & /d/id) -> Integrasi dengan acefile_resolver.py
   - Google Drive -> Direct Export URL
5. Mematuhi Aturan Workspace:
   - Rule 1: Diuji secara nyata end-to-end.
   - Rule 5: Deteksi Season (Romawi vs Arab) berjalan paling pertama.
"""

import sys
import os
import re
import json
import time
import difflib
import urllib.request
import urllib.parse
from pathlib import Path

# Rekonfigurasi konsol Windows agar aman dari karakter Unicode / emoji / checkmark
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Impor Acefile Resolver jika tersedia di folder modules
try:
    from modules.acefile_resolver import resolve_acefile_to_direct
except ImportError:
    try:
        from acefile_resolver import resolve_acefile_to_direct
    except ImportError:
        resolve_acefile_to_direct = None

# Impor Google Drive Resolver jika tersedia di folder modules
try:
    from modules.batch_source_aggregator import resolve_gdrive_to_direct
except ImportError:
    try:
        from batch_source_aggregator import resolve_gdrive_to_direct
    except ImportError:
        resolve_gdrive_to_direct = None

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Kamus Konversi Angka Romawi <-> Angka Arab
ROMAN_TO_ARABIC = {
    'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5,
    'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10
}
ARABIC_TO_ROMAN = {v: k for k, v in ROMAN_TO_ARABIC.items()}

def extract_season_number(text: str) -> int:
    """Mendeteksi nomor season dari judul teks (Arab maupun Romawi). Default: 1."""
    text_clean = str(text).lower().replace('_', ' ')
    # 1. Season X / Musim X
    m = re.search(r'\b(?:season|musim)[_\s-]*(\d+)\b', text_clean)
    if m:
        return int(m.group(1))
    # 2. Xth / Xnd / Xrd / Xst Season
    m = re.search(r'\b(\d+)(?:st|nd|rd|th)[_\s-]*(?:season|musim)?\b', text_clean)
    if m:
        return int(m.group(1))
    # 3. s2, s3, -s2 di kata terpisah atau akhir slug
    m = re.search(r'(?:\b|[-_])s(\d+)(?:\b|[-_]|$)', text_clean)
    if m:
        return int(m.group(1))
    # 4. Pola Angka Romawi (diurutkan dari terpanjang)
    roman_pairs = [('viii', 8), ('vii', 7), ('iii', 3), ('vi', 6), ('iv', 4), ('ix', 9), ('ii', 2), ('x', 10), ('v', 5)]
    for r_str, r_val in roman_pairs:
        if re.search(rf'(?:\b|[-_]){r_str}(?:\b|[-_]|$)', text_clean):
            return r_val
    # 5. Angka mandiri 2-15 sebelum tag umum/akhir teks
    base_text = re.sub(r'\b(?:batch|subtitle|indonesia|sub\s*indo|bd|ona|ova|bluray|episode|ep|eps)[_\s-]*\d*\b', '', text_clean)
    base_text = re.sub(r'\b(?:part|cour)[_\s-]*\d+\b', '', base_text)
    m = re.search(r'(?:\b|[-_])([2-9]|1[0-5])(?:\s*\[|\s*\(|[-_\s]*$)', base_text)
    if m:
        return int(m.group(1))
    return 1

def normalize_title(title: str) -> str:
    """Membersihkan judul dari tag metadata dan normalisasi spasi."""
    t = title.lower()
    # Hapus tag umum kusonime
    t = re.sub(r'\b(batch|subtitle|indonesia|sub\s*indo|bd|ona|ova|bluray)\b', ' ', t)
    # Hapus kurung dan isi simbol
    t = re.sub(r'\[[^\]]*\]|\([^\)]*\)', ' ', t)
    t = re.sub(r'[^\w\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def search_kusonime(keyword: str, timeout: int = 15) -> list[dict]:
    """
    Mencari anime di Kusonime (https://kusonime.com/?s={keyword}).
    Mengembalikan daftar kandidat anime dengan judul, URL halaman, dan nomor season.
    """
    clean_kw = re.sub(r'[^\w\s]', ' ', keyword).strip()
    encoded = urllib.parse.quote(clean_kw)
    url = f"https://kusonime.com/?s={encoded}"
    
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': DEFAULT_UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'id,en-US;q=0.9,en;q=0.8'
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"[KUSONIME] Gagal mencari query '{keyword}': {e}", file=sys.stderr)
        return []
        
    items = re.findall(
        r'<h2[^>]*class=["\']episodeye["\'][^>]*>\s*<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        html,
        flags=re.I
    )
    if not items:
        items = re.findall(
            r'<a\s+href=["\'](https://kusonime\.com/[^"\']+)["\'][^>]*rel=["\']bookmark["\'][^>]*>(.*?)</a>',
            html,
            flags=re.I
        )
        
    results = []
    seen_urls = set()
    for link, raw_title in items:
        if link in seen_urls:
            continue
        seen_urls.add(link)
        
        clean_title = re.sub(r'<[^>]+>', '', raw_title).strip()
        season_num = extract_season_number(clean_title)
        
        results.append({
            'title': clean_title,
            'url': link,
            'season': season_num,
            'normalized': normalize_title(clean_title)
        })
        
    return results

def match_kusonime_result(target_title: str, candidates: list[dict]) -> dict | None:
    """
    Memilih kandidat Kusonime yang paling cocok berdasarkan:
    1. PRIORITAS UTAMA: Kesamaan Season (Arab vs Romawi).
    2. Kesamaan nama inti judul (Similarity Score).
    """
    if not candidates:
        return None
        
    target_season = extract_season_number(target_title)
    target_norm = normalize_title(target_title)
    
    # Saring kandidat dengan season yang sama
    same_season_candidates = [c for c in candidates if c['season'] == target_season]
    search_pool = same_season_candidates if same_season_candidates else candidates
    
    best_candidate = None
    best_score = 0.0
    
    for c in search_pool:
        # Jika season berbeda dan target meminta season > 1, berikan penalti berat
        if target_season > 1 and c['season'] != target_season:
            continue
            
        c_norm = c['normalized']
        # Hitung similarity menggunakan difflib
        score = difflib.SequenceMatcher(None, target_norm, c_norm).ratio()
        
        # Bonus jika substring persis
        if target_norm in c_norm or c_norm in target_norm:
            score += 0.25
            
        # Bonus jika season persis sama
        if c['season'] == target_season:
            score += 0.3
            
        if score > best_score:
            best_score = score
            best_candidate = c
            
    # Ambang batas minimal kemiripan 0.65
    if best_score >= 0.65:
        return best_candidate
        
    return None

def parse_kusonime_batch_page(page_url: str, html: str = None, timeout: int = 15) -> list[dict]:
    """
    Mengurai halaman anime Kusonime untuk mengekstrak seluruh paket unduhan batch.
    Mendukung Multi-Part / Split-Cour Batch (misal Ep 01-12 dan Ep 13-24).
    
    Mengembalikan daftar paket batch (list of packages), dengan struktur:
    [
      {
        'package_title': 'Download Sousou no Frieren 01-16 Batch BD Subtitle Indonesia',
        'ep_range': (1, 16),
        'resolutions': {
            '1080p': [ {'hoster': 'Pixeldrain', 'url': '...', 'priority': 1}, ... ],
            '720p': [ ... ],
            '480p': [ ... ],
            '360p': [ ... ]
        }
      },
      ...
    ]
    """
    if not html:
        req = urllib.request.Request(
            page_url,
            headers={'User-Agent': DEFAULT_UA}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"[KUSONIME] Gagal membaca halaman '{page_url}': {e}", file=sys.stderr)
            return []

    # Temukan kontainer batch (smokeddlrh / smokedd)
    raw_blocks = re.findall(
        r'<div[^>]*class=["\']smokeddlrh["\'][^>]*>([\s\S]*?)</div>\s*</div>(?:\s*</div>)?',
        html
    )
    if not raw_blocks:
        # Fallback jika class bernama 'smokedd'
        raw_blocks = re.findall(
            r'<div[^>]*class=["\']smokedd["\'][^>]*>([\s\S]*?)</div>\s*</div>',
            html
        )
        
    packages = []
    
    for block in raw_blocks:
        ttls = re.findall(r'<div[^>]*class=["\']smokettlrh["\'][^>]*>(.*?)</div>', block)
        ttl = ttls[0].strip() if ttls else "Download Batch"
        
        # Ekstrak rentang episode (misal: "01-12", "13-24", "01-24")
        ep_range = None
        range_match = re.search(r'\b(\d{1,3})\s*-\s*(\d{1,3})\b', ttl)
        if range_match:
            ep_range = (int(range_match.group(1)), int(range_match.group(2)))
            
        pkg = {
            'package_title': ttl,
            'ep_range': ep_range,
            'resolutions': {
                '1080p': [],
                '720p': [],
                '480p': [],
                '360p': []
            }
        }
        
        # Cari setiap baris resolusi: <div class="smokeurlrh"><strong>1080P</strong> ...</div>
        res_lines = re.findall(
            r'<div[^>]*class=["\']smokeurlrh["\'][^>]*>\s*<strong>(.*?)</strong>([\s\S]*?)</div>',
            block
        )
        
        for raw_res_name, links_html in res_lines:
            r_lower = raw_res_name.lower()
            std_res = None
            if '1080' in r_lower:
                std_res = '1080p'
            elif '720' in r_lower:
                std_res = '720p'
            elif '480' in r_lower:
                std_res = '480p'
            elif '360' in r_lower:
                std_res = '360p'
                
            if not std_res:
                continue
                
            # Ambil semua tag <a>
            a_tags = re.findall(r'<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', links_html)
            for href, h_name in a_tags:
                href = href.replace('&amp;', '&').strip()
                h_name_clean = re.sub(r'<[^>]+>', '', h_name).strip()
                
                # Tentukan nama hoster & prioritas unduhan
                hoster_type = "Unknown"
                priority = 99
                
                href_l = href.lower()
                h_name_l = h_name_clean.lower()
                
                if 'drive.google.com' in href_l or 'gdrive' in h_name_l or 'google drive' in h_name_l:
                    hoster_type = 'Google Drive'
                    priority = 1
                elif 'acefile.co' in href_l or 'sharer' in h_name_l or 'google sharer' in h_name_l:
                    hoster_type = 'Acefile'
                    priority = 1
                elif 'mediafire.com' in href_l or 'mediafire' in h_name_l:
                    hoster_type = 'Mediafire'
                    priority = 2
                elif 'mega.nz' in href_l or 'mega' in h_name_l:
                    hoster_type = 'Mega'
                    priority = 2
                elif 'pixeldrain.com' in href_l or 'pixeldrain' in h_name_l:
                    hoster_type = 'Pixeldrain'
                    priority = 90
                elif 'terabox' in href_l or 'terabox' in h_name_l:
                    hoster_type = 'Terabox'
                    priority = 99
                else:
                    hoster_type = h_name_clean
                    priority = 10
                    
                pkg['resolutions'][std_res].append({
                    'hoster': hoster_type,
                    'raw_url': href,
                    'priority': priority
                })
                
        # Urutkan link di tiap resolusi berdasarkan prioritas (1: Pixeldrain, 2: Acefile, dst)
        has_any_links = False
        for r_key in pkg['resolutions']:
            pkg['resolutions'][r_key].sort(key=lambda x: x['priority'])
            if pkg['resolutions'][r_key]:
                has_any_links = True
            
        # Hanya simpan paket jika memiliki minimal satu link unduhan aktif (bukan BELUM TERSEDIA)
        if has_any_links:
            packages.append(pkg)
        
    return packages

def resolve_pixeldrain_url(url: str, target_res: str = None, timeout: int = 10) -> tuple[str, str]:
    """
    Mengurai URL Pixeldrain menjadi Direct Download API URL:
    - Jika /u/{id}: langsung return https://pixeldrain.com/api/file/{id}?download
    - Jika /l/{list_id}: panggil API list untuk mencari file yang sesuai dengan target_res (1080p, 720p, dst).
    Mengembalikan: (direct_url, filename)
    """
    # 1. Single file: https://pixeldrain.com/u/{id}
    m_single = re.search(r'pixeldrain\.com/u/([a-zA-Z0-9_-]+)', url)
    if m_single:
        file_id = m_single.group(1)
        direct_url = f"https://pixeldrain.com/api/file/{file_id}?download"
        return direct_url, f"{file_id}.rar"
        
    # 2. Album / List: https://pixeldrain.com/l/{list_id}
    m_list = re.search(r'pixeldrain\.com/l/([a-zA-Z0-9_-]+)', url)
    if m_list:
        list_id = m_list.group(1)
        api_url = f"https://pixeldrain.com/api/list/{list_id}"
        req = urllib.request.Request(api_url, headers={'User-Agent': DEFAULT_UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                files = data.get('files', [])
                
                # Cari file yang sesuai resolusi
                chosen_f = None
                if target_res:
                    res_num = re.sub(r'[^\d]', '', target_res) # '1080'
                    for f in files:
                        f_name = f.get('name', '').lower()
                        if res_num in f_name:
                            chosen_f = f
                            break
                            
                # Fallback jika target_res tidak spesifik atau tidak ketemu
                if not chosen_f and files:
                    chosen_f = files[0]
                    
                if chosen_f:
                    f_id = chosen_f.get('id')
                    f_name = chosen_f.get('name', f"{f_id}.rar")
                    return f"https://pixeldrain.com/api/file/{f_id}?download", f_name
        except Exception as e:
            print(f"[PIXELDRAIN] Gagal mengurai list '{list_id}': {e}", file=sys.stderr)
            
    return None, None

def resolve_kusonime_download_link(hoster_info: dict, target_res: str = None) -> tuple[str, dict]:
    """
    Menyelesaikan URL hoster Kusonime menjadi direct streaming link siap unduh.
    Mengembalikan: (direct_url, extra_headers)
    """
    hoster = hoster_info.get('hoster', '')
    raw_url = hoster_info.get('raw_url', '')
    headers = {'User-Agent': DEFAULT_UA}
    
    if (hoster == 'Google Drive' or 'drive.google.com' in raw_url) and resolve_gdrive_to_direct:
        direct, cookie = resolve_gdrive_to_direct(raw_url)
        if direct:
            if cookie:
                headers['Cookie'] = cookie
            return direct, headers

    elif (hoster == 'Acefile' or 'acefile.co' in raw_url) and resolve_acefile_to_direct:
        direct, cookie = resolve_acefile_to_direct(raw_url)
        if direct:
            if cookie:
                headers['Cookie'] = cookie
            return direct, headers

    elif hoster == 'Pixeldrain' or 'pixeldrain.com' in raw_url:
        direct, fname = resolve_pixeldrain_url(raw_url, target_res=target_res)
        if direct:
            return direct, headers

    return None, headers

# ---------------------------------------------------------------------------
# CLI Uji Coba Mandiri (Self-Test Execution)
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    print("=== PENGUJIAN MODUL KUSONIME SCRAPER & DIRECT RESOLVER ===")
    test_queries = [
        "Lycoris Recoil",
        "Tensei shitara Ken deshita",
        "Tensei shitara Ken deshita II",
        "Sousou no Frieren"
    ]
    
    for query in test_queries:
        print(f"\n[TEST SEARCH] Query: '{query}'")
        res = search_kusonime(query)
        print(f"-> Ditemukan {len(res)} hasil.")
        
        match = match_kusonime_result(query, res)
        if match:
            print(f"✓ Cocok ({match['season']}): {match['title']} -> {match['url']}")
            
            # Uji parse paket batch
            pkgs = parse_kusonime_batch_page(match['url'])
            print(f"-> Terdeteksi {len(pkgs)} paket batch:")
            for p_idx, p in enumerate(pkgs, 1):
                print(f"   [Paket {p_idx}] {p['package_title']} (Rentang Ep: {p['ep_range']})")
                for r_name in ['1080p', '720p', '480p', '360p']:
                    h_list = p['resolutions'].get(r_name, [])
                    if h_list:
                        top_h = h_list[0]
                        print(f"      • {r_name.upper()}: {top_h['hoster']} ({top_h['raw_url'][:45]}...)")
                        # Uji resolving untuk 1080p
                        if r_name == '1080p' and p_idx == 1:
                            d_url, _ = resolve_kusonime_download_link(top_h, target_res=r_name)
                            print(f"        -> DIRECT URL: {d_url[:75]}..." if d_url else "        -> Gagal resolve")
        else:
            print(f"✗ Tidak ada kecocokan untuk '{query}'")
