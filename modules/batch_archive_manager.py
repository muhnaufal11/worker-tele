#!/usr/bin/env python3
"""
Nipnime Batch Archive Manager & Safety Guard
=============================================================================
Fitur:
1. Cross-Platform 7z / Archive Runner (Linux CasaOS / VPS / Colab / Windows).
   - Mendukung format RAR, RAR5, ZIP, 7Z, TAR.
   - Deteksi pintar full 7z.exe / 7zz vs 7za.exe (agar file RAR tidak gagal dibaca).
2. Disk Guard Safety (shutil.disk_usage >= 2.5x archive size, min free 3GB).
3. Multi-Password Auto-Trial & Password Caching:
   - Menguji kandidat password otomatis (misal: kusonime.com, otakudesu.com, kuramanime, tanpa password).
   - Menyimpan password yang terbukti berhasil agar ekstraksi episode berjalan instan tanpa tebak ulang.
4. Pre-Sanitizer Nama File & Episode Regex Tingkat Lanjut:
   - Mendukung penomoran episode dengan token v2, v3, suffix (End), tanda kurung, garis bawah, dll.
   - Filter blacklist OVA/SP/NCOP/NCED/Preview.
5. Progressive Single-File Extraction & Comprehensive Tracking:
   - Pelacakan detail [ARCHIVE_CHECK], [ARCHIVE_LIST], [ARCHIVE_EXTRACT], [ARCHIVE_SUCCESS], [ARCHIVE_ERR].
   - Menangkap stderr/stdout 7z secara transparan saat terjadi kegagalan untuk diagnosis instan.
6. Stream Compatibility Guard (MKV -> Fast MP4 remux untuk player web Nipnime).
"""

import sys
import os
import re
import time
import shutil
import subprocess
from pathlib import Path

# Pastikan konsol Windows UTF-8 aman
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Blacklist token untuk menyaring video ekstra non-episode
BLACKLIST_TOKENS = {
    'ova', 'oad', 'sp', 'special', 'ncop', 'nced',
    'creditless', 'preview', 'pv', 'ost', 'soundtrack', 'menu'
}

# Ekstensi file video yang valid
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.ts', '.webm'}

# Cache password arsip yang terbukti berhasil: { abs_path_str: working_password }
_ARCHIVE_PASSWORD_CACHE: dict[str, str] = {}

# Custom logger callback jika diintegrasikan dengan worker
_ARCHIVE_LOGGER = None

def set_archive_logger(fn):
    """Menyetel fungsi logger kustom dari anime_telegram_worker (misal: log(tag, msg, color))."""
    global _ARCHIVE_LOGGER
    _ARCHIVE_LOGGER = fn

def _emit_log(tag: str, msg: str, color: str = ""):
    """Mengirim log pelacakan ke logger kustom atau stdout."""
    if _ARCHIVE_LOGGER:
        try:
            _ARCHIVE_LOGGER(tag, msg, color)
            return
        except Exception:
            pass
    print(f"[{tag}] {msg}", flush=True)

def format_bytes(size_bytes: int) -> str:
    """Format ukuran byte menjadi string yang mudah dibaca (KB, MB, GB)."""
    try:
        size = float(size_bytes)
        if size >= 1024**3:
            return f"{size / (1024**3):.2f} GB"
        elif size >= 1024**2:
            return f"{size / (1024**2):.1f} MB"
        elif size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{int(size)} B"
    except Exception:
        return "0 B"

