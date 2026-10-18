# 🚀 Panduan Menjalankan Nipnime Worker di GitHub Codespaces

Panduan lengkap untuk menjalankan **Nipnime Ongoing Anime & Telegram Video Worker** secara gratis di cloud menggunakan **GitHub Codespaces** dengan koneksi gigabit dan pemrosesan otomatis 24/7.

---

## 🌟 Keuntungan Menjalankan Worker di GitHub Codespaces
1. **Koneksi Super Cepat (Gigabit Cloud)**: Kecepatan unduh & unggah hingga ratusan Mbps ke Telegram MTProto CDN dan server anime.
2. **0 Beban Jaringan Rumah (Indihome Bebas Lag)**: Seluruh proses download, render, dan upload berjalan di server cloud Microsoft / GitHub.
3. **Mendukung Sharding & Gotong Royong**: Otomatis terdeteksi sebagai node `CODESPACE` di dashboard admin `https://nipnime.com/admin/ongoing-watcher`.
4. **Gratis Kuota Bulanan**: Akun GitHub gratis mendapatkan kuota hingga 120 core-hours per bulan (atau 180 core-hours untuk GitHub Pro/Student).

---

## 🛠️ Langkah 1: Siapkan Repositori di GitHub

Disarankan membuat **Repositori Privat (Private)** agar token API Nipnime dan bot Telegram Anda aman.

### Opsi A: Push Folder `terop-worker` ke Repo Baru (Sangat Direkomendasikan)
Di komputer/laptop Anda (atau terminal CasaOS), buka folder `tools/terop-worker` lalu jalankan perintah git berikut:

```bash
# 1. Masuk ke folder worker
cd tools/terop-worker

# 2. Inisialisasi git
git init
git branch -M main

# 3. Tambahkan semua file worker (file sensitif/cache besar otomatis diabaikan oleh .gitignore)
git add .
git commit -m "feat: setup nipnime worker for github codespaces"

# 4. Hubungkan ke repository GitHub Anda (ganti URL di bawah dengan repo Anda)
git remote add origin https://github.com/USERNAME-ANDA/nipnime-worker.git

# 5. Push ke GitHub
git push -u origin main
```

---

## ☁️ Langkah 2: Buat GitHub Codespace (1 Klik)

1. Buka repositori `nipnime-worker` Anda di browser GitHub.
2. Klik tombol hijau **`<> Code`**.
3. Pilih tab **`Codespaces`**.
4. Klik tombol **`Create codespace on main`**.
5. Tunggu sekitar 1–2 menit sementara GitHub menyiapkan container Linux (Python 3.11, Node.js 20, FFmpeg, 7-Zip, dan paket otomatis diinstall melalui `.devcontainer`).

---

## ⚙️ Langkah 3: Konfigurasi Kredensial (.env)

Saat Codespace terbuka di VS Code browser, file `.env` akan dibuat otomatis dari template `.env.codespace.example`.

Pastikan kredensial di dalam file `.env` sudah sesuai:
```env
API_URL=https://nipnime.com/api/terop
WORKER_TOKEN=nipnime_terop_secret_key_2026
WORKER_ROLE=codespace
TELEGRAM_API_ID=37009424
TELEGRAM_API_HASH=9e15f809ab7f895bcd0786c36881599d
TELEGRAM_BOT_TOKEN=8613506821:AAHD74hykC4SKHUdtFqirTZTcz7MJq7k8cI
TELEGRAM_CHANNEL_ID=-1004428873400
TELEGRAM_STREAM_BASE_URL=https://nipnime.com/tg-stream
HEADLESS=true
```

> **Catatan Keamanan (Opsional & Direkomendasikan)**:
> Jika Anda menggunakan repositori publik, jangan simpan token di file `.env`. Gunakan **GitHub Codespaces Secrets**:
> Buka **Settings GitHub** -> **Secrets and variables** -> **Codespaces** -> Tambahkan secret seperti `WORKER_TOKEN`, `TELEGRAM_BOT_TOKEN`, dll.

---

## ▶️ Langkah 4: Jalankan Worker

Di terminal terminal GitHub Codespaces (di bagian bawah layar), cukup ketik:

```bash
./start-codespace.sh
```

Akan muncul menu interaktif:
```text
======================================================================
  PILIHAN MENU CODESPACE WORKER:
  [1] JALANKAN WORKER UTAMA (Daemon 24/7 + Watchdog Auto-Restart)
  [2] TEST SCAN FEED TERBARU (AnimeSail vs Kurama vs NontonAnimeID)
  [3] CEK KONEKSI TELEGRAM & NIPNIME API
  [4] CEK STATUS EPISODE & RESOLUSI ONGOING
  [5] JALANKAN SCRAPER KURAMANIME & NEKOPOI (Puppeteer Headless)
  [0] Keluar
======================================================================
```

- Tekan **`1`** lalu **Enter** untuk menjalankan worker utama non-stop.
- Masukkan jumlah paralel (rekomendasi: **`2`** atau **`3`**).
- Worker akan mulai memantau rilisan anime ongoing baru secara real-time, mengunggah ke Telegram CDN, dan melaporkan detak jantung ke website Nipnime!

---

## 📊 Langkah 5: Pantau di Dashboard Admin Nipnime

Buka dashboard admin Nipnime:
👉 **`https://nipnime.com/admin/ongoing-watcher`**

- Di tabel **Cluster Worker Node**, Anda akan melihat node baru dengan badge **`CODESPACE`** berwarna hijau toska (teal).
- Node Codespace akan bekerja bahu-membahu dengan worker CasaOS & worker laptop:
  - Mengambil unduhan berat melalui jalur gigabit cloud.
  - Membantu backfill episode 1080p, 720p, 480p, dan 360p.
  - Berbagi beban kerja secara cerdas tanpa ada file yang saling bertabrakan (Distributed Claim Lock).

---

## ⏰ Tips Penting: Mencegah Codespaces Mati Sendiri (Idle Timeout)

GitHub Codespaces secara default akan **mati otomatis (suspend)** jika tab browser ditutup atau tidak ada interaksi selama **30 menit**.

Untuk memperpanjang waktu aktif hingga maksimal:
1. Buka pengaturan akun GitHub Anda:
   👉 **https://github.com/settings/codespaces**
2. Cari bagian **Default idle timeout**.
3. Ubah nilainya dari `30 minutes` menjadi **`240 minutes` (4 Jam)** lalu klik simpan.
4. Agar terus berjalan tanpa henti:
   - Cukup biarkan tab browser Codespaces tetap terbuka di background browser laptop/HP Anda.
   - Atau gunakan ekstensi browser auto-refresher / tab pinger.
   - Jika kuota gratis bulanan Codespaces habis, Anda bisa menjalankan di Google Colab atau kembali ke worker lokal/laptop dengan `jalankan-worker-laptop.bat`.
