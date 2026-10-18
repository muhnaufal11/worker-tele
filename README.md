# Nipnime Remote Terop Worker (Kuramanime & Nekopoi)

Aplikasi client worker mandiri untuk laptop Windows / macOS / Linux yang memungkinkan Anda menjalankan ekstraksi video **Kuramanime** dan **Nekopoi** dari mana saja (di luar jaringan rumah, WiFi kafe, tethering HP) menggunakan browser dan prosesor laptop Anda.

Hasil ekstraksi video otomatis langsung disimpan ke database server `https://nipnime.com` via API.

---

## Persyaratan di Laptop
- **Node.js**: Versi 18+ terpasang di laptop (download di https://nodejs.org jika belum ada).
- **Koneksi Internet**: Laptop bisa membuka `https://nipnime.com`.

---

## Cara Penggunaan di Windows (Satu Klik)

1. Anda bisa menjalankan langsung dari folder ini:
   `Z:\tools\terop-worker\`
   *Atau* jika sedang bepergian tanpa sambungan drive Z:, Anda cukup menyalin (copy) seluruh folder `terop-worker` ini ke laptop Anda (misal ke `D:\terop-worker` atau `C:\terop-worker`).

2. Klik dua kali file:
   `start-worker.bat`

3. Pilih mode yang Anda inginkan:
   - **[1] Jalankan Semua (Kuramanime + Nekopoi)**: Menyapu episode terbaru dari kedua sumber.
   - **[2] Jalankan Kuramanime Saja**: Fokus ekstraksi video MP4 Kuramadrive.
   - **[3] Jalankan Nekopoi Saja**: Fokus ekstraksi iframe server anime dewasa.
   - **[4] Mode Otomatis Berkelanjutan (Loop)**: Worker akan terus aktif di latar belakang dan memeriksa tugas baru tiap 45 detik.
   - **[5] Mode Kustom**: Menentukan sendiri jumlah limit episode (misal 50 atau 100 episode).

4. **Untuk Mematikan Worker**:
   Cukup tekan tombol `Ctrl + C` atau tutup langsung jendela terminal.

---

## Mode Tampilan Browser Brave (HIDE vs TAMPIL)

Worker mendukung 2 mode tampilan browser Brave:
- **MODE HIDE (Latar Belakang / Senyap - Rekomendasi)**: Brave berjalan di background secara senyap tanpa memunculkan jendela atau membuka tab di layar laptop. Laptop bebas digunakan untuk aktivitas lain tanpa terganggu.
- **MODE TAMPIL (Jendela Terbuka)**: Jendela Brave terbuka di layar sehingga Anda dapat melihat langsung proses bypass dan scraping.

### Cara Mengatur Mode Browser:
1. **Via Menu `start-worker.bat`**:
   - Di menu utama, status mode browser saat ini langsung tertera di bagian atas.
   - Tekan tombol **`B`** untuk beralih antara Mode HIDE dan Mode TAMPIL.
2. **Via Script Cepat `atur-mode-browser.bat`**:
   - Cukup klik 2x file `atur-mode-browser.bat` untuk beralih mode kapan saja.
3. **Via Argumen CLI**:
   - Tambahkan `--hide` (background) atau `--show` (jendela terbuka).
   - Contoh: `node worker.js --source=neko --download --server-download --loop --hide`

---

## Cara Menjalankan via Terminal / CMD Manual

```bash
# Jalankan mode HIDE (senyap di background)
node worker.js --source=all --limit=20 --hide

# Jalankan mode TAMPIL (jendela browser terlihat)
node worker.js --source=all --limit=20 --show

# Jalankan nekopoi auto server download (mode senyap)
node worker.js --source=neko --download --server-download --loop --limit=30 --hide
```

---

## Konfigurasi (.env)

Pengaturan default sudah otomatis terisi di file `.env`:
- `API_URL`: `https://nipnime.com/api/terop`
- `WORKER_TOKEN`: Token rahasia otentikasi ke server.
- `HEADLESS`: `true` (Mode HIDE: berjalan di background tanpa membuka jendela browser; ubah ke `false` jika ingin melihat browser Brave membuka halaman).
- `POLL_INTERVAL_SECONDS`: Jeda waktu pemeriksaan tugas saat mode loop (default 45 detik).