def get_7z_binary(for_rar: bool = False) -> str | None:
    """
    Mencari lokasi binary 7z / 7zz / unrar di sistem atau folder bin project.
    Cross-platform: Windows menggunakan bin/7z.exe, Linux/macOS menggunakan bin/7zz atau sistem.
    Jika for_rar=True, binary 7za dan 7zr TIDAK DIPILIH karena tidak mendukung format RAR.
    """
    current_dir = Path(__file__).resolve().parent.parent # Z:\tools\terop-worker
    is_win = sys.platform.startswith('win')
    
    if is_win:
        # 1. Kandidat Windows (Mendukung RAR, RAR5, ZIP, 7Z, TAR, dll.)
        win_candidates = [
            current_dir / "bin" / "7z.exe",
            Path("C:/Program Files/7-Zip/7z.exe"),
            Path("C:/Program Files (x86)/7-Zip/7z.exe")
        ]
        for c in win_candidates:
            if c.exists():
                return str(c)

        for name in ['7z', '7zz', 'unrar']:
            found = shutil.which(name)
            if found:
                return found

        if not for_rar:
            for c in [current_dir / "bin" / "7za.exe", current_dir / "bin" / "7zr.exe"]:
                if c.exists():
                    return str(c)
            for name in ['7za', '7zr']:
                found = shutil.which(name)
                if found:
                    return found
    else:
        # 2. Kandidat Linux / Unix / macOS: DILARANG KERAS mengeksekusi file .exe!
        # Prioritaskan binary standalone bin/7zz jika tersedia di bundle worker
        standalone_7zz = current_dir / "bin" / "7zz"
        if standalone_7zz.exists():
            try:
                os.chmod(str(standalone_7zz), 0o755)
            except Exception:
                pass
            if os.access(str(standalone_7zz), os.X_OK):
                return str(standalone_7zz)

        # Cek PATH sistem untuk full 7zz / 7z / unrar
        for name in ['7zz', '7z', 'unrar', 'unar']:
            found = shutil.which(name)
            if found and os.access(found, os.X_OK):
                return found

        linux_candidates = [
            Path("/usr/local/bin/7zz"),
            Path("/usr/bin/7zz"),
            Path("/usr/bin/7z"),
            Path("/usr/local/bin/7z"),
            Path("/usr/bin/unrar"),
            Path("/usr/bin/unar")
        ]
        for c in linux_candidates:
            if c.exists() and os.access(str(c), os.X_OK):
                return str(c)

        if not for_rar:
            for name in ['7za', '7zr', 'p7zip']:
                found = shutil.which(name)
                if found and os.access(found, os.X_OK):
                    return found
            for c in [Path("/usr/bin/7za"), Path("/usr/bin/p7zip")]:
                if c.exists() and os.access(str(c), os.X_OK):
                    return str(c)

        # 3. Auto-Provisioning Standalone 7zz Linux (Full RAR/RAR5) dari server Nipnime jika belum ada
        try:
            bin_dir = current_dir / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            target_7zz = bin_dir / "7zz"
            if not target_7zz.exists() or target_7zz.stat().st_size < 100000:
                _emit_log("ARCHIVE_AUTO_7Z", "📥 Mengunduh binary standalone 7zz untuk Linux x86_64 dari server Nipnime...", "cyan")
                import urllib.request
                dl_urls = [
                    "https://nipnime.com/worker/7zz",
                    "https://nipnime.com/worker/bin/7zz"
                ]
                for u in dl_urls:
                    try:
                        req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                        with urllib.request.urlopen(req, timeout=15) as resp:
                            if resp.status == 200:
                                with open(target_7zz, 'wb') as f_out:
                                    f_out.write(resp.read())
                                os.chmod(str(target_7zz), 0o755)
                                if os.access(str(target_7zz), os.X_OK):
                                    _emit_log("ARCHIVE_AUTO_7Z", "✓ Binary 7zz Linux berhasil diunduh dan dipasang!", "green")
                                    return str(target_7zz)
                    except Exception:
                        continue
        except Exception:
            pass

    return None

def get_ffmpeg_binary() -> str | None:
    """Mencari executable ffmpeg di bin project atau PATH sistem."""
    current_dir = Path(__file__).resolve().parent.parent
    if sys.platform.startswith('win'):
        c = current_dir / "bin" / "ffmpeg.exe"
        if c.exists():
            return str(c)
    found = shutil.which("ffmpeg")
    if found:
        return found
    for p in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
        if Path(p).exists() and os.access(p, os.X_OK):
            return p
    return None

def disk_space_guard(required_archive_bytes: int, target_dir: Path = None, min_free_gb: float = 3.0) -> tuple[bool, str]:
    """
    Memeriksa ketersediaan ruang disk:
    1. Sisa disk bebas minimal harus >= 2.5x ukuran arsip batch.
    2. Sisa disk bebas minimal harus >= min_free_gb (default 3 GB).
    """
    if target_dir is None:
        target_dir = Path.cwd()
    try:
        usage = shutil.disk_usage(str(target_dir))
        free_bytes = usage.free
        required_guard_bytes = max(int(required_archive_bytes * 2.5), int(min_free_gb * 1024 * 1024 * 1024))
        
        free_gb = free_bytes / (1024**3)
        req_gb = required_guard_bytes / (1024**3)
        
        if free_bytes < required_guard_bytes:
            return False, f"Ruang disk tidak cukup! Bebas: {free_gb:.2f} GB, Dibutuhkan aman: {req_gb:.2f} GB."
        return True, f"Ruang disk aman (Bebas: {free_gb:.2f} GB, Dibutuhkan: {req_gb:.2f} GB)."
    except Exception as e:
        return True, f"Pemeriksaan disk dilewati ({e})"

def sanitize_and_extract_episode(filename: str) -> tuple[int | None, str]:
    """
    Membersihkan nama file dari metadata kurung siku / resolusi / season / suffix fansub,
    dan mengekstrak nomor episode secara akurat.
    
    Contoh:
    '[Kusonime] Sousou no Frieren - 04 [1080p].mkv' -> (4, 'Sousou no Frieren - 04.mkv')
    'Kimetsu no Yaiba - 01v2.mkv' -> (1, 'Kimetsu no Yaiba - 01.mkv')
    'Kimetsu no Yaiba - 26 [END] [720p].mkv' -> (26, 'Kimetsu no Yaiba - 26.mkv')
    'Sousou no Frieren - SP01.mkv' -> (None, 'Blacklisted token: SP')
    """
    path_obj = Path(filename)
    stem = path_obj.stem
    ext = path_obj.suffix.lower()
    
    if ext not in VIDEO_EXTENSIONS:
        return None, "Bukan file video"
        
    lower_stem = stem.lower()
    
    # 1. Cek Blacklist Tokens
    for token in BLACKLIST_TOKENS:
        if re.search(rf'(?:\b|_|-){token}(?:\b|_|-|\d)', lower_stem):
            return None, f"Blacklisted token: {token}"
            
    # 2. Hapus konten dalam kurung siku [...] dan kurung biasa (...)
    clean_stem = re.sub(r'\[[^\]]*\]', ' ', stem)
    clean_stem = re.sub(r'\([^\)]*\)', ' ', clean_stem)
    
    # 3. Hapus indikator season agar angka season tidak tertukar dengan nomor episode
    clean_stem = re.sub(r'(?i)\bseason\s*\d+\b', ' ', clean_stem)
    clean_stem = re.sub(r'(?i)\bs\d{1,2}\b', ' ', clean_stem)
    
    # 4. Hapus resolusi dan tag rilis video (1080p, 720p, 480p, 360p, 2k, 4k, bd, bluray, web-dl)
    clean_stem = re.sub(r'(?i)\b(?:1080|720|480|360|2160)p?\b', ' ', clean_stem)
    clean_stem = re.sub(r'(?i)\b(?:2k|4k|bd|bluray|web-dl|hdrip|dvdrip|x264|x265|hevc|aac)\b', ' ', clean_stem)
    
    # 5. Tangani fansub versioning (misal: 01v2, 01_v2, 01v3)
    clean_stem = re.sub(r'(?<=\d)[vV]\d+\b', '', clean_stem)
    
    # 6. Ganti separator underscore dengan spasi untuk memudahkan tokenisasi episode
    clean_stem = clean_stem.replace('_', ' ')
    
    # 7. Cari nomor episode dengan regex bertingkat
    patterns = [
        # Format eksplisit: "Episode 01", "Ep 01", "E01", "Ep. 01"
        r'(?i)(?:\b|ep|episode|e)[\s\.-]*(\d{1,4})(?:\b|\.|\s|$)',
        # Format strip: "- 01", "- 01 -"
        r'(?:-\s*)(\d{1,4})(?:\s*-|\s*\.|\s*$)',
        # Angka murni di dalam teks
        r'\b(\d{1,4})\b'
    ]
    
    for pat in patterns:
        for m in re.finditer(pat, clean_stem):
            ep_num = int(m.group(1))
            # Filter angka tahun atau angka codec video yang mungkin lolos
            if ep_num in (264, 265, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026):
                continue
            if 1 <= ep_num <= 2000:
                clean_name = re.sub(r'\s+', ' ', clean_stem).strip()
                return ep_num, f"{clean_name}{ext}"
                
    return None, "Nomor episode tidak terdeteksi"

def _resolve_candidate_passwords(archive_path: Path, password: str = None, candidate_passwords: list[str] = None) -> list[str]:
    """Menyusun daftar kandidat password berdasarkan nama file arsip dan preferensi sumber."""
    resolved = []
    
    # 1. Cek apakah ada password yang sudah terbukti berhasil di cache
    abs_key = str(archive_path.resolve())
    if abs_key in _ARCHIVE_PASSWORD_CACHE:
        resolved.append(_ARCHIVE_PASSWORD_CACHE[abs_key])
        
    # 2. Tambahkan password spesifik dari pemanggil jika ada
    if password is not None and password not in resolved:
        resolved.append(password)
        
    # 3. Tambahkan list calon password dari pemanggil
    if candidate_passwords:
        for cp in candidate_passwords:
            if cp not in resolved:
                resolved.append(cp)
                
    # 4. Tambahkan tebakan cerdas berdasarkan nama file jika belum ada
    fn_lower = archive_path.name.lower()
    if 'kuso' in fn_lower:
        default_order = ["kusonime.com", "", "www.kusonime.com", "otakudesu.com"]
    elif 'otaku' in fn_lower or 'desu' in fn_lower:
        default_order = ["", "otakudesu.com", "www.otakudesu.com", "kusonime.com"]
    elif 'kura' in fn_lower:
        default_order = ["", "kuramanime", "kuramanime.pro", "kusonime.com"]
    else:
        default_order = ["", "kusonime.com", "otakudesu.com", "www.kusonime.com"]
        
    for p in default_order:
        if p not in resolved:
            resolved.append(p)
            
    return resolved

def list_archive_contents(
    archive_path: Path | str,
    password: str = None,
    candidate_passwords: list[str] = None
) -> list[dict]:
    """
    Membaca daftar file di dalam arsip RAR / ZIP tanpa mengekstraknya total.
    Mendukung multi-password trial otomatis dan pencatatan log diagnostik detail.
    
    Mengembalikan daftar entri:
    [
      {
        'internal_path': 'Sousou no Frieren/Ep 01 [1080p].mp4',
        'filename': 'Ep 01 [1080p].mp4',
        'size': 450123456,
        'episode': 1
      },
      ...
    ]
    """
    archive_path = Path(archive_path)
    if not archive_path.exists():
        _emit_log("ARCHIVE_ERR", f"File arsip tidak ditemukan di disk: {archive_path}")
        return []

    file_size_str = format_bytes(archive_path.stat().st_size)
    is_rar = archive_path.suffix.lower() in ('.rar', '.r00')
    is_zip = archive_path.suffix.lower() == '.zip'
    
    _emit_log("ARCHIVE_CHECK", f"📋 Memeriksa isi arsip '{archive_path.name}' ({file_size_str})...")

    passwords_to_try = _resolve_candidate_passwords(archive_path, password, candidate_passwords)
    bin_7z = get_7z_binary(for_rar=is_rar)

    if not bin_7z and is_rar:
        _emit_log("ARCHIVE_ERR", f"❌ Binary 7z/unrar dengan dukungan format RAR tidak ditemukan di sistem! Tidak dapat membaca '{archive_path.name}'.")
        return []

    # 1. Coba menggunakan binary 7z
    if bin_7z:
        for idx, pwd in enumerate(passwords_to_try):
            pwd_flag = f"-p{pwd}" if pwd != "" else "-p"
            cmd = [bin_7z, 'l', '-slt', pwd_flag, str(archive_path)]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, errors='ignore')
                out_all = res.stdout + "\n" + res.stderr
                
                # Cek jika ada indikasi password salah
                is_wrong_pwd = any(err_kw in out_all.lower() for err_kw in [
                    'wrong password', 'cannot open encrypted archive', 'data error in encrypted'
                ])
                if is_wrong_pwd:
                    pwd_display = f"'{pwd}'" if pwd else "(tanpa password)"
                    _emit_log("ARCHIVE_PWD_FAIL", f"Percobaan password {pwd_display} gagal untuk '{archive_path.name}'. Mencoba kandidat lain...")
                    continue

                if res.returncode == 0:
                    entries = []
                    total_files = 0
                    cur_entry = {}
                    
                    for line in res.stdout.splitlines():
                        line = line.strip()
                        if line.startswith("Path = "):
                            cur_entry['Path'] = line[7:].strip()
                        elif line.startswith("Size = "):
                            try: cur_entry['Size'] = int(line[7:].strip())
                            except Exception: cur_entry['Size'] = 0
                        elif line.startswith("Folder = "):
                            cur_entry['Folder'] = line[9:].strip()
                        elif not line and cur_entry:
                            if cur_entry.get('Folder') != '+':
                                total_files += 1
                                p = cur_entry.get('Path', '')
                                fname = Path(p).name
                                ep_num, _ = sanitize_and_extract_episode(fname)
                                if ep_num is not None:
                                    entries.append({
                                        'internal_path': p,
                                        'filename': fname,
                                        'size': cur_entry.get('Size', 0),
                                        'episode': ep_num
                                    })
                            cur_entry = {}
                            
                    if cur_entry and cur_entry.get('Folder') != '+':
                        total_files += 1
                        p = cur_entry.get('Path', '')
                        fname = Path(p).name
                        ep_num, _ = sanitize_and_extract_episode(fname)
                        if ep_num is not None:
                            entries.append({
                                'internal_path': p,
                                'filename': fname,
                                'size': cur_entry.get('Size', 0),
                                'episode': ep_num
                            })

                    if entries:
                        entries.sort(key=lambda x: x['episode'])
                        # Simpan password berhasil di cache
                        _ARCHIVE_PASSWORD_CACHE[str(archive_path.resolve())] = pwd
                        pwd_label = f"'{pwd}'" if pwd else "(tanpa password)"
                        ep_summary = f"Ep {entries[0]['episode']} s/d {entries[-1]['episode']}" if len(entries) > 1 else f"Ep {entries[0]['episode']}"
                        _emit_log("ARCHIVE_LIST", f"✓ Arsip '{archive_path.name}' berhasil dibaca via 7z {pwd_label}: {len(entries)} video episode valid ({ep_summary}, total {total_files} file dalam arsip).")
                        return entries
                    else:
                        _emit_log("ARCHIVE_WARN", f"⚠️ Arsip '{archive_path.name}' terbaca ({total_files} file), tetapi tidak ada file video yang cocok dengan format episode.")
                else:
                    # Return code non-zero dan bukan wrong password biasa
                    err_lines = [l.strip() for l in out_all.splitlines() if any(kw in l.lower() for kw in ['error', 'cannot', 'failed', 'corrupt'])]
                    err_msg = "; ".join(err_lines[:2]) if err_lines else f"exit code {res.returncode}"
                    _emit_log("ARCHIVE_ERR", f"Uji 7z pada '{archive_path.name}' gagal: {err_msg}")
            except Exception as e:
                _emit_log("ARCHIVE_ERR", f"Eksekusi binary 7z gagal: {e}")

    # 2. Fallback untuk file .zip menggunakan Python built-in zipfile
    if is_zip:
        import zipfile
        for pwd in passwords_to_try:
            try:
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    pwd_bytes = pwd.encode('utf-8') if pwd else None
                    entries = []
                    total_files = 0
                    for info in zf.infolist():
                        if not info.is_dir():
                            total_files += 1
                            fname = Path(info.filename).name
                            ep_num, _ = sanitize_and_extract_episode(fname)
                            if ep_num is not None:
                                entries.append({
                                    'internal_path': info.filename,
                                    'filename': fname,
                                    'size': info.file_size,
                                    'episode': ep_num
                                })
                    if entries:
                        entries.sort(key=lambda x: x['episode'])
                        _ARCHIVE_PASSWORD_CACHE[str(archive_path.resolve())] = pwd
                        pwd_label = f"'{pwd}'" if pwd else "(tanpa password)"
                        _emit_log("ARCHIVE_LIST", f"✓ Arsip ZIP '{archive_path.name}' terbaca via zipfile {pwd_label}: {len(entries)} episode video.")
                        return entries
            except Exception as ze:
                pass

    _emit_log("ARCHIVE_ERR", f"❌ Seluruh metode listing untuk '{archive_path.name}' gagal. Arsip mungkin corrupt atau password tidak cocok dari daftar: {passwords_to_try}.")
    return []

def extract_single_episode(
    archive_path: Path | str,
    internal_path: str,
    output_dir: Path | str,
    password: str = None,
    candidate_passwords: list[str] = None,
    progress_callback: callable = None,
    expected_size: int = 0
) -> Path | None:
    """
    Mengekstrak TEPAT 1 FILE episode ke direktori output dengan mode flat ('e')
    sehingga tidak membuat hierarki folder bertingkat.
    Dilengkapi pelacakan waktu, kecepatan transfer, live progress callback, dan diagnosis error detail.
    """
    archive_path = Path(archive_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    target_filename = Path(internal_path).name
    expected_output = output_dir / target_filename
    is_rar = archive_path.suffix.lower() in ('.rar', '.r00')
    is_zip = archive_path.suffix.lower() == '.zip'

    # Hapus sisa file lama jika ada agar ekstraksi bersih
    if expected_output.exists():
        try: expected_output.unlink()
        except Exception: pass

    passwords_to_try = _resolve_candidate_passwords(archive_path, password, candidate_passwords)
    bin_7z = get_7z_binary(for_rar=is_rar)

    start_time = time.time()
    total_target_bytes = int(expected_size or 0)
    _emit_log("ARCHIVE_EXTRACT", f"📦 Memulai ekstraksi '{target_filename}' dari {archive_path.name}...")

    if bin_7z:
        for pwd in passwords_to_try:
            pwd_flag = f"-p{pwd}" if pwd != "" else "-p"
            cmd = [
                bin_7z, 'e',
                str(archive_path),
                internal_path,
                f"-o{output_dir}",
                pwd_flag,
                "-y"
            ]
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    errors='ignore'
                )

                # Monitor live progress while 7z writes the extracted file to disk
                while proc.poll() is None:
                    time.sleep(0.35)
                    if progress_callback:
                        cur_bytes = 0
                        if expected_output.exists():
                            try:
                                cur_bytes = expected_output.stat().st_size
                            except Exception:
                                pass
                        cur_mb = cur_bytes / (1024 * 1024)
                        tot_mb = total_target_bytes / (1024 * 1024) if total_target_bytes > 0 else 0.0
                        pct = min(99.0, (cur_bytes / total_target_bytes * 100)) if total_target_bytes > 0 else 50.0
                        elapsed = max(0.1, time.time() - start_time)
                        speed_mb = cur_mb / elapsed
                        rem_sec = ((total_target_bytes - cur_bytes) / (speed_mb * 1024 * 1024)) if (total_target_bytes > cur_bytes and speed_mb > 0) else 0
                        eta_str = f"{int(rem_sec)}s" if rem_sec > 0 else "Ekstrak"
                        status_text = f"Mengekstrak {target_filename}: {cur_mb:.1f}/{tot_mb:.1f} MB ({pct:.1f}%)" if tot_mb > 0 else f"Mengekstrak {target_filename}..."
                        try:
                            progress_callback(pct, cur_mb, tot_mb, speed_mb, eta_str, status_text)
                        except Exception:
                            pass

                stdout, stderr = proc.communicate()
                out_all = (stdout or "") + "\n" + (stderr or "")
                
                # Check apakah file berhasil diekstrak
                if expected_output.exists() and expected_output.stat().st_size > 1024:
                    elapsed = max(0.1, time.time() - start_time)
                    file_size = expected_output.stat().st_size
                    speed_mb = (file_size / (1024 * 1024)) / elapsed
                    cur_mb = file_size / (1024 * 1024)
                    tot_mb = cur_mb
                    if progress_callback:
                        try:
                            progress_callback(100.0, cur_mb, tot_mb, speed_mb, "0s", f"Ekstraksi {target_filename} selesai")
                        except Exception:
                            pass
                    _emit_log("ARCHIVE_SUCCESS", f"✓ Ekstraksi '{target_filename}' berhasil ({format_bytes(file_size)}) dalam {elapsed:.1f}s ({speed_mb:.1f} MB/s)!")
                    _ARCHIVE_PASSWORD_CACHE[str(archive_path.resolve())] = pwd
                    return expected_output

                # Jika ada indikasi wrong password, coba kandidat selanjutnya
                if any(kw in out_all.lower() for kw in ['wrong password', 'data error in encrypted']):
                    continue

                if proc.returncode != 0:
                    err_lines = [l.strip() for l in out_all.splitlines() if any(kw in l.lower() for kw in ['error', 'cannot', 'failed', 'crc'])]
                    err_msg = "; ".join(err_lines[:2]) if err_lines else f"exit code {proc.returncode}"
                    _emit_log("ARCHIVE_ERR", f"Kegagalan 7z saat ekstrak '{target_filename}': {err_msg}")
            except Exception as e:
                _emit_log("ARCHIVE_ERR", f"Error subprocess saat ekstrak '{target_filename}': {e}")

    # Fallback untuk file .zip
    if is_zip:
        import zipfile
        for pwd in passwords_to_try:
            try:
                pwd_bytes = pwd.encode('utf-8') if pwd else None
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    with zf.open(internal_path, pwd=pwd_bytes) as src, open(expected_output, 'wb') as dst:
                        cur_bytes = 0
                        chunk_size = 1024 * 1024
                        while True:
                            chunk = src.read(chunk_size)
                            if not chunk:
                                break
                            dst.write(chunk)
                            cur_bytes += len(chunk)
                            if progress_callback:
                                cur_mb = cur_bytes / (1024 * 1024)
                                tot_mb = total_target_bytes / (1024 * 1024) if total_target_bytes > 0 else 0.0
                                pct = min(99.0, (cur_bytes / total_target_bytes * 100)) if total_target_bytes > 0 else 50.0
                                elapsed = max(0.1, time.time() - start_time)
                                speed_mb = cur_mb / elapsed
                                rem_sec = ((total_target_bytes - cur_bytes) / (speed_mb * 1024 * 1024)) if (total_target_bytes > cur_bytes and speed_mb > 0) else 0
                                eta_str = f"{int(rem_sec)}s" if rem_sec > 0 else "Ekstrak"
                                status_text = f"Mengekstrak {target_filename}: {cur_mb:.1f}/{tot_mb:.1f} MB ({pct:.1f}%)" if tot_mb > 0 else f"Mengekstrak {target_filename}..."
                                try:
                                    progress_callback(pct, cur_mb, tot_mb, speed_mb, eta_str, status_text)
                                except Exception:
                                    pass

                if expected_output.exists() and expected_output.stat().st_size > 1024:
                    elapsed = max(0.1, time.time() - start_time)
                    file_size = expected_output.stat().st_size
                    speed_mb = (file_size / (1024 * 1024)) / elapsed
                    cur_mb = file_size / (1024 * 1024)
                    if progress_callback:
                        try:
                            progress_callback(100.0, cur_mb, cur_mb, speed_mb, "0s", f"Ekstraksi {target_filename} selesai")
                        except Exception:
                            pass
                    _emit_log("ARCHIVE_SUCCESS", f"✓ Ekstraksi ZIP '{target_filename}' berhasil ({format_bytes(file_size)}) dalam {elapsed:.1f}s!")
                    return expected_output
            except Exception as ze:
                pass

    _emit_log("ARCHIVE_ERR", f"❌ Gagal mengekstrak '{target_filename}' dari {archive_path.name} setelah mencoba seluruh opsi.")
    return None

def stream_compatibility_guard(video_path: Path) -> Path:
    """
    Memastikan kompatibilitas pemutaran langsung di browser web HTML5 Nipnime:
    - Jika file berformat .mp4, langsung dikembalikan.
    - Jika file berformat .mkv (softsub), jalankan fast remux ke .mp4
      menggunakan ffmpeg copy stream.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        return video_path
        
    if video_path.suffix.lower() == '.mp4':
        return video_path
        
    ffmpeg_bin = get_ffmpeg_binary()
    if not ffmpeg_bin:
        return video_path
        
    mp4_path = video_path.with_suffix('.mp4')
    if mp4_path.exists():
        try: mp4_path.unlink()
        except Exception: pass
        
    cmd = [
        ffmpeg_bin, '-y',
        '-i', str(video_path),
        '-c', 'copy',
        '-movflags', '+faststart',
        str(mp4_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and mp4_path.exists() and mp4_path.stat().st_size > 1024:
            try: video_path.unlink()
            except Exception: pass
            return mp4_path
    except Exception as fe:
        _emit_log("ARCHIVE_WARN", f"Fast remux mkv->mp4 dilewati ({fe}). Menggunakan video asli.")
        
    return video_path

def cleanup_file(path: Path | str | None):
    """Menghapus file dari disk lokal secara aman."""
    if not path:
        return
    p = Path(path)
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass

if __name__ == '__main__':
    print("=== PENGUJIAN MODUL BATCH ARCHIVE MANAGER ===")
    
    bin_7z_rar = get_7z_binary(for_rar=True)
    bin_7z_all = get_7z_binary(for_rar=False)
    bin_ffmpeg = get_ffmpeg_binary()
    print(f"✓ Binary 7z (untuk RAR) : {bin_7z_rar}")
    print(f"✓ Binary 7z (umum)      : {bin_7z_all}")
    print(f"✓ Binary FFmpeg         : {bin_ffmpeg}")
    
    ok, msg = disk_space_guard(1024 * 1024 * 1024)
    print(f"✓ Disk Space Guard       : {ok} -> {msg}")
