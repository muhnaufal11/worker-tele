/**
 * Nipnime Remote Terop Worker (Kuramanime & Nekopoi)
 * 
 * Menjalankan ekstraksi video menggunakan browser/prosesor laptop,
 * lalu menyetorkan link video secara otomatis ke https://nipnime.com.
 * Bisa dijalankan di mana saja (di luar jaringan lokal, WiFi kafe, tethering).
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const http = require('http');
const https = require('https');
const axios = require('axios');
const puppeteer = require('puppeteer');

// Auto-fallback load .env
const envPath = path.join(__dirname, '.env');
if (fs.existsSync(envPath)) {
    require('dotenv').config({ path: envPath });
} else {
    require('dotenv').config();
}

const API_URL = process.env.API_URL || 'https://nipnime.com/api/terop';
const WORKER_TOKEN = process.env.WORKER_TOKEN || 'nipnime_terop_secret_key_2026';
const POLL_INTERVAL = parseInt(process.env.POLL_INTERVAL_SECONDS || '45', 10);

// ANSI Color & Styling Tokens (Zero Emojis, Pure Aesthetic Typography)
const UI = {
    reset: '\x1b[0m',
    bold: '\x1b[1m',
    dim: '\x1b[2m',
    italic: '\x1b[3m',
    underline: '\x1b[4m',

    black: '\x1b[30m',
    red: '\x1b[31m',
    green: '\x1b[32m',
    yellow: '\x1b[33m',
    blue: '\x1b[34m',
    magenta: '\x1b[35m',
    cyan: '\x1b[36m',
    white: '\x1b[37m',
    gray: '\x1b[90m',

    brightRed: '\x1b[91m',
    brightGreen: '\x1b[92m',
    brightYellow: '\x1b[93m',
    brightBlue: '\x1b[94m',
    brightMagenta: '\x1b[95m',
    brightCyan: '\x1b[96m',
    brightWhite: '\x1b[97m',

    time: () => {
        const d = new Date();
        const t = d.toTimeString().split(' ')[0];
        return `${UI.gray}[${t}]${UI.reset}`;
    },

    tabBadge: (tabLabel) => {
        if (tabLabel.includes('KURAMA')) {
            return `${UI.brightCyan}${UI.bold}[${tabLabel}]${UI.reset}`;
        }
        if (tabLabel.includes('NEKO')) {
            return `${UI.brightMagenta}${UI.bold}[${tabLabel}]${UI.reset}`;
        }
        return `${UI.brightWhite}${UI.bold}[${tabLabel}]${UI.reset}`;
    },

    statusBadge: (status) => {
        switch (status) {
            case 'SUCCESS':
            case 'OK':
                return `${UI.brightGreen}${UI.bold}[BERHASIL]${UI.reset}`;
            case 'FAILED':
            case 'GAGAL':
                return `${UI.brightRed}${UI.bold}[GAGAL]${UI.reset}`;
            case 'PROCESS':
            case 'PROSES':
                return `${UI.brightYellow}${UI.bold}[PROSES]${UI.reset}`;
            case 'SEARCH':
                return `${UI.brightBlue}${UI.bold}[CARI]${UI.reset}`;
            default:
                return `${UI.gray}[${status}]${UI.reset}`;
        }
    },

    banner: (sourceMode, limit, headless, isLoop, interval, browserName, isMultiTab, isDownload, storageDir, serverStats) => {
        let srcText = '';
        if (sourceMode === 'kurama') {
            srcText = `${UI.brightCyan}${UI.bold}Kuramanime${UI.reset} ${UI.gray}(Anime TV / Ongoing / Series)${UI.reset}`;
        } else if (sourceMode === 'neko') {
            srcText = `${UI.brightMagenta}${UI.bold}Nekopoi${UI.reset} ${UI.gray}(Anime 18+ / Hentai Collection)${UI.reset}`;
        } else {
            srcText = `${UI.brightCyan}Kuramanime${UI.reset} ${UI.gray}&${UI.reset} ${UI.brightMagenta}Nekopoi${UI.reset} ${UI.gray}(Dual Mode Simultan)${UI.reset}`;
        }

        console.log(`\n${UI.brightCyan}  ┌─────────────────────────────────────────────────────────────┐${UI.reset}`);
        console.log(`${UI.brightCyan}  │${UI.reset}  ${UI.brightWhite}${UI.bold}N I P N I M E   R E M O T E   W O R K E R${UI.reset}       ${UI.gray}v2.2${UI.reset}        ${UI.brightCyan}│${UI.reset}`);
        console.log(`${UI.brightCyan}  │${UI.reset}  ${UI.gray}High-Performance Automated Stream Extractor${UI.reset}               ${UI.brightCyan}│${UI.reset}`);
        console.log(`${UI.brightCyan}  ├─────────────────────────────────────────────────────────────┤${UI.reset}`);
        console.log(`${UI.brightCyan}  │${UI.reset}  ${UI.gray}Target   :${UI.reset} ${srcText}`);
        console.log(`${UI.brightCyan}  │${UI.reset}  ${UI.gray}Tab Mode :${UI.reset} ${isMultiTab ? `${UI.brightYellow}Multi-Tab (2 Tab Paralel)${UI.reset}` : `${UI.brightGreen}Single-Tab (1 Tab Stabil)${UI.reset}`}`);
        const isModeHide = headless !== false && headless !== 'false';
        const modeLabel = isModeHide ? `${UI.brightGreen}MODE HIDE (Latar Belakang / Senyap)${UI.reset}` : `${UI.brightYellow}MODE TAMPIL (Jendela Terbuka)${UI.reset}`;
        console.log(`${UI.brightCyan}  │${UI.reset}  ${UI.gray}Browser  :${UI.reset} ${UI.brightWhite}${browserName}${UI.reset} ${UI.gray}[${modeLabel}${UI.gray}]${UI.reset}`);
        console.log(`${UI.brightCyan}  │${UI.reset}  ${UI.gray}Server   :${UI.reset} ${UI.blue}${API_URL}${UI.reset}`);
        console.log(`${UI.brightCyan}  │${UI.reset}  ${UI.gray}Kapasitas:${UI.reset} ${UI.brightYellow}${limit} episode / batch${UI.reset}`);
        console.log(`${UI.brightCyan}  │${UI.reset}  ${UI.gray}Eksekusi :${UI.reset} ${isLoop ? `${UI.brightGreen}Loop Berkelanjutan${UI.reset} ${UI.gray}(jeda ${interval} dtk)${UI.reset}` : `${UI.brightWhite}1x Selesai${UI.reset}`}`);
        if (sourceMode === 'neko' || sourceMode === 'all') {
            let dlStatus = `${UI.gray}Non-Aktif (Hanya Link Stream Embed)${UI.reset}`;
            if (isDownload) {
                if (IS_SERVER_DOWNLOAD) {
                    dlStatus = `${UI.brightCyan}Aktif (Server-Side CasaOS)${UI.reset} ${UI.gray}(Multi-Q 3-4 Resolusi)${UI.reset}`;
                } else if (storageDir) {
                    dlStatus = `${UI.brightGreen}Aktif (Lokal Y:\\)${UI.reset} ${UI.gray}(Multi-Q 3-4 Resolusi)${UI.reset}`;
                } else {
                    dlStatus = `${UI.brightCyan}Aktif (Auto Server-Side: Y:\\ di luar jangkauan)${UI.reset}`;
                }
            }
            if (isDownload) {
                console.log(`${UI.brightCyan}  │${UI.reset}  ${UI.gray}Watchdog :${UI.reset} ${UI.brightGreen}Aktif (Auto-ganti jika speed < ${MIN_DOWNLOAD_SPEED_MB} MB/s dlm ${SPEED_WATCHDOG_WAIT_SEC}s)${UI.reset}`);
            }
            console.log(`${UI.brightCyan}  │${UI.reset}  ${UI.gray}Unduh MP4:${UI.reset} ${dlStatus}`);
        }
        if (serverStats) {
            const nFilled = serverStats.neko_episodes_filled || 0;
            const nTotal = serverStats.neko_total_episodes || 0;
            const nPct = serverStats.neko_percent || 0;
            const diskSize = serverStats.disk_size_formatted || '0 GB';
            const today = serverStats.added_today || 0;
            console.log(`${UI.brightCyan}  │${UI.reset}  ${UI.gray}Server Ad:${UI.reset} ${UI.brightGreen}${nFilled}/${nTotal} ep Nekopoi (${nPct}%)${UI.reset} ${UI.gray}│${UI.reset} ${UI.cyan}${diskSize}${UI.reset} ${UI.gray}(+${today} hari ini)${UI.reset}`);
        }
        console.log(`${UI.brightCyan}  └─────────────────────────────────────────────────────────────┘${UI.reset}\n`);
    },

    batchSummary: (total, completed, failed, durationSec, nextWaitSec, serverStats) => {
        const percent = total > 0 ? ((completed / total) * 100).toFixed(1) : '0';
        const mins = Math.floor(durationSec / 60);
        const secs = durationSec % 60;
        const durText = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;

        console.log(`\n${UI.gray}  ┌── RINGKASAN BATCH ──────────────────────────────────────────┐${UI.reset}`);
        console.log(`${UI.gray}  │${UI.reset}  ${UI.gray}Total Tugas       :${UI.reset} ${UI.brightWhite}${total}${UI.reset} episode`);
        console.log(`${UI.gray}  │${UI.reset}  ${UI.gray}Berhasil Disetor  :${UI.reset} ${UI.brightGreen}${completed}${UI.reset} episode ${UI.gray}(${percent}%)${UI.reset}`);
        console.log(`${UI.gray}  │${UI.reset}  ${UI.gray}Belum Ditemukan   :${UI.reset} ${failed > 0 ? UI.brightRed + failed : UI.gray + '0'}${UI.reset} episode`);
        console.log(`${UI.gray}  │${UI.reset}  ${UI.gray}Durasi Pengerjaan :${UI.reset} ${UI.brightYellow}${durText}${UI.reset}`);
        if (serverStats) {
            const nFilled = serverStats.neko_episodes_filled || 0;
            const nTotal = serverStats.neko_total_episodes || 0;
            const nPct = serverStats.neko_percent || 0;
            const today = serverStats.added_today || 0;
            console.log(`${UI.gray}  │${UI.reset}  ${UI.gray}Server Admin Live :${UI.reset} ${UI.brightGreen}${nFilled} / ${nTotal} ep Nekopoi (${nPct}%)${UI.reset} ${UI.cyan}[+${today} hari ini]${UI.reset}`);
        }
        if (nextWaitSec) {
            console.log(`${UI.gray}  │${UI.reset}  ${UI.gray}Putaran Berikutnya:${UI.reset} ${UI.cyan}Menunggu ${nextWaitSec} detik...${UI.reset}`);
        }
        console.log(`${UI.gray}  └─────────────────────────────────────────────────────────────┘${UI.reset}\n`);
    }
};

// Cari Brave / Google Chrome / Edge di Windows
function getBrowserInfo() {
    const localAppData = process.env.LOCALAPPDATA || '';
    const candidates = [
        { name: 'Brave Browser', path: process.env.BRAVE_PATH },
        { name: 'Google Chrome', path: process.env.CHROME_PATH },
        { name: 'Custom Browser', path: process.env.BROWSER_PATH },
        { name: 'Brave Browser', path: 'C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe' },
        { name: 'Brave Browser', path: 'C:\\Program Files (x86)\\BraveSoftware\\Brave-Browser\\Application\\brave.exe' },
        { name: 'Brave Browser', path: localAppData ? path.join(localAppData, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe') : null },
        { name: 'Google Chrome', path: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' },
        { name: 'Google Chrome', path: 'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe' },
        { name: 'Microsoft Edge', path: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' },
        { name: 'Microsoft Edge', path: 'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe' },
    ];
    for (const c of candidates) {
        if (c.path && fs.existsSync(c.path)) return c;
    }
    return { name: 'Puppeteer Chromium', path: undefined };
}

// Parse argumen CLI
const args = process.argv.slice(2);
function getArg(name, def) {
    for (const a of args) {
        if (a.startsWith(`--${name}=`)) return a.split('=')[1];
    }
    return def;
}

// Cek parameter headless / hide / show
let HEADLESS = 'new';
let savedBrowserMode = '';
const modeFile = path.join(__dirname, 'browser_mode.txt');
if (fs.existsSync(modeFile)) {
    try { savedBrowserMode = fs.readFileSync(modeFile, 'utf8').trim().toLowerCase(); } catch (e) {}
}

const browserModeArg = (getArg('browser', getArg('mode-browser', ''))).toLowerCase();
if (args.includes('--hide') || args.includes('--headless') || getArg('headless') === 'true' || browserModeArg === 'hide' || browserModeArg === 'background') {
    HEADLESS = 'new';
} else if (args.includes('--show') || args.includes('--head') || getArg('headless') === 'false' || browserModeArg === 'show' || browserModeArg === 'tampil') {
    HEADLESS = false;
} else if (savedBrowserMode === 'tampil' || savedBrowserMode === 'show') {
    HEADLESS = false;
} else if (savedBrowserMode === 'hide' || savedBrowserMode === 'senyap') {
    HEADLESS = 'new';
} else {
    HEADLESS = (process.env.HEADLESS === 'false' || process.env.HEADLESS === 'show') ? false : 'new';
}

const SOURCE_MODE = getArg('source', process.env.DEFAULT_SOURCE || 'all');
const BATCH_LIMIT = parseInt(getArg('limit', process.env.DEFAULT_LIMIT || '20'), 10);
const MAX_SCAN_PAGES = parseInt(getArg('max-scan-pages', '30'), 10);
const LOOP_MODE = args.includes('--loop') || args.includes('-l');
const IS_MULTI_TAB = args.includes('--multi-tab') || parseInt(getArg('tabs', '1'), 10) > 1;

// Direktori penyimpanan video server lokal CasaOS (Y:\)
const VIDEO_STORAGE_DIR = process.env.VIDEO_STORAGE_DIR || (fs.existsSync('Y:\\') ? 'Y:\\' : null);
const DOWNLOAD_MODE = (args.includes('--download') || getArg('download') === 'true' || process.env.DOWNLOAD_MODE === 'true') && !args.includes('--no-download');
const IS_SERVER_DOWNLOAD = args.includes('--server-download') || getArg('server-download') === 'true' || process.env.SERVER_DOWNLOAD === 'true';

// Parameter Ambang Batas Kecepatan Minimum (Speed Watchdog)
// Default: 1.0 MB/s (bisa diatur via --min-speed=1.5 atau .env MIN_DOWNLOAD_SPEED_MB=1.0)
const MIN_DOWNLOAD_SPEED_MB = parseFloat(getArg('min-speed', process.env.MIN_DOWNLOAD_SPEED_MB || '1.0'));
const SPEED_WATCHDOG_WAIT_SEC = parseInt(getArg('speed-wait', process.env.SPEED_WATCHDOG_WAIT_SEC || '8'), 10);

const insecureAgent = new https.Agent({ rejectUnauthorized: false });

const client = axios.create({
    baseURL: API_URL,
    headers: {
        'X-Terop-Token': WORKER_TOKEN,
        'Accept': 'application/json',
    },
    httpsAgent: insecureAgent,
    timeout: 90000,
});

const MEDIA_RE = /\.m3u8|\.mp4(\?|$)|kuramadrive/i;
const SKIP_HOSTS = ['a-ads.com', 'discord', 'disqus', 'facebook', 'twitter', 'youtube', 'google', 'chatango.com'];

function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
}

function log(msg) {
    console.log(`${UI.time()} ${msg}`);
}

async function requestTasks(source, limit) {
    try {
        const res = await client.get('/tasks', {
            params: {
                source,
                limit,
                download: DOWNLOAD_MODE ? 1 : 0
            }
        });
        if (res.data && res.data.success) {
            return res.data.tasks || [];
        }
        return [];
    } catch (err) {
        if (err.response) {
            console.log(`${UI.time()} ${UI.brightRed}[ERROR]${UI.reset} Gagal meminta tugas (HTTP ${err.response.status}): ${JSON.stringify(err.response.data)}`);
        } else {
            console.log(`${UI.time()} ${UI.brightRed}[ERROR]${UI.reset} Gagal terhubung ke server: ${err.message}`);
        }
        return [];
    }
}

async function submitResult(payload) {
    try {
        const res = await client.post('/submit', payload);
        return res.data && res.data.success;
    } catch (err) {
        const msg = err.response && err.response.data ? JSON.stringify(err.response.data) : err.message;
        console.log(`         ${UI.gray}└─ Gagal Setor :${UI.reset} ${UI.brightRed}${msg}${UI.reset}`);
        return false;
    }
}

async function fetchServerAdminStats() {
    try {
        const res = await client.get('/status');
        if (res.data && res.data.success && res.data.server_admin) {
            return res.data.server_admin;
        }
    } catch (e) {}
    return null;
}

const kuramaAnimeCache = new Map();
const kuramaAnimeRangeCache = new Map();
const activeWorkerPages = new Set();

async function cleanupStrayTabs(browser) {
    if (!browser) return;
    try {
        const pages = await browser.pages().catch(() => []);
        if (pages.length <= 1) return; // Lindungi tab terakhir agar browser tidak mati
        for (const p of pages) {
            if (!activeWorkerPages.has(p)) {
                const current = await browser.pages().catch(() => []);
                if (current.length > 1) {
                    await p.close().catch(() => {});
                }
            }
        }
    } catch (e) {}
}

async function checkAndBypassCloudflare(page, print = console.log) {
    if (!page) return false;
    try {
        const title = (await page.title().catch(() => '')).toLowerCase();
        const content = (await page.content().catch(() => '')).toLowerCase();
        
        const isCloudflare = title.includes('just a moment') || 
                             content.includes('verify you are human') || 
                             content.includes('please go to captcha') ||
                             content.includes('challenges.cloudflare.com');

        if (isCloudflare) {
            print(`         ${UI.gray}├─ Cloudflare:${UI.reset} ${UI.yellow}Mendeteksi verifikasi Turnstile, mencoba klik otomatis...${UI.reset}`);
            await sleep(1500);

            // Coba klik checkbox di frame turnstile
            const frames = page.frames();
            for (const frame of frames) {
                try {
                    const cb = await frame.$('input[type="checkbox"], .ctp-checkbox-label, #challenge-stage input');
                    if (cb) {
                        const box = await cb.boundingBox();
                        if (box) {
                            await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
                            print(`         ${UI.gray}├─ Cloudflare:${UI.reset} ${UI.brightGreen}Checkbox Turnstile berhasil diklik!${UI.reset}`);
                            await sleep(3500);
                            return true;
                        }
                    }
                } catch (e) {}
            }

            // Fallback klik elemen turnstile di halaman utama
            const turnstileElem = await page.$('iframe[src*="turnstile"], iframe[src*="challenge"], iframe[src*="cloudflare"], #cf-turnstile');
            if (turnstileElem) {
                const box = await turnstileElem.boundingBox();
                if (box) {
                    await page.mouse.click(box.x + 30, box.y + box.height / 2);
                    print(`         ${UI.gray}├─ Cloudflare:${UI.reset} ${UI.brightGreen}Area Turnstile diklik via koordinat mouse!${UI.reset}`);
                    await sleep(3500);
                    return true;
                }
            }
        }
    } catch (e) {}
    return false;
}

async function getKuramaEpisodeRange(page) {
    try {
        return await page.evaluate(() => {
            let minEp = null;
            let maxEp = null;

            // 1. Ekstrak dari popover attribute Daftar Episode (#episodeLists)
            const epListBtn = document.querySelector('#episodeLists, [data-original-title*="Episode"], [data-content*="Terlama"], [data-content*="Terbaru"]');
            const popoverHtml = epListBtn ? (epListBtn.getAttribute('data-content') || epListBtn.getAttribute('data-bs-content') || '') : '';

            if (popoverHtml) {
                const mTerlama = popoverHtml.match(/Ep\s*(\d+)\s*\([^)]*Terlama[^)]*\)/i) || popoverHtml.match(/(\d+)\s*\([^)]*Terlama[^)]*\)/i);
                if (mTerlama) minEp = parseInt(mTerlama[1], 10);

                const mTerbaru = popoverHtml.match(/Ep\s*(\d+)\s*\([^)]*Terbaru[^)]*\)/i) || popoverHtml.match(/(\d+)\s*\([^)]*Terbaru[^)]*\)/i);
                if (mTerbaru) maxEp = parseInt(mTerbaru[1], 10);

                if (minEp === null || maxEp === null) {
                    const allNums = Array.from(popoverHtml.matchAll(/\/episode\/(\d+)/g)).map(m => parseInt(m[1], 10));
                    if (allNums.length > 0) {
                        if (minEp === null) minEp = Math.min(...allNums);
                        if (maxEp === null) maxEp = Math.max(...allNums);
                    }
                }
            }

            // 2. Jika belum ditemukan, periksa rendered DOM text
            if (minEp === null || maxEp === null) {
                const all = Array.from(document.querySelectorAll('a, button, div, span, p'));
                for (const el of all) {
                    const txt = (el.innerText || '').trim();
                    if (/Terlama/i.test(txt)) {
                        const m = txt.match(/Ep\s*(\d+)/i) || txt.match(/(\d+)/);
                        if (m && minEp === null) minEp = parseInt(m[1], 10);
                    }
                    if (/Terbaru/i.test(txt)) {
                        const m = txt.match(/Ep\s*(\d+)/i) || txt.match(/(\d+)/);
                        if (m && maxEp === null) maxEp = parseInt(m[1], 10);
                    }
                }
            }

            // 3. Fallback periksa semua link episode langsung di DOM
            if (minEp === null || maxEp === null) {
                const epLinks = Array.from(document.querySelectorAll('a[href*="/episode/"]'));
                const nums = epLinks.map(a => {
                    const m = a.href.match(/\/episode\/(\d+)/i);
                    return m ? parseInt(m[1], 10) : null;
                }).filter(n => n !== null);
                if (nums.length > 0) {
                    if (minEp === null) minEp = Math.min(...nums);
                    if (maxEp === null) maxEp = Math.max(...nums);
                }
            }

            return { minEp, maxEp };
        });
    } catch (e) {
        return { minEp: null, maxEp: null };
    }
}

function cleanTitleWords(title) {
    return (title || '')
        .replace(/\[[^\]]*\]/g, ' ')
        .replace(/\([^\)]*\)/g, ' ')
        .replace(/[:\-–—]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

// 1. Cari Link Episode Kuramanime di Browser Brave
async function resolveKuramaUrl(page, animeTitle, episodeNumber, animeSlug) {
    if (kuramaAnimeCache.has(animeTitle)) {
        const animeBaseUrl = kuramaAnimeCache.get(animeTitle);
        if (!kuramaAnimeRangeCache.has(animeTitle)) {
            try {
                await page.goto(animeBaseUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
                const range = await getKuramaEpisodeRange(page);
                if (range && (range.minEp !== null || range.maxEp !== null)) {
                    kuramaAnimeRangeCache.set(animeTitle, range);
                }
            } catch (e) {}
        }
        return `${animeBaseUrl}/episode/${episodeNumber}`;
    }

    const rawPrimary = (animeTitle.split(/[:\-–—]/)[0] || animeTitle).trim();
    const primaryTitle = cleanTitleWords(rawPrimary);
    const clean = cleanTitleWords(animeTitle);
    const searchTerms = Array.from(new Set([
        primaryTitle,
        clean,
        animeSlug ? animeSlug.replace(/-/g, ' ') : null,
    ])).filter(t => t && t.trim().length >= 2);

    for (const term of searchTerms) {
        try {
            const searchUrl = `https://v20.kuramanime.ing/anime?search=${encodeURIComponent(term.trim())}`;
            await page.goto(searchUrl, { waitUntil: 'domcontentloaded', timeout: 25000 });

            const animeBaseUrl = await page.evaluate((targetTitle) => {
                const links = Array.from(document.querySelectorAll('a[href*="/anime/"]'));
                const cleanStr = (s) => (s || '').toLowerCase()
                    .replace(/^\[(.*)\]$/, '$1')
                    .replace(/[^a-z0-9\s]/g, ' ')
                    .replace(/\s+/g, ' ')
                    .trim();

                const targetClean = cleanStr(targetTitle);
                if (!targetClean) return null;

                for (const a of links) {
                    const href = a.href || '';
                    if (!href || href.includes('/episode/')) continue;
                    const h = a.querySelector('h5, h4, h3, h2, h1, .title');
                    const cardTitle = (h ? h.innerText : a.innerText || '').trim();
                    if (!cardTitle || cardTitle.toLowerCase().includes('loading')) continue;

                    const cleanCard = cleanStr(cardTitle);

                    // 100% Presisi Eksak: HANYA cocok jika judul sama persis (tanpa kata ekstra di belakang/depan)
                    if (cleanCard === targetClean) {
                        return href.replace(/\/+$/, '');
                    }
                }
                return null;
            }, animeTitle);

            if (animeBaseUrl) {
                kuramaAnimeCache.set(animeTitle, animeBaseUrl);

                // Ekstrak rentang episode yang tersedia di Kuramanime (Terlama & Terbaru)
                try {
                    await page.goto(animeBaseUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
                    const range = await getKuramaEpisodeRange(page);
                    if (range && (range.minEp !== null || range.maxEp !== null)) {
                        kuramaAnimeRangeCache.set(animeTitle, range);
                    }
                } catch (e) {}

                return `${animeBaseUrl}/episode/${episodeNumber}`;
            }
        } catch (e) {}
    }

    return null;
}

// 2. Cari Link Episode Nekopoi di Browser Brave
async function resolveNekopoiUrl(page, animeTitle, episodeNumber, animeSlug) {
    if (animeSlug) {
        const slugNorm = animeSlug
            .replace(/aa/g, 'a')
            .replace(/ee/g, 'e')
            .replace(/ii/g, 'i')
            .replace(/oo/g, 'o')
            .replace(/uu/g, 'u')
            .replace(/-tte-/g, 'tte-')
            .replace(/-+/, '-');

        const slugs = Array.from(new Set([
            animeSlug,
            slugNorm,
            animeSlug.replace(/-tte-/g, 'tte-'),
            animeSlug.replace(/-/g, '')
        ]));

        const candidateUrls = [];
        for (const s of slugs) {
            candidateUrls.push(`https://nekopoi.care/new-release-${s}-episode-${episodeNumber}-subtitle-indonesia/`);
            candidateUrls.push(`https://nekopoi.care/${s}-episode-${episodeNumber}-subtitle-indonesia/`);
            candidateUrls.push(`https://nekopoi.care/new-release-${s}-ep-${episodeNumber}-subtitle-indonesia/`);
            candidateUrls.push(`https://nekopoi.care/${s}-ep-${episodeNumber}-subtitle-indonesia/`);
        }

        for (const directUrl of candidateUrls) {
            try {
                const res = await page.goto(directUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
                if (res && res.status() === 200) {
                    const isFound = await page.evaluate(() => {
                        const isError = document.body.classList.contains('error404') || 
                                        document.querySelector('.error404, .not-found') !== null ||
                                        (document.title && /404\s*(not\s*found)?|halaman\s*tidak\s*ditemukan/i.test(document.title));
                        const hasContent = document.querySelector('.nk-article, .nk-main-content, .nk-download-section, .nk-download-box, .nk-download-row, article, .post, .entry-content, .contentpost, #nk-player, iframe') !== null;
                        return !isError && hasContent;
                    });
                    if (isFound) return directUrl;
                }
            } catch (e) {}
        }
    }

    const rawPrimary = (animeTitle.split(/[:\-–—]/)[0] || animeTitle).trim();
    const primaryTitle = cleanTitleWords(rawPrimary);
    const primaryNoDouble = primaryTitle.replace(/aa/g, 'a').replace(/ee/g, 'e').replace(/ii/g, 'i').replace(/oo/g, 'o').replace(/uu/g, 'u');
    const clean = cleanTitleWords(animeTitle);
    const cleanNoDouble = clean.replace(/aa/g, 'a').replace(/ee/g, 'e').replace(/ii/g, 'i').replace(/oo/g, 'o').replace(/uu/g, 'u');

    // Tambahkan variasi kata depan (3-4 kata pertama) untuk query pencarian WordPress Nekopoi
    const words = primaryTitle.split(/\s+/).filter(w => w.length > 1);
    const shortPrefix3 = words.length >= 3 ? words.slice(0, 3).join(' ') : null;
    const shortPrefix4 = words.length >= 4 ? words.slice(0, 4).join(' ') : null;

    const searchTerms = Array.from(new Set([
        primaryTitle,
        primaryNoDouble,
        clean,
        cleanNoDouble,
        shortPrefix4,
        shortPrefix3,
        animeSlug ? animeSlug.replace(/-/g, ' ') : null,
    ])).filter(t => t && t.trim().length >= 3);

    for (const term of searchTerms) {
        try {
            // Cek hingga 2 halaman hasil pencarian jika anime memiliki banyak episode
            for (let pageNum = 1; pageNum <= 2; pageNum++) {
                const searchUrl = pageNum === 1
                    ? `https://nekopoi.care/search/${encodeURIComponent(term.trim()).replace(/%20/g, '+')}/`
                    : `https://nekopoi.care/search/${encodeURIComponent(term.trim()).replace(/%20/g, '+')}/page/${pageNum}/`;

                const res = await page.goto(searchUrl, { waitUntil: 'domcontentloaded', timeout: 25000 }).catch(() => null);
                if (!res || res.status() === 404) break;

                const epUrl = await page.evaluate((epNum, fullTitle) => {
                    const items = Array.from(document.querySelectorAll('a.nk-search-item, .nk-search-item'));
                    const cleanStr = (s) => (s || '').toLowerCase()
                        .replace(/^(\s*\[[^\]]*\]\s*)+/, '')
                        .replace(/\s*episode\s*\d+.*$/i, '')
                        .replace(/\s*ep\s*\d+.*$/i, '')
                        .replace(/\s*subtitle\s*indonesia.*$/i, '')
                        .replace(/\s*sub\s*indo.*$/i, '')
                        .replace(/[^a-z0-9\s]/g, ' ')
                        .replace(/\s+/g, ' ')
                        .trim();

                    const normalizeTitle = (s) => cleanStr(s)
                        .replace(/\bthe\s+animation\b/gi, '')
                        .replace(/aa/g, 'a')
                        .replace(/ee/g, 'e')
                        .replace(/ii/g, 'i')
                        .replace(/oo/g, 'o')
                        .replace(/uu/g, 'u')
                        .replace(/\s+/g, ' ')
                        .trim();

                    const targetClean = cleanStr(fullTitle);
                    const targetNorm = normalizeTitle(fullTitle);
                    if (!targetClean) return null;

                    // Regex pencocokan nomor episode yang presisi (menghindari 'episode 1' mencocokkan 'episode 12')
                    const epRegex = new RegExp('(?:episode|ep)[\\s\\-_/]*0*' + epNum + '(?!\\d)', 'i');

                    for (const item of items) {
                        const href = item.href || item.getAttribute('href') || '';
                        const h2 = item.querySelector('h2');
                        const rawText = ((h2 ? h2.innerText : item.innerText) || '').trim();
                        const hrefLow = href.toLowerCase();

                        const hasEp = epRegex.test(rawText) || epRegex.test(hrefLow);
                        if (!hasEp) continue;

                        const cleanCard = cleanStr(rawText);
                        const normCard = normalizeTitle(rawText);

                        // Presisi Cerdas: Cocok jika judul sama persis (dengan/tanpa 'The Animation'),
                        // atau card dimulai dengan target yang cukup panjang
                        const isMatch = (cleanCard === targetClean) ||
                                        (normCard === targetNorm) ||
                                        (targetNorm.length >= 10 && normCard.startsWith(targetNorm)) ||
                                        (normCard.length >= 10 && targetNorm.startsWith(normCard));

                        if (isMatch) {
                            if (hrefLow.includes('nekopoi.care') || href.startsWith('/')) {
                                return href;
                            }
                        }
                    }
                    return null;
                }, episodeNumber, animeTitle);

                if (epUrl) return epUrl;
            }
        } catch (e) {}
    }

    return null;
}

async function extractKurama(page, task, tabLabel, logFn) {
    const print = logFn || console.log;
    let foundMedia = null;
    const onResponse = (r) => {
        const u = r.url();
        if (MEDIA_RE.test(u) && (/kdrive/i.test(u) || /\.mp4(\?|$)/i.test(u))) {
            foundMedia = u;
        }
    };

    try {
        // 1. Cek rentang episode valid jika sudah pernah tercatat
        const range = kuramaAnimeRangeCache.get(task.anime_title);
        if (range && range.minEp !== null && task.episode_number < range.minEp) {
            print(`         ${UI.gray}└─ Status    :${UI.reset} ${UI.brightYellow}[LEWATI]${UI.reset} ${UI.gray}Ep ${task.episode_number} tidak ada di Kuramanime (Tersedia: Ep ${range.minEp} s/d ${range.maxEp})${UI.reset}`);
            await submitResult({
                task_id: task.task_id,
                source: 'kuramanime',
                episode_id: task.episode_id,
                status: 'unavailable',
                min_episode: range.minEp,
                max_episode: range.maxEp
            });
            return { skipped: true };
        }
        if (range && range.maxEp !== null && task.episode_number > range.maxEp) {
            print(`         ${UI.gray}└─ Status    :${UI.reset} ${UI.brightYellow}[LEWATI]${UI.reset} ${UI.gray}Ep ${task.episode_number} belum rilis di Kuramanime (Tersedia: Ep ${range.minEp} s/d ${range.maxEp})${UI.reset}`);
            await submitResult({
                task_id: task.task_id,
                source: 'kuramanime',
                episode_id: task.episode_id,
                status: 'unavailable',
                min_episode: range.minEp,
                max_episode: range.maxEp
            });
            return { skipped: true };
        }

        let targetUrl = task.url;
        if (!targetUrl) {
            print(`         ${UI.gray}├─ Pencarian :${UI.reset} ${UI.gray}Mencari link anime di Kuramanime...${UI.reset}`);
            targetUrl = await resolveKuramaUrl(page, task.anime_title, task.episode_number, task.anime_slug);
        }

        // Cek ulang rentang setelah pencarian URL anime selesai
        const updatedRange = kuramaAnimeRangeCache.get(task.anime_title);
        if (updatedRange && updatedRange.minEp !== null && task.episode_number < updatedRange.minEp) {
            print(`         ${UI.gray}└─ Status    :${UI.reset} ${UI.brightYellow}[LEWATI]${UI.reset} ${UI.gray}Ep ${task.episode_number} tidak ada di Kuramanime (Tersedia: Ep ${updatedRange.minEp} s/d ${updatedRange.maxEp})${UI.reset}`);
            await submitResult({
                task_id: task.task_id,
                source: 'kuramanime',
                episode_id: task.episode_id,
                status: 'unavailable',
                min_episode: updatedRange.minEp,
                max_episode: updatedRange.maxEp
            });
            return { skipped: true };
        }
        if (updatedRange && updatedRange.maxEp !== null && task.episode_number > updatedRange.maxEp) {
            print(`         ${UI.gray}└─ Status    :${UI.reset} ${UI.brightYellow}[LEWATI]${UI.reset} ${UI.gray}Ep ${task.episode_number} belum rilis di Kuramanime (Tersedia: Ep ${updatedRange.minEp} s/d ${updatedRange.maxEp})${UI.reset}`);
            await submitResult({
                task_id: task.task_id,
                source: 'kuramanime',
                episode_id: task.episode_id,
                status: 'unavailable',
                min_episode: updatedRange.minEp,
                max_episode: updatedRange.maxEp
            });
            return { skipped: true };
        }

        if (!targetUrl) {
            print(`         ${UI.gray}└─ Hasil     :${UI.reset} ${UI.statusBadge('FAILED')} Judul/episode tidak ditemukan`);
            await submitResult({
                task_id: task.task_id,
                source: 'kuramanime',
                episode_id: task.episode_id,
                status: 'unavailable',
            });
            return { skipped: true };
        }

        print(`         ${UI.gray}├─ Target    :${UI.reset} ${UI.cyan}${targetUrl}${UI.reset}`);

        page.on('response', onResponse);

        const navRes = await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 35000 }).catch(() => null);

        // Hanya anggap 404 jika HTTP status benar-benar 404
        if (navRes && navRes.status() === 404) {
            page.off('response', onResponse);
            print(`         ${UI.gray}└─ Status    :${UI.reset} ${UI.brightRed}[404 GAGAL]${UI.reset} ${UI.gray}Halaman episode 404 di Kuramanime${UI.reset}`);
            await submitResult({
                task_id: task.task_id,
                source: 'kuramanime',
                episode_id: task.episode_id,
                status: 'unavailable',
            });
            return { skipped: true, isAnimeUnavailable: (task.episode_number === 1) };
        }

        // Beri waktu player video untuk render di DOM (maksimal 7 detik)
        await page.waitForSelector('#player, video, iframe', { timeout: 7000 }).catch(() => null);

        // Trigger klik player jika dibutuhkan
        await page.evaluate(() => {
            const btn = document.querySelector('.vjs-big-play-button, .play-button, #player');
            if (btn) btn.click();
        }).catch(() => null);

        // Tunggu stream video muncul (maksimal 15 detik)
        for (let i = 0; i < 15; i++) {
            if (foundMedia) break;

            const res = await page.evaluate(() => {
                const p = document.querySelector('#player');
                const so = p && p.querySelector('source') ? p.querySelector('source').src : null;
                const hs = p ? (p.getAttribute('data-hls-src') || p.getAttribute('data-hlssrc')) : null;
                const v = document.querySelector('video');
                const vsrc = v && v.currentSrc ? v.currentSrc : null;
                return so || hs || vsrc;
            }).catch(() => null);

            if (res && (/kdrive/i.test(res) || /\.mp4(\?|$)/i.test(res))) {
                foundMedia = res;
                break;
            }

            await sleep(1000);
        }

        page.off('response', onResponse);

        if (foundMedia) {
            let quality = '720p';
            const m = foundMedia.match(/(\d{3,4})p/i);
            if (m) quality = m[1] + 'p';
            return { url: foundMedia, quality };
        }

        return null;
    } catch (err) {
        page.off('response', onResponse);
        print(`         ${UI.gray}├─ Error     :${UI.reset} ${UI.brightRed}${err.message}${UI.reset}`);
        return null;
    }
}

async function resolveOuoLink(browser, ouoUrl, print = console.log) {
    if (!ouoUrl || (!ouoUrl.includes('ouo.io') && !ouoUrl.includes('ouo.press'))) {
        return ouoUrl;
    }
    let page = null;
    try {
        page = await browser.newPage();
        activeWorkerPages.add(page);
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
        await page.evaluateOnNewDocument(() => {
            window.open = function() { return null; };
            window.alert = function() {};
            try {
                Object.defineProperty(window.history, 'back', { value: function() {}, writable: false, configurable: false });
                Object.defineProperty(window.history, 'go', { value: function() {}, writable: false, configurable: false });
            } catch (e) {
                window.history.back = function() {};
                window.history.go = function() {};
            }
        });

        await page.goto(ouoUrl, { waitUntil: 'domcontentloaded', timeout: 25000 });
        let curUrl = page.url();
        if (!curUrl.includes('ouo.io') && !curUrl.includes('ouo.press')) {
            print(`         ${UI.gray}│  ouo langsung: ${curUrl}${UI.reset}`);
            return curUrl;
        }

        // Step 1: Submit form human verification via form.submit() (kebal click-jacking overlay iklan)
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => {}),
            page.evaluate(() => {
                const f = document.querySelector('form');
                if (f) f.submit();
                else {
                    const btn = document.querySelector('form button[type="submit"], input[type="submit"], #btn-main');
                    if (btn) btn.click();
                }
            }).catch(() => {})
        ]);

        curUrl = page.url();
        if (!curUrl.includes('ouo.io') && !curUrl.includes('ouo.press')) {
            print(`         ${UI.gray}│  ouo step 1 selesai: ${curUrl}${UI.reset}`);
            return curUrl;
        }

        // Step 2: Tunggu countdown ~4.5 detik
        await sleep(4500);

        // Step 3: Submit form Get Link via form.submit()
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => {}),
            page.evaluate(() => {
                const f = document.querySelector('form');
                if (f) f.submit();
                else {
                    const btn = document.querySelector('#btn-main, form button[type="submit"], input[type="submit"]');
                    if (btn) btn.click();
                }
            }).catch(() => {})
        ]);

        curUrl = page.url();
        print(`         ${UI.gray}│  ouo hasil: ${curUrl}${UI.reset}`);
        return (!curUrl.includes('ouo.io') && !curUrl.includes('ouo.press')) ? curUrl : null;
    } catch (e) {
        print(`         ${UI.gray}├─ Bypass ouo :${UI.reset} ${UI.brightRed}Gagal: ${e.message}${UI.reset}`);
        return null;
    } finally {
        if (page) {
            activeWorkerPages.delete(page);
            await page.close().catch(() => {});
        }
    }
}

function findOuoLink(links, pattern) {
    if (!links || typeof links !== 'object') return null;
    // 1. Prioritaskan yang ada tag [ouo]
    for (const [k, v] of Object.entries(links)) {
        if (pattern.test(k) && /ouo/i.test(k) && typeof v === 'string') {
            return v;
        }
    }
    // 2. Link ouo langsung
    for (const [k, v] of Object.entries(links)) {
        if (pattern.test(k) && typeof v === 'string' && (v.includes('ouo.io') || v.includes('ouo.press'))) {
            return v;
        }
    }
    // 3. Fallback nama host umum
    for (const [k, v] of Object.entries(links)) {
        if (pattern.test(k) && typeof v === 'string') {
            return v;
        }
    }
    return null;
}

async function resolveMp4UploadDirect(embedUrl) {
    if (!embedUrl) return null;
    try {
        const res = await axios.get(embedUrl, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://www.mp4upload.com/'
            },
            timeout: 12000
        });
        const html = typeof res.data === 'string' ? res.data : '';
        const m = html.match(/player\.src\(\s*\{\s*type:\s*["']video\/mp4["'],\s*src:\s*["']([^"']+)["']/i) 
               || html.match(/src:\s*["'](https?:\/\/[^"']+\.mp4[^"']*)["']/i);
        return m ? m[1] : null;
    } catch (e) {
        return null;
    }
}

async function resolveMirroredHosts(browser, mirroredUrl, print = console.log) {
    if (!mirroredUrl || !mirroredUrl.includes('mirrored.to')) {
        return [];
    }
    let page = null;
    const results = [];
    try {
        page = await browser.newPage();
        activeWorkerPages.add(page);
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
        await page.evaluateOnNewDocument(() => {
            window.open = function() { return null; };
            window.alert = function() {};
            try {
                Object.defineProperty(window.history, 'back', { value: function() {}, writable: false, configurable: false });
                Object.defineProperty(window.history, 'go', { value: function() {}, writable: false, configurable: false });
            } catch (e) {
                window.history.back = function() {};
                window.history.go = function() {};
            }
        });

        await page.goto(mirroredUrl, { waitUntil: 'domcontentloaded', timeout: 25000 });

        // Klik tombol "Click to view the download links" jika ada
        const getBtn = await page.$('.get_btn, a[href*="hash="]');
        if (getBtn) {
            await Promise.all([
                page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => {}),
                getBtn.click()
            ]);
        }

        // Tunggu tabel host selesai di-render
        await page.waitForSelector('table tr td, #result', { timeout: 12000 }).catch(() => {});
        await sleep(1500);

        const hostRows = await page.evaluate(() => {
            const trs = document.querySelectorAll('table tr');
            return Array.from(trs).map(tr => {
                const host = tr.querySelector('td[data-label="Host"] img')?.getAttribute('alt') || tr.querySelector('td[data-label="Host"]')?.innerText?.trim() || '';
                const link = tr.querySelector('td[data-label="File Link"] a')?.getAttribute('href') || tr.querySelector('td[data-label="File Link"] a')?.href || '';
                const status = tr.querySelector('td[data-label="Upload Status"]')?.innerText?.trim() || '';
                return { host, link, status };
            }).filter(x => x.host && x.link && !x.status.toLowerCase().includes('failed'));
        });

        if (hostRows.length > 0) {
            print(`         ${UI.gray}│  mirrored.to hosts (${hostRows.length}): ${hostRows.map(h => h.host).join(', ')}${UI.reset}`);
        }

        // Ambil link download dari halaman getlink
        for (const row of hostRows) {
            const fullLink = row.link.startsWith('http') ? row.link : `https://www.mirrored.to${row.link}`;
            try {
                await page.goto(fullLink, { waitUntil: 'domcontentloaded', timeout: 15000 });
                const directUrl = await page.evaluate(() => {
                    const anchors = Array.from(document.querySelectorAll('a'));
                    for (const a of anchors) {
                        if (a.href && !a.href.includes('mirrored.to') && !a.href.includes('x.com') && !a.href.includes('javascript:')) {
                            return a.href;
                        }
                    }
                    const match = document.body.innerText.match(/https?:\/\/[^\s"'<>()]+/);
                    return match ? match[0] : null;
                });

                if (directUrl) {
                    results.push({ host: row.host, url: directUrl });
                }
            } catch (err) {
                // Abaikan jika salah satu getlink timeout
            }
        }
    } catch (e) {
        print(`         ${UI.gray}├─ Mirror resolve :${UI.reset} ${UI.brightRed}Gagal: ${e.message}${UI.reset}`);
    } finally {
        if (page) {
            activeWorkerPages.delete(page);
            await page.close().catch(() => {});
        }
    }
    return results;
}

async function downloadDirectVideo(downloadUrl, destPath, print = console.log, options = {}) {
    const dir = path.dirname(destPath);
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
    }

    // Gunakan buffer SSD lokal laptop (%TEMP%) agar download stream berkecepatan penuh
    // dan tidak tertahan oleh latensi penulisan SMB Wi-Fi ke Y:\
    const localTmpDir = path.join(os.tmpdir(), 'nipnime_cache');
    if (!fs.existsSync(localTmpDir)) {
        try { fs.mkdirSync(localTmpDir, { recursive: true }); } catch (e) {}
    }
    const localTmpPath = path.join(localTmpDir, `nip_${Date.now()}_${path.basename(destPath)}`);

    // Tentukan referer yang tepat (Mp4Upload/Pixeldrain/Mirrored butuh Referer yang sesuai)
    let referer = downloadUrl;
    if (downloadUrl.includes('mp4upload.com')) {
        referer = 'https://www.mp4upload.com/';
    } else if (downloadUrl.includes('pixeldrain.com')) {
        referer = 'https://pixeldrain.com/';
    } else if (downloadUrl.includes('buzzheavier.com')) {
        referer = 'https://buzzheavier.com/';
    } else if (downloadUrl.includes('krakenfiles.com')) {
        referer = 'https://krakenfiles.com/';
    }

    return new Promise((resolve, reject) => {
        let downloadedBytes = 0;
        let totalBytes = 0;
        let startTime = Date.now();
        let lastReportTime = Date.now();
        let fileStream = null;
        let isAborted = false;

        const cleanup = () => {
            isAborted = true;
            if (fileStream) {
                try {
                    fileStream.removeAllListeners('error');
                    fileStream.on('error', () => {});
                    fileStream.destroy();
                } catch (e) {}
                fileStream = null;
            }
            if (fs.existsSync(localTmpPath)) {
                try { fs.unlinkSync(localTmpPath); } catch (e) {}
            }
        };

        const requestUrl = (urlToFetch) => {
            const clientModule = urlToFetch.startsWith('http:') ? http : https;
            const req = clientModule.get(urlToFetch, {
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': referer,
                }
            }, (res) => {
                if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
                    let redirectUrl = res.headers.location;
                    if (redirectUrl.startsWith('/')) {
                        const u = new URL(urlToFetch);
                        redirectUrl = `${u.protocol}//${u.host}${redirectUrl}`;
                    }
                    return requestUrl(redirectUrl);
                }

                if (res.statusCode !== 200 && res.statusCode !== 206) {
                    cleanup();
                    return reject(new Error(`HTTP ${res.statusCode}: ${res.statusMessage}`));
                }

                totalBytes = parseInt(res.headers['content-length'] || '0', 10);
                const totalMb = totalBytes > 0 ? (totalBytes / (1024 * 1024)).toFixed(1) + ' MB' : 'Ukuran ?';

                fileStream = fs.createWriteStream(localTmpPath);
                fileStream.on('error', (err) => {
                    if (isAborted) return;
                    cleanup();
                    reject(err);
                });
                startTime = Date.now();
                lastReportTime = Date.now();

                res.on('data', (chunk) => {
                    if (isAborted) return;
                    downloadedBytes += chunk.length;
                    if (fileStream && !fileStream.destroyed && !fileStream.closed && fileStream.writable) {
                        try {
                            fileStream.write(chunk);
                        } catch (e) {}
                    }

                    const now = Date.now();
                    if (now - lastReportTime > 500 || (totalBytes > 0 && downloadedBytes === totalBytes)) {
                        lastReportTime = now;
                        const elapsedSec = Math.max(0.1, (now - startTime) / 1000);
                        const speedBps = downloadedBytes / elapsedSec;
                        const speedMb = (speedBps / (1024 * 1024)).toFixed(1);
                        const downMb = (downloadedBytes / (1024 * 1024)).toFixed(1);
                        const percent = totalBytes > 0 ? ((downloadedBytes / totalBytes) * 100).toFixed(0) : '?';

                        // Speed Watchdog: Deteksi kecepatan secara aktif dan otomatis ganti jika lambat
                        const minSpeedMb = options.minSpeedMb !== undefined ? options.minSpeedMb : MIN_DOWNLOAD_SPEED_MB;
                        const minSpeedBps = minSpeedMb * 1024 * 1024;
                        const checkSec = options.minSpeedCheckSec || SPEED_WATCHDOG_WAIT_SEC;

                        if (options.enableSpeedWatchdog && elapsedSec >= checkSec) {
                            if (speedBps < minSpeedBps && (totalBytes === 0 || downloadedBytes < totalBytes * 0.75)) {
                                isAborted = true;
                                res.removeAllListeners('data');
                                res.destroy();
                                req.destroy();
                                cleanup();
                                process.stdout.write('\n');
                                print(`         ${UI.gray}├─ ${UI.brightYellow}[SPEED WATCHDOG] Kecepatan terdeteksi lambat (${speedMb} MB/s < ${minSpeedMb.toFixed(1)} MB/s) pada detik ke-${Math.round(elapsedSec)}!${UI.reset}`);
                                print(`         ${UI.gray}│  ${UI.yellow}Menghentikan koneksi ini dan otomatis beralih ke sumber cadangan...${UI.reset}`);
                                return reject(new Error(`SPEED_THROTTLED (${speedMb} MB/s < ${minSpeedMb.toFixed(1)} MB/s)`));
                            }
                        }

                        let etaStr = '';
                        if (totalBytes > 0 && speedBps > 1024) {
                            const remBytes = totalBytes - downloadedBytes;
                            const etaSec = Math.max(0, Math.round(remBytes / speedBps));
                            if (etaSec >= 3600) {
                                const h = Math.floor(etaSec / 3600);
                                const m = Math.floor((etaSec % 3600) / 60);
                                const s = etaSec % 60;
                                etaStr = s > 0 ? `${h}h ${m}m ${s}s` : `${h}h ${m}m`;
                            } else if (etaSec >= 60) {
                                etaStr = `${Math.floor(etaSec / 60)}m ${etaSec % 60}s`;
                            } else {
                                etaStr = `${etaSec}s`;
                            }
                        }
                        const etaDisplay = etaStr ? ` ${UI.gray}| ETA: ${etaStr}${UI.reset}` : '';

                        process.stdout.write(`\r         ${UI.gray}│  Progres: ${UI.brightCyan}${downMb} MB / ${totalMb} (${percent}%)${UI.reset} ${UI.brightYellow}[${speedMb} MB/s]${UI.reset}${etaDisplay}   `);
                    }
                });

                res.on('end', () => {
                    if (isAborted) return;
                    if (fileStream) {
                        fileStream.end(() => {
                            process.stdout.write('\n');
                            try {
                                const finalMb = (downloadedBytes / (1024 * 1024)).toFixed(1);
                                print(`         ${UI.gray}├─ Menyimpan :${UI.reset} ${UI.yellow}Memindahkan file ke ${path.basename(destPath)}...${UI.reset}`);
                                if (fs.existsSync(destPath)) {
                                    try { fs.unlinkSync(destPath); } catch (e) {}
                                }
                                fs.copyFileSync(localTmpPath, destPath);
                                try { fs.unlinkSync(localTmpPath); } catch (e) {}
                                print(`         ${UI.gray}├─ Selesai   :${UI.reset} ${UI.brightGreen}Tersimpan di ${path.basename(destPath)} (${finalMb} MB)${UI.reset}`);
                                resolve(true);
                            } catch (err) {
                                cleanup();
                                return reject(err);
                            }
                        });
                    } else {
                        resolve(false);
                    }
                });

                res.on('error', (err) => {
                    cleanup();
                    reject(err);
                });
            });

            req.on('error', (err) => {
                cleanup();
                reject(err);
            });

            req.setTimeout(180000, () => {
                cleanup();
                req.destroy(new Error('Download timeout (180s)'));
            });
        };

        requestUrl(downloadUrl);
    });
}

async function monitorServerDownloads(episodeId, downloads) {
    const qualities = downloads.map(d => d.quality.toLowerCase());
    const startTime = Date.now();
    const maxTimeoutMs = 25 * 60 * 1000;
    let lastRenderLength = 0;

    while (Date.now() - startTime < maxTimeoutMs) {
        try {
            const res = await client.get('/download-progress', {
                params: {
                    episode_id: episodeId,
                    qualities: qualities.join(',')
                }
            });

            if (res.data && res.data.success) {
                const dlData = res.data.downloads || {};
                const parts = [];
                let completedCount = 0;
                let failedCount = 0;

                for (const q of qualities) {
                    const info = dlData[q];
                    const qLabel = q.toUpperCase();

                    if (!info) {
                        parts.push(`${UI.gray}[${qLabel}] Menghubungkan...${UI.reset}`);
                        continue;
                    }

                    const status = info.status || 'queued';
                    const pct = info.progress !== undefined ? Number(info.progress).toFixed(0) : '0';
                    const downMb = info.downloaded > 0 ? (info.downloaded / (1024 * 1024)).toFixed(1) : '0';
                    const totalMb = info.total > 0 ? (info.total / (1024 * 1024)).toFixed(1) : '?';

                    if (status === 'completed') {
                        completedCount++;
                        parts.push(`${UI.brightGreen}[${qLabel}] 100% (${downMb}MB)${UI.reset}`);
                    } else if (status === 'failed') {
                        failedCount++;
                        parts.push(`${UI.brightRed}[${qLabel}] Gagal${UI.reset}`);
                    } else if (status === 'queued') {
                        parts.push(`${UI.yellow}[${qLabel}] Antre...${UI.reset}`);
                    } else {
                        parts.push(`${UI.brightCyan}[${qLabel}] ${pct}% (${downMb}/${totalMb}MB)${UI.reset}`);
                    }
                }

                const rawLine = `         │  Progres Server: ${parts.join(' | ')}`;
                const cleanLen = rawLine.replace(/\x1b\[[0-9;]*m/g, '').length;
                const padSpaces = Math.max(0, lastRenderLength - cleanLen);
                process.stdout.write(`\r${rawLine}${' '.repeat(padSpaces)}`);
                lastRenderLength = cleanLen;

                if (completedCount + failedCount >= qualities.length && qualities.length > 0) {
                    process.stdout.write('\n');
                    return { completed: completedCount, failed: failedCount };
                }
            }
        } catch (pollErr) {
            // Abaikan kesalahan koneksi berkala
        }

        await sleep(1000);
    }

    process.stdout.write('\n');
    return { completed: 0, failed: qualities.length };
}

async function extractNekopoi(page, task, tabLabel, logFn) {
    const print = logFn || console.log;
    const capturedServers = new Map();
    let targetPage = page;
    let createdNewTargetPage = false;

    const checkAndAddUrl = (rawUrl) => {
        if (!rawUrl || typeof rawUrl !== 'string') return;
        let u = rawUrl.trim();
        if (u.startsWith('//')) u = 'https:' + u;
        if (!u.startsWith('http')) return;

        const isSkip = SKIP_HOSTS.some(h => u.toLowerCase().includes(h));
        if (isSkip) return;

        if (/playmogo\.com\/e\/[a-z0-9]+/i.test(u) || /streampoi\.com\/embed-[a-z0-9_]+\.html/i.test(u) || /nekodrive|streamtape\.com\/e\/|dood\.|filelions|hxfile/i.test(u)) {
            let name = 'Nekopoi Stream';
            try {
                const parsed = new URL(u);
                name = parsed.hostname.replace(/^www\./, '');
            } catch (e) {}
            if (!capturedServers.has(u)) {
                capturedServers.set(u, { name, url: u });
            }
        }
    };

    const onFrameNav = (frame) => {
        try { checkAndAddUrl(frame.url()); } catch (e) {}
    };
    const onResponse = (res) => {
        try { checkAndAddUrl(res.url()); } catch (e) {}
    };

    try {
        let targetUrl = task.url;
        if (!targetUrl) {
            print(`         ${UI.gray}├─ Pencarian :${UI.reset} ${UI.gray}Mencari link anime di Nekopoi...${UI.reset}`);
            targetUrl = await resolveNekopoiUrl(page, task.anime_title, task.episode_number, task.anime_slug);
        }

        if (!targetUrl) {
            print(`         ${UI.gray}└─ Hasil     :${UI.reset} ${UI.statusBadge('FAILED')} Judul/episode tidak ditemukan`);
            await submitResult({
                task_id: task.task_id,
                source: 'nekopoi',
                episode_id: task.episode_id,
                status: 'unavailable',
            });
            return { notFound: true, servers: [] };
        }

        print(`         ${UI.gray}├─ Target    :${UI.reset} ${UI.magenta}${targetUrl}${UI.reset}`);

        const browser = page.browser();
        const targetPage = page;

        // Navigasi ke episode target hanya jika belum di halaman tersebut
        if (targetPage.url() !== targetUrl) {
            print(`         ${UI.gray}├─ Navigasi  :${UI.reset} ${UI.gray}Membuka ${targetUrl}...${UI.reset}`);
            try {
                const navRes = await targetPage.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 25000 });
                print(`         ${UI.gray}├─ Nav Status:${UI.reset} ${UI.gray}HTTP ${navRes ? navRes.status() : 'null'} -> ${targetPage.url()}${UI.reset}`);
                await checkAndBypassCloudflare(targetPage, print);
            } catch (navErr) {
                print(`         ${UI.gray}├─ Nav Error :${UI.reset} ${UI.brightRed}${navErr.message}${UI.reset}`);
            }
        } else {
            print(`         ${UI.gray}├─ Navigasi  :${UI.reset} ${UI.brightGreen}Halaman episode sudah siap${UI.reset}`);
            await checkAndBypassCloudflare(targetPage, print);
        }

        // Safeguard jika halaman sempat terlempar ke about:blank akibat script iklan nekopoi
        if (targetPage.url() === 'about:blank' || !targetPage.url().includes('nekopoi.care')) {
            print(`         ${UI.gray}├─ Nav Retry :${UI.reset} ${UI.yellow}Mencegah redirect liar (about:blank), membuka ulang target...${UI.reset}`);
            try {
                const retryRes = await targetPage.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 25000 });
                print(`         ${UI.gray}├─ Nav Status:${UI.reset} ${UI.gray}Status akhir -> ${targetPage.url()}${UI.reset}`);
                await checkAndBypassCloudflare(targetPage, print);
            } catch (retryErr) {}
        }

        targetPage.on('framenavigated', onFrameNav);
        targetPage.on('response', onResponse);

        // Tunggu maksimal 8 detik untuk player video jika belum tertangkap
        if (capturedServers.size === 0) {
            await targetPage.waitForSelector('#nk-stream-1 iframe, #nk-stream-2 iframe, #nk-stream-3 iframe, .nk-player-frame iframe, #nk-player iframe, .entry-content iframe', { timeout: 8000 }).catch(() => {});
        }

        // Ekstraksi langsung dari DOM
        try {
            const rawIframes = await targetPage.evaluate(() => {
                const iframes = document.querySelectorAll('#nk-stream-1 iframe, #nk-stream-2 iframe, #nk-stream-3 iframe, .nk-player-frame iframe, #nk-player iframe, .entry-content iframe');
                const list = [];
                for (const f of iframes) {
                    const src = f.src || f.getAttribute('data-src') || f.getAttribute('data-lazy-src') || f.getAttribute('data-lzl-src') || '';
                    if (src) list.push(src);
                }
                return list;
            }).catch(() => []);
            for (const s of rawIframes) {
                checkAndAddUrl(s);
            }
        } catch (e) {}

        // Ekstraksi fallback dari konten HTML
        try {
            const html = await targetPage.content().catch(() => '');
            const matches = html.match(/(https?:\/\/(?:playmogo\.com\/e\/[a-z0-9]+|streampoi\.com\/embed-[a-z0-9_]+\.html))/gi) || [];
            for (const s of matches) {
                checkAndAddUrl(s);
            }
        } catch (e) {}

        // Ekstraksi kotak download (UNDUH) Nekopoi (Multi-Resolusi 3-4 Kualitas)
        const resolvedDownloads = [];
        const isServerDownload = IS_SERVER_DOWNLOAD || !VIDEO_STORAGE_DIR;
        let downloadRows = [];

        try {
            if (targetPage.url() !== targetUrl || targetPage.url() === 'about:blank') {
                await targetPage.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => {});
            }
            await targetPage.waitForSelector('.nk-download-row, .nk-download-section, .nk-download-box', { timeout: 8000 }).catch(() => null);

            downloadRows = await targetPage.evaluate(() => {
                const rows = [];
                const elRows = document.querySelectorAll('.nk-download-row, .nk-download-section .nk-download-row, .nk-download-box .nk-download-row');
                for (const r of elRows) {
                    const nameEl = r.querySelector('.nk-download-name');
                    const nameText = nameEl ? nameEl.innerText.trim() : '';
                    const qMatch = nameText.match(/\[(4K|2K|1080p|720p|480p|360p)\]/i) || nameText.match(/\b(4K|2K|1080p|720p|480p|360p)\b/i);
                    const quality = qMatch ? qMatch[1].toLowerCase() : '';

                    const links = {};
                    const anchors = r.querySelectorAll('.nk-download-links a');
                    for (const a of anchors) {
                        const host = (a.innerText || '').trim();
                        const href = a.href || a.getAttribute('href') || '';
                        if (host && href) {
                            links[host] = href;
                        }
                    }
                    if (Object.keys(links).length > 0) {
                        rows.push({ quality, name: nameText, links });
                    }
                }
                return rows;
            }).catch(() => []);

            if (downloadRows.length > 0) {
                print(`         ${UI.gray}├─ Unduhan   :${UI.reset} ${UI.gray}Ditemukan ${downloadRows.length} opsi kualitas video${UI.reset}`);

                // Normalisasi kualitas
                for (const r of downloadRows) {
                    r.quality = (r.quality || '720p').toLowerCase();
                }

                // Cek apakah ada 4K atau 2K
                const hasUltra = downloadRows.some(r => /4k|2k|2160p|1440p/i.test(r.quality));
                const targetLimit = hasUltra ? 4 : 3;

                const qRank = { '4k': 6, '2160p': 6, '2k': 5, '1440p': 5, '1080p': 4, '720p': 3, '480p': 2, '360p': 1 };
                downloadRows.sort((a, b) => (qRank[b.quality] || 0) - (qRank[a.quality] || 0));

                // Ambil hingga targetLimit baris kualitas unik
                const targetRows = [];
                const seenQualities = new Set();
                for (const r of downloadRows) {
                    if (!seenQualities.has(r.quality)) {
                        seenQualities.add(r.quality);
                        targetRows.push(r);
                        if (targetRows.length >= targetLimit) break;
                    }
                }

                print(`         ${UI.gray}├─ Target Q  :${UI.reset} ${UI.brightCyan}${targetRows.map(r => r.quality.toUpperCase()).join(', ')} (${targetRows.length} resolusi)${UI.reset}`);

                const baseSlug = task.anime_slug || (task.anime_title || 'anime').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

                for (let idx = 0; idx < targetRows.length; idx++) {
                    const row = targetRows[idx];
                    const rowQ = row.quality || '720p';
                    const isDefault = (idx === 0);
                    const fname = `${baseSlug}-ep${task.episode_number}-${rowQ}.mp4`;

                    const pixeldrainOuo = findOuoLink(row.links, /pixel/i);
                    const mp4uploadOuo  = findOuoLink(row.links, /mp4upload/i);
                    const mirrorOuo     = findOuoLink(row.links, /mirror/i);

                    const downloadCandidates = [];

                    // 1. Prioritas Utama: Coba Pixeldrain (Kecepatan Sangat Tinggi ~10-30+ MB/s, Unthrottled)
                    if (pixeldrainOuo) {
                        print(`         ${UI.gray}├─ Resolving :${UI.reset} ${UI.gray}Bypass ouo.io Pixeldrain [${rowQ.toUpperCase()}]...${UI.reset}`);
                        const resolvedPixel = await resolveOuoLink(browser, pixeldrainOuo, print);
                        if (resolvedPixel && resolvedPixel.includes('pixeldrain.com')) {
                            const mId = resolvedPixel.match(/pixeldrain\.com\/(?:u|d)\/([a-zA-Z0-9_-]+)/);
                            if (mId) {
                                const fileId = mId[1];
                                const streamApi = `https://pixeldrain.com/api/file/${fileId}`;
                                const downloadApi = `https://pixeldrain.com/api/file/${fileId}?download`;
                                capturedServers.set(streamApi, {
                                    name: `Pixeldrain [${rowQ.toUpperCase()}]`,
                                    url: streamApi,
                                });
                                downloadCandidates.push({
                                    url: downloadApi,
                                    source: 'Pixeldrain (Super Cepat)',
                                    priority: 1
                                });
                                print(`         ${UI.gray}├─ Direct URL:${UI.reset} ${UI.brightGreen}Pixeldrain [${rowQ.toUpperCase()}] berhasil didapatkan (Prioritas Utama)${UI.reset}`);
                            }
                        }
                    }

                    // 2. Ambil Mirror [ouo] (mirrored.to): ekstrak Pixeldrain, Buzzheavier, KrakenFiles, Mp4Upload, VoeSx
                    if (mirrorOuo) {
                        print(`         ${UI.gray}├─ Resolving :${UI.reset} ${UI.gray}Bypass ouo.io Mirror [${rowQ.toUpperCase()}]...${UI.reset}`);
                        const resolvedMirror = await resolveOuoLink(browser, mirrorOuo, print);
                        if (resolvedMirror) {
                            if (resolvedMirror.includes('pixeldrain.com')) {
                                const mId = resolvedMirror.match(/pixeldrain\.com\/(?:u|d)\/([a-zA-Z0-9_-]+)/);
                                if (mId) {
                                    const fileId = mId[1];
                                    const streamApi = `https://pixeldrain.com/api/file/${fileId}`;
                                    const downloadApi = `https://pixeldrain.com/api/file/${fileId}?download`;
                                    capturedServers.set(streamApi, {
                                        name: `Pixeldrain [${rowQ.toUpperCase()}]`,
                                        url: streamApi,
                                    });
                                    downloadCandidates.push({
                                        url: downloadApi,
                                        source: 'Pixeldrain (via Mirror)',
                                        priority: 1
                                    });
                                    print(`         ${UI.gray}├─ Direct URL:${UI.reset} ${UI.brightGreen}Pixeldrain [${rowQ.toUpperCase()}] berhasil didapatkan (via Mirror)${UI.reset}`);
                                }
                            } else if (resolvedMirror.includes('mirrored.to')) {
                                print(`         ${UI.gray}├─ Mirror Host:${UI.reset} ${UI.gray}Mengekstrak host dari mirrored.to [${rowQ.toUpperCase()}]...${UI.reset}`);
                                const mirroredHosts = await resolveMirroredHosts(browser, resolvedMirror, print);
                                for (const h of mirroredHosts) {
                                    const hUrl = h.url;
                                    if (/pixeldrain\.com/i.test(hUrl)) {
                                        const mId = hUrl.match(/pixeldrain\.com\/(?:u|d)\/([a-zA-Z0-9_-]+)/);
                                        if (mId) {
                                            const fileId = mId[1];
                                            const streamApi = `https://pixeldrain.com/api/file/${fileId}`;
                                            const downloadApi = `https://pixeldrain.com/api/file/${fileId}?download`;
                                            capturedServers.set(streamApi, {
                                                name: `Pixeldrain [${rowQ.toUpperCase()}]`,
                                                url: streamApi,
                                            });
                                            downloadCandidates.push({
                                                url: downloadApi,
                                                source: 'Pixeldrain (Mirrored.to)',
                                                priority: 1
                                            });
                                            print(`         ${UI.gray}├─ Direct URL:${UI.reset} ${UI.brightGreen}Pixeldrain [${rowQ.toUpperCase()}] didapatkan dari Mirrored.to${UI.reset}`);
                                        }
                                    } else if (/buzzheavier\.com/i.test(hUrl) || /krakenfiles\.com/i.test(hUrl)) {
                                        // Catatan: KrakenFiles & Buzzheavier adalah landing page HTML, bukan direct MP4 stream
                                        print(`         ${UI.gray}├─ File Host :${UI.reset} ${UI.gray}${h.host} [${rowQ.toUpperCase()}] ditemukan di Mirrored.to (Halaman Web, bukan Direct MP4)${UI.reset}`);
                                    } else if (/mp4upload\.com/i.test(hUrl)) {
                                        const mMp4 = hUrl.match(/mp4upload\.com\/(?:embed-)?([a-zA-Z0-9_-]+)/);
                                        if (mMp4) {
                                            const embedUrl = `https://www.mp4upload.com/embed-${mMp4[1]}.html`;
                                            capturedServers.set(embedUrl, {
                                                name: `Mp4Upload [${rowQ.toUpperCase()}]`,
                                                url: embedUrl,
                                            });
                                            const directMp4 = await resolveMp4UploadDirect(embedUrl);
                                            if (directMp4) {
                                                downloadCandidates.push({
                                                    url: directMp4,
                                                    source: 'Mp4Upload (via Mirror)',
                                                    priority: 2
                                                });
                                            }
                                            print(`         ${UI.gray}├─ Direct URL:${UI.reset} ${UI.brightGreen}Mp4Upload [${rowQ.toUpperCase()}] didapatkan dari Mirrored.to${UI.reset}`);
                                        }
                                    } else if (/voe\.sx/i.test(hUrl)) {
                                        const mVoe = hUrl.match(/voe\.sx\/(?:e\/)?([a-zA-Z0-9_-]+)/i);
                                        const embedUrl = mVoe ? `https://voe.sx/e/${mVoe[1]}` : hUrl;
                                        capturedServers.set(embedUrl, {
                                            name: `VoeSx [${rowQ.toUpperCase()}]`,
                                            url: embedUrl,
                                        });
                                        print(`         ${UI.gray}├─ Server MP4 :${UI.reset} ${UI.brightGreen}VoeSx [${rowQ.toUpperCase()}] didapatkan dari Mirrored.to${UI.reset}`);
                                    }
                                }
                            } else if (resolvedMirror.includes('mp4upload.com')) {
                                const mMp4 = resolvedMirror.match(/mp4upload\.com\/(?:embed-)?([a-zA-Z0-9_-]+)/);
                                if (mMp4) {
                                    const embedUrl = `https://www.mp4upload.com/embed-${mMp4[1]}.html`;
                                    capturedServers.set(embedUrl, {
                                        name: `Mp4Upload [${rowQ.toUpperCase()}]`,
                                        url: embedUrl,
                                    });
                                    const directMp4 = await resolveMp4UploadDirect(embedUrl);
                                    if (directMp4) {
                                        downloadCandidates.push({
                                            url: directMp4,
                                            source: 'Mp4Upload (via Mirror)',
                                            priority: 2
                                        });
                                    }
                                    print(`         ${UI.gray}├─ Embed URL :${UI.reset} ${UI.brightGreen}Mp4Upload [${rowQ.toUpperCase()}] berhasil didapatkan (via Mirror)${UI.reset}`);
                                }
                            }
                        }
                    }

                    // 3. Cadangan: Coba Mp4Upload (Embed Stream Server & Cadangan Unduh)
                    if (mp4uploadOuo) {
                        print(`         ${UI.gray}├─ Resolving :${UI.reset} ${UI.gray}Bypass ouo.io Mp4Upload [${rowQ.toUpperCase()}]...${UI.reset}`);
                        const resolvedMp4 = await resolveOuoLink(browser, mp4uploadOuo, print);
                        if (resolvedMp4 && resolvedMp4.includes('mp4upload.com')) {
                            const mMp4 = resolvedMp4.match(/mp4upload\.com\/(?:embed-)?([a-zA-Z0-9_-]+)/);
                            if (mMp4) {
                                const embedUrl = `https://www.mp4upload.com/embed-${mMp4[1]}.html`;
                                capturedServers.set(embedUrl, {
                                    name: `Mp4Upload [${rowQ.toUpperCase()}]`,
                                    url: embedUrl,
                                });
                                print(`         ${UI.gray}├─ Embed URL :${UI.reset} ${UI.brightGreen}Mp4Upload [${rowQ.toUpperCase()}] berhasil didapatkan${UI.reset}`);

                                const directMp4 = await resolveMp4UploadDirect(embedUrl);
                                if (directMp4) {
                                    downloadCandidates.push({
                                        url: directMp4,
                                        source: 'Mp4Upload',
                                        priority: 2
                                    });
                                    print(`         ${UI.gray}├─ Direct MP4:${UI.reset} ${UI.gray}Mp4Upload [${rowQ.toUpperCase()}] stream direct didapatkan (Cadangan)${UI.reset}`);
                                }
                            }
                        }
                    }

                    // Urutkan kandidat berdasarkan prioritas kecepatan terbaik
                    downloadCandidates.sort((a, b) => a.priority - b.priority);
                    const bestCandidate = downloadCandidates[0] || null;
                    const directDownloadUrl = bestCandidate ? bestCandidate.url : null;
                    const directDownloadSource = bestCandidate ? bestCandidate.source : '';

                    if (DOWNLOAD_MODE && downloadCandidates.length > 0) {
                        if (isServerDownload) {
                            // Mode di luar rumah / server-side download
                            resolvedDownloads.push({
                                quality: rowQ,
                                direct_download_url: directDownloadUrl,
                                local_file: fname,
                                is_default: isDefault,
                            });
                            print(`         ${UI.gray}├─ Delegasi  :${UI.reset} ${UI.brightCyan}[${rowQ.toUpperCase()}] Tugas unduh diserahkan ke server CasaOS (via ${directDownloadSource})${isDefault ? ' (Default)' : ''}${UI.reset}`);
                        } else if (VIDEO_STORAGE_DIR) {
                            // Mode lokal rumah: simpan langsung ke Y:\
                            const destPath = path.join(VIDEO_STORAGE_DIR, fname);
                            if (fs.existsSync(destPath) && fs.statSync(destPath).size > 5 * 1024 * 1024) {
                                print(`         ${UI.gray}├─ Video Admin:${UI.reset} ${UI.brightGreen}[${rowQ.toUpperCase()}] File sudah ada di Y:\\${fname}${isDefault ? ' (Default)' : ''}${UI.reset}`);
                                resolvedDownloads.push({
                                    quality: rowQ,
                                    local_file: fname,
                                    is_default: isDefault,
                                });
                            } else {
                                let downloadSuccess = false;
                                for (let cIdx = 0; cIdx < downloadCandidates.length; cIdx++) {
                                    const cand = downloadCandidates[cIdx];
                                    const hasAlternative = cIdx < downloadCandidates.length - 1;
                                    try {
                                        print(`         ${UI.gray}├─ Unduh MP4 :${UI.reset} ${UI.yellow}[${rowQ.toUpperCase()}] Mengunduh via ${cand.source} (Target: >${MIN_DOWNLOAD_SPEED_MB} MB/s)...${UI.reset}`);
                                        await downloadDirectVideo(cand.url, destPath, print, {
                                            enableSpeedWatchdog: hasAlternative,
                                            minSpeedMb: MIN_DOWNLOAD_SPEED_MB,
                                            minSpeedCheckSec: SPEED_WATCHDOG_WAIT_SEC
                                        });
                                        resolvedDownloads.push({
                                            quality: rowQ,
                                            local_file: fname,
                                            is_default: isDefault,
                                        });
                                        print(`         ${UI.gray}├─ Selesai   :${UI.reset} ${UI.brightGreen}[${rowQ.toUpperCase()}] Tersimpan di ${fname}${isDefault ? ' (Default)' : ''}${UI.reset}`);
                                        downloadSuccess = true;
                                        break;
                                    } catch (dlErr) {
                                        if (dlErr.message && dlErr.message.includes('SPEED_THROTTLED')) {
                                            print(`         ${UI.gray}├─ Auto-Switch:${UI.reset} ${UI.brightMagenta}[${rowQ.toUpperCase()}] Mengalihkan ke sumber alternatif berikutnya...${UI.reset}`);
                                        } else {
                                            print(`         ${UI.gray}├─ Unduh MP4 :${UI.reset} ${UI.brightRed}[${rowQ.toUpperCase()}] Gagal via ${cand.source} (${dlErr.message})${UI.reset}`);
                                            if (hasAlternative) {
                                                print(`         ${UI.gray}├─ Fallback  :${UI.reset} ${UI.brightYellow}Beralih ke sumber alternatif berikutnya...${UI.reset}`);
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            } else {
                print(`         ${UI.gray}├─ Unduhan   :${UI.reset} ${UI.gray}Kotak download tidak ditemukan (${targetPage.url()})${UI.reset}`);
            }
        } catch (dlParseErr) {
            print(`         ${UI.gray}├─ Info      :${UI.reset} ${UI.gray}Gagal membaca kotak download (${dlParseErr.message})${UI.reset}`);
        }

        return {
            notFound: false,
            downloads: resolvedDownloads,
            download_on_server: isServerDownload && resolvedDownloads.length > 0,
            servers: Array.from(capturedServers.values())
        };
    } catch (err) {
        print(`         ${UI.gray}├─ Error     :${UI.reset} ${UI.brightRed}${err.message}${UI.reset}`);
        return { notFound: false, servers: Array.from(capturedServers.values()) };
    } finally {
        if (targetPage) {
            targetPage.off('framenavigated', onFrameNav);
            targetPage.off('response', onResponse);
        }
    }
}

async function processQueue(browser, queue, tabLabel) {
    let completed = 0;
    let page = null;

    try {
        // 1. Bersihkan semua tab liar / popup yang mungkin tersisa
        await cleanupStrayTabs(browser);

        // 2. Gunakan tab browser yang sudah ada jika tersedia, hindari membuat tab baru
        const existingPages = await browser.pages();
        const availablePage = existingPages.find(p => !activeWorkerPages.has(p));
        if (availablePage) {
            page = availablePage;
        } else {
            page = await browser.newPage();
        }
        activeWorkerPages.add(page);
        await page.setViewport({ width: 1280, height: 720 });
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');

        page.on('popup', async (popup) => {
            try {
                await sleep(200);
                await popup.close().catch(() => {});
            } catch (e) {}
        });

        // 3. Kebal dari popup iklan liar secara global & anti history hijacking
        await page.evaluateOnNewDocument(() => {
            window.open = function() { return null; };
            window.alert = function() {};
            window.confirm = function() { return true; };
            window.prompt = function() { return null; };
            try {
                Object.defineProperty(window.history, 'back', {
                    value: function() {},
                    writable: false,
                    configurable: false
                });
                Object.defineProperty(window.history, 'go', {
                    value: function() {},
                    writable: false,
                    configurable: false
                });
                Object.defineProperty(window.history, 'forward', {
                    value: function() {},
                    writable: false,
                    configurable: false
                });
            } catch (e) {
                window.history.back = function() {};
                window.history.go = function() {};
                window.history.forward = function() {};
            }
        });

        // 4. Pastikan hanya tab resmi ini yang hidup
        await cleanupStrayTabs(browser);

        for (let i = 0; i < queue.length; i++) {
            const task = queue[i];
            await cleanupStrayTabs(browser);

            // Fast auto-prune jika range Kuramanime anime ini sudah diketahui dan episode di luar range
            if (task.source === 'kuramanime') {
                const range = kuramaAnimeRangeCache.get(task.anime_title);
                if (range) {
                    const isTooLow = range.minEp !== null && task.episode_number < range.minEp;
                    const isTooHigh = range.maxEp !== null && task.episode_number > range.maxEp;
                    if (isTooLow || isTooHigh) {
                        const batchSkipped = [task];
                        const remaining = [];
                        for (let j = i + 1; j < queue.length; j++) {
                            const next = queue[j];
                            if (next.source === 'kuramanime' && next.anime_title === task.anime_title) {
                                const nextLow = range.minEp !== null && next.episode_number < range.minEp;
                                const nextHigh = range.maxEp !== null && next.episode_number > range.maxEp;
                                if (nextLow || nextHigh) {
                                    batchSkipped.push(next);
                                    continue;
                                }
                            }
                            remaining.push(next);
                        }

                        queue.splice(i + 1, queue.length - (i + 1), ...remaining);

                        Promise.all(batchSkipped.map(t => submitResult({
                            task_id: t.task_id,
                            source: 'kuramanime',
                            episode_id: t.episode_id,
                            status: 'unavailable',
                            min_episode: range.minEp,
                            max_episode: range.maxEp
                        }))).catch(() => {});

                        const numStr = String(i + 1).padStart(2, '0');
                        const totalStr = String(queue.length).padStart(2, '0');
                        const progress = `${UI.gray}[${UI.brightWhite}${numStr}/${totalStr}${UI.gray}]${UI.reset}`;
                        const currentTabLabel = (tabLabel === 'TAB-WORKER' || tabLabel === 'TAB-1')
                            ? 'TAB-KURAMA'
                            : tabLabel;
                        const badge = UI.tabBadge(currentTabLabel);
                        const extraNote = batchSkipped.length > 1 ? ` & ${batchSkipped.length - 1} episode lainnya` : '';
                        console.log(`${UI.time()} ${badge} ${progress} ${UI.brightWhite}${UI.bold}${task.anime_title}${UI.reset} ${UI.brightYellow}(Ep ${task.episode_number}${extraNote})${UI.reset}`);
                        console.log(`         ${UI.gray}└─ Status    :${UI.reset} ${UI.brightYellow}[LEWATI]${UI.reset} ${UI.gray}Di luar rentang rilis Kuramanime (Tersedia: Ep ${range.minEp} s/d ${range.maxEp})${UI.reset}\n`);
                        await sleep(200);
                        continue;
                    }
                }
            }

            const numStr = String(i + 1).padStart(2, '0');
            const totalStr = String(queue.length).padStart(2, '0');
            const progress = `${UI.gray}[${UI.brightWhite}${numStr}/${totalStr}${UI.gray}]${UI.reset}`;
            const currentTabLabel = (tabLabel === 'TAB-WORKER' || tabLabel === 'TAB-1')
                ? (task.source === 'nekopoi' ? 'TAB-NEKOPOI' : 'TAB-KURAMA')
                : tabLabel;
            const badge = UI.tabBadge(currentTabLabel);

            const headerLog = `${UI.time()} ${badge} ${progress} ${UI.brightWhite}${UI.bold}${task.anime_title}${UI.reset} ${UI.brightYellow}(Ep ${task.episode_number})${UI.reset}`;
            console.log(headerLog);
            const logs = [headerLog];
            const logFn = (msg) => {
                logs.push(msg);
                console.log(msg);
            };

            try {
                if (task.source === 'kuramanime') {
                    const result = await extractKurama(page, task, currentTabLabel, logFn);
                    if (result && result.url) {
                        const shortUrl = result.url.length > 55 ? result.url.substring(0, 52) + '...' : result.url;
                        logs.push(`         ${UI.gray}├─ Stream    :${UI.reset} ${UI.brightGreen}Kuramadrive ${result.quality}${UI.reset} ${UI.gray}(${shortUrl})${UI.reset}`);
                        
                        const ok = await submitResult({
                            task_id: task.task_id,
                            source: 'kuramanime',
                            episode_id: task.episode_id,
                            url: result.url,
                            quality: result.quality,
                        });
                        if (ok) {
                            logs.push(`         ${UI.gray}└─ Status    :${UI.reset} ${UI.statusBadge('SUCCESS')} Disimpan ke database Nipnime`);
                            completed++;
                        } else {
                            logs.push(`         ${UI.gray}└─ Status    :${UI.reset} ${UI.statusBadge('FAILED')} Gagal disetor ke server`);
                        }
                    } else if (!result || !result.skipped) {
                        logs.push(`         ${UI.gray}└─ Status    :${UI.reset} ${UI.statusBadge('FAILED')} Stream Kuramadrive tidak ditemukan`);
                    }

                    if (result && result.isAnimeUnavailable) {
                        const skippedOthers = [];
                        const remaining = [];
                        for (let j = i + 1; j < queue.length; j++) {
                            const next = queue[j];
                            if (next.source === task.source && next.anime_id === task.anime_id) {
                                skippedOthers.push(next);
                            } else {
                                remaining.push(next);
                            }
                        }
                        queue.splice(i + 1, queue.length - (i + 1), ...remaining);
                        Promise.all(skippedOthers.map(t => submitResult({
                            task_id: t.task_id,
                            source: t.source,
                            episode_id: t.episode_id,
                            status: 'unavailable',
                        }))).catch(() => {});
                        if (skippedOthers.length > 0) {
                            logs.push(`         ${UI.gray}└─ Auto-Skip :${UI.reset} ${UI.brightYellow}Ep 1 Belum Tersedia di sumber -> ${skippedOthers.length} episode lainnya otomatis dilewati${UI.reset}`);
                        }
                    }
                } else if (task.source === 'nekopoi') {
                    const result = await extractNekopoi(page, task, currentTabLabel, logFn);
                    const servers = (result && result.servers) ? result.servers : [];
                    const downloads = (result && result.downloads) ? result.downloads : [];
                    const downloadOnServer = !!(result && result.download_on_server);

                    if (downloads.length > 0 || servers.length > 0) {
                        if (downloads.length > 0) {
                            const dlSummary = downloads.map(d => `${d.quality.toUpperCase()}${d.is_default ? ' (Default)' : ''}`).join(', ');
                            if (downloadOnServer) {
                                logs.push(`         ${UI.gray}├─ Server DL :${UI.reset} ${UI.brightCyan}${downloads.length} resolusi diserahkan -> Server CasaOS mengunduh di latar belakang (${dlSummary})${UI.reset}`);
                            } else {
                                logs.push(`         ${UI.gray}├─ Video Admin:${UI.reset} ${UI.brightGreen}${downloads.length} resolusi tersimpan di Y:\\ (${dlSummary})${UI.reset}`);
                            }
                        }
                        if (servers.length > 0) {
                            const serverNames = servers.map(s => s.name).join(', ');
                            logs.push(`         ${UI.gray}├─ Cadangan  :${UI.reset} ${UI.brightMagenta}${servers.length} stream server${UI.reset} ${UI.gray}(${serverNames})${UI.reset}`);
                        }

                        const ok = await submitResult({
                            task_id: task.task_id,
                            source: 'nekopoi',
                            episode_id: task.episode_id,
                            downloads: downloads,
                            download_on_server: downloadOnServer,
                            download_status: (DOWNLOAD_MODE && downloads.length === 0) ? 'no_download' : null,
                            servers: servers,
                        });
                        if (ok) {
                            if (downloadOnServer && downloads.length > 0) {
                                console.log(`         ${UI.gray}├─ Monitor   :${UI.reset} ${UI.yellow}Memantau persentase unduhan server CasaOS...${UI.reset}`);
                                const dlStats = await monitorServerDownloads(task.episode_id, downloads);
                                if (dlStats.completed > 0) {
                                    logs.push(`         ${UI.gray}├─ Selesai DL:${UI.reset} ${UI.brightGreen}${dlStats.completed}/${downloads.length} resolusi sukses tersimpan di server CasaOS${UI.reset}`);
                                }
                            }
                            logs.push(`         ${UI.gray}└─ Status    :${UI.reset} ${UI.statusBadge('SUCCESS')} Disimpan ke database Nipnime`);
                            completed++;
                        } else {
                            logs.push(`         ${UI.gray}└─ Status    :${UI.reset} ${UI.statusBadge('FAILED')} Gagal disetor ke server`);
                        }
                    } else if (!result || !result.notFound) {
                        if (DOWNLOAD_MODE) {
                            await submitResult({
                                task_id: task.task_id,
                                source: 'nekopoi',
                                episode_id: task.episode_id,
                                download_status: 'no_download',
                                status: 'no_download',
                            });
                        }
                        logs.push(`         ${UI.gray}└─ Status    :${UI.reset} ${UI.statusBadge('FAILED')} Stream & file video tidak ditemukan`);
                    }
                }
            } catch (itemErr) {
                const errMsg = `         ${UI.gray}└─ Error     :${UI.reset} ${UI.brightRed}${itemErr.message}${UI.reset}`;
                logs.push(errMsg);
                console.log(errMsg);
            }

            console.log('');
            const wasSkipped = logs.some(l => l.includes('[LEWATI]'));
            await sleep(wasSkipped ? 200 : 1500);
            await cleanupStrayTabs(browser);
        }
    } catch (err) {
        console.log(`${UI.time()} ${UI.brightRed}[FATAL ${tabLabel}]${UI.reset} ${err.message}`);
    } finally {
        if (page) {
            activeWorkerPages.delete(page);
            try { await page.close(); } catch (e) {}
        }
    }

    return completed;
}

let hasAppliedCliPageOnce = false;

function loadCatalogState() {
    const p = path.join(__dirname, 'catalog_state.json');
    let state = { kurama_page: 1, kurama_movie_page: 1, neko_page: 1 };
    if (fs.existsSync(p)) {
        try { state = Object.assign(state, JSON.parse(fs.readFileSync(p, 'utf8'))); } catch (e) {}
    }
    if (!hasAppliedCliPageOnce) {
        if (args.includes('--reset-page')) {
            state.kurama_page = 1;
            state.kurama_movie_page = 1;
            state.neko_page = 1;
        }
        const cliNekoPage = getArg('neko-page', getArg('page'));
        const cliKuramaPage = getArg('kurama-page', getArg('page'));
        const cliMoviePage = getArg('movie-page');
        if (cliNekoPage !== undefined) state.neko_page = Math.max(1, parseInt(cliNekoPage, 10));
        if (cliKuramaPage !== undefined) state.kurama_page = Math.max(1, parseInt(cliKuramaPage, 10));
        if (cliMoviePage !== undefined) state.kurama_movie_page = Math.max(1, parseInt(cliMoviePage, 10));
        hasAppliedCliPageOnce = true;
    }
    return state;
}

function saveCatalogState(updates) {
    const p = path.join(__dirname, 'catalog_state.json');
    let diskState = { kurama_page: 1, kurama_movie_page: 1, neko_page: 1 };
    if (fs.existsSync(p)) {
        try {
            const raw = fs.readFileSync(p, 'utf8');
            if (raw && raw.trim()) {
                diskState = Object.assign(diskState, JSON.parse(raw));
            }
        } catch (e) {}
    }
    // Partial merge: hanya perbarui field yang dikirim agar worker paralel (Kurama vs Neko) tidak saling menimpa
    if (updates && typeof updates === 'object') {
        Object.assign(diskState, updates);
    }
    try {
        fs.writeFileSync(p, JSON.stringify(diskState, null, 2), 'utf8');
    } catch (e) {
        console.error('Gagal menyimpan catalog_state.json:', e.message);
    }
    return diskState;
}

async function scanAndVerifyCatalogBatch(browser, sourceMode) {
    let verifiedTasks = [];
    let page = null;

    try {
        const existingPages = await browser.pages();
        const availablePage = existingPages.find(p => !activeWorkerPages.has(p));
        if (availablePage) {
            page = availablePage;
        } else {
            page = await browser.newPage();
        }
        activeWorkerPages.add(page);
        await page.setViewport({ width: 1280, height: 720 });
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
        page.on('popup', async (popup) => {
            try {
                await sleep(200);
                await popup.close().catch(() => {});
            } catch (e) {}
        });

        await page.evaluateOnNewDocument(() => {
            window.open = function() { return null; };
            window.alert = function() {};
            window.confirm = function() { return true; };
            window.prompt = function() { return null; };
            try {
                Object.defineProperty(window.history, 'back', {
                    value: function() {},
                    writable: false,
                    configurable: false
                });
                Object.defineProperty(window.history, 'go', {
                    value: function() {},
                    writable: false,
                    configurable: false
                });
                Object.defineProperty(window.history, 'forward', {
                    value: function() {},
                    writable: false,
                    configurable: false
                });
            } catch (e) {
                window.history.back = function() {};
                window.history.go = function() {};
                window.history.forward = function() {};
            }
        });
        await cleanupStrayTabs(browser);

        // 1. Pindaian Katalog Kuramanime (Quick/Finished)
        if (sourceMode === 'kurama' || sourceMode === 'all') {
            const kuramaTarget = (sourceMode === 'all') ? Math.ceil(BATCH_LIMIT / 2) : BATCH_LIMIT;
            let kuramaScanned = 0;
            const kuramaMaxBudget = getArg('max-scan-pages') ? parseInt(getArg('max-scan-pages'), 10) : 180;

            while (verifiedTasks.length < kuramaTarget && kuramaScanned < kuramaMaxBudget) {
                kuramaScanned++;
                const isMovieMode = args.includes('--movie') || getArg('type') === 'movie';
                const curState = loadCatalogState();
                const curPage = isMovieMode ? (curState.kurama_movie_page || 1) : (curState.kurama_page || 1);
                const labelKurama = isMovieMode ? 'KATALOG MOVIE' : 'KATALOG KURAMA';
                console.log(`${UI.time()} ${UI.brightCyan}[${labelKurama}]${UI.reset} Membaca halaman ${isMovieMode ? 'movie' : 'katalog'} ${UI.brightWhite}#${curPage}${UI.reset} di Kuramanime... ${UI.gray}(Terkumpul: ${verifiedTasks.length}/${kuramaTarget})${UI.reset}`);
                const targetUrl = isMovieMode
                    ? `https://v20.kuramanime.ing/properties/type/movie?page=${curPage}`
                    : `https://v20.kuramanime.ing/quick/finished?page=${curPage}`;
                try {
                    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 25000 });
                    const cards = await page.evaluate(() => {
                        const list = [];
                        // HANYA ambil kartu dari konten utama katalog, ABAIKAN sidebar komentar/trending/view!
                        const mainContainer = document.querySelector('.product__page__content') || document.querySelector('.col-lg-8') || document.body;
                        const items = mainContainer.querySelectorAll('.product__item');
                        for (const item of items) {
                            if (item.closest('.product__sidebar, .product__sidebar__view, aside')) continue;
                            const a = item.querySelector('a[href*="/anime/"]');
                            if (!a) continue;
                            const href = a.href || '';
                            if (href.includes('/episode/')) continue;
                            const m = href.match(/\/anime\/(\d+)\/([a-z0-9-]+)/i);
                            if (!m) continue;
                            const h = item.querySelector('h5, h4, h3, h2, h1, .title');
                            const title = (h ? h.innerText : a.innerText || '').trim();
                            if (!title || title.toLowerCase().includes('loading')) continue;

                            let totalEps = 0;
                            const epEl = item.querySelector('.ep, .epz, .badge, .status');
                            if (epEl) {
                                const epText = epEl.innerText || '';
                                const epMatch = epText.match(/(\d+)\s*\/\s*(\d+)/) || epText.match(/(\d+)\s*(?:ep|eps|episode)/i) || epText.match(/ep\s*(\d+)/i);
                                if (epMatch) {
                                    totalEps = parseInt(epMatch[2] || epMatch[1], 10);
                                }
                            }

                            // Jika Movie, total episode otomatis di-set 1
                            const isMovie = (item.innerText || '').toLowerCase().includes('movie') || href.toLowerCase().includes('-movie') || (title || '').toLowerCase().includes('movie');
                            if (totalEps === 0 && isMovie) {
                                totalEps = 1;
                            }

                            list.push({
                                anime_id: parseInt(m[1], 10),
                                slug: m[2],
                                title: title,
                                total_episodes: totalEps,
                                url: href.split('?')[0]
                            });
                        }
                        return list;
                    });

                    if (cards.length > 0) {
                        console.log(`${UI.time()} ${UI.gray}  └─ Terbaca ${cards.length} kartu. Mengirim ke server untuk verifikasi 100% presisi...${UI.reset}`);
                        const res = await client.post('/verify-catalog', {
                            source: 'kuramanime',
                            catalog_page: curPage,
                            items: cards
                        });

                        if (res.data && res.data.tasks && res.data.tasks.length > 0) {
                            console.log(`${UI.time()} ${UI.brightGreen}  └─ Server mencocokkan ${res.data.tasks.length} episode yang butuh video server!${UI.reset}`);
                            verifiedTasks.push(...res.data.tasks);
                            console.log(`${UI.time()} ${UI.brightCyan}  └─ Total terkumpul: ${verifiedTasks.length}/${kuramaTarget} tugas.${UI.reset}`);
                        } else {
                            console.log(`${UI.time()} ${UI.gray}  └─ 0 episode baru yang butuh server di halaman ini.${UI.reset}`);
                        }
                    }

                    if (cards.length === 0) {
                        console.log(`${UI.time()} ${UI.yellow}  └─ Halaman #${curPage} kosong (ujung ${labelKurama}). Mereset ke Halaman #1.${UI.reset}`);
                        if (isMovieMode) {
                            saveCatalogState({ kurama_movie_page: 1 });
                        } else {
                            saveCatalogState({ kurama_page: 1 });
                        }
                        break;
                    }

                    if (isMovieMode) {
                        saveCatalogState({ kurama_movie_page: (curPage >= 25) ? 1 : curPage + 1 });
                    } else {
                        saveCatalogState({ kurama_page: (curPage >= 500) ? 1 : curPage + 1 });
                    }

                    if (verifiedTasks.length >= kuramaTarget) {
                        console.log(`${UI.time()} ${UI.brightGreen}  └─ Target batch Kurama (${verifiedTasks.length}/${kuramaTarget}) tercapai!${UI.reset}\n`);
                        break;
                    }

                    await sleep(500);
                } catch (kErr) {
                    console.log(`${UI.time()} ${UI.brightRed}  └─ Gagal membaca katalog Kurama: ${kErr.message}${UI.reset}`);
                    if (isMovieMode) {
                        saveCatalogState({ kurama_movie_page: (curPage >= 25) ? 1 : curPage + 1 });
                    } else {
                        saveCatalogState({ kurama_page: curPage + 1 });
                    }
                    await sleep(1000);
                }
            }
        }

        // 2. Pindaian Katalog Nekopoi (Category Hentai)
        if (sourceMode === 'neko' || (sourceMode === 'all' && verifiedTasks.length < BATCH_LIMIT)) {
            const nekoTarget = BATCH_LIMIT;
            let nekoScanned = 0;
            const nekoMaxBudget = getArg('max-scan-pages') ? parseInt(getArg('max-scan-pages'), 10) : 500;

            while (verifiedTasks.length < nekoTarget && nekoScanned < nekoMaxBudget) {
                nekoScanned++;
                const curState = loadCatalogState();
                const curPage = curState.neko_page || 1;
                console.log(`${UI.time()} ${UI.brightMagenta}[KATALOG NEKOPOI]${UI.reset} Membaca halaman arsip ${UI.brightWhite}#${curPage}${UI.reset} di Nekopoi... ${UI.gray}(Terkumpul: ${verifiedTasks.length}/${nekoTarget})${UI.reset}`);
                const targetUrl = curPage === 1
                    ? 'https://nekopoi.care/category/hentai/'
                    : `https://nekopoi.care/category/hentai/page/${curPage}/`;
                try {
                    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 25000 });
                    const items = await page.evaluate(() => {
                        const list = [];
                        // HANYA ambil item artikel/postingan di main content, abaikan sidebar
                        const mainContainer = document.querySelector('#content, .site-main, .contentpost, #main') || document.body;
                        const anchors = mainContainer.querySelectorAll('a.nk-search-item, .nk-search-item');
                        for (const a of anchors) {
                            if (a.closest('.sidebar, #sidebar, aside, .widget')) continue;
                            const href = a.href || a.getAttribute('href') || '';
                            const m = href.match(/\/([a-z0-9-]+)-episode-(\d+)-subtitle-indonesia/i);
                            if (!m) continue;
                            const h2 = a.querySelector('h2');
                            const rawTitle = (h2 ? h2.innerText : a.innerText || '').trim();
                            list.push({
                                slug: m[1],
                                episode_number: parseInt(m[2], 10),
                                title: rawTitle,
                                url: href
                            });
                        }
                        return list;
                    });

                    if (items.length > 0) {
                        console.log(`${UI.time()} ${UI.gray}  └─ Terbaca ${items.length} item hentai. Mengirim ke server untuk verifikasi 100% presisi...${UI.reset}`);
                        const res = await client.post('/verify-catalog', {
                            source: 'nekopoi',
                            catalog_page: curPage,
                            items: items,
                            download: DOWNLOAD_MODE ? 1 : 0
                        });

                        if (res.data && res.data.tasks && res.data.tasks.length > 0) {
                            console.log(`${UI.time()} ${UI.brightGreen}  └─ Server mencocokkan ${res.data.tasks.length} episode yang butuh video server!${UI.reset}`);
                            verifiedTasks.push(...res.data.tasks);
                            console.log(`${UI.time()} ${UI.brightMagenta}  └─ Total terkumpul: ${verifiedTasks.length}/${nekoTarget} tugas.${UI.reset}`);
                        } else {
                            console.log(`${UI.time()} ${UI.gray}  └─ 0 episode baru yang butuh server di halaman ini.${UI.reset}`);
                        }

                        saveCatalogState({ neko_page: curPage + 1 });
                    } else {
                        console.log(`${UI.time()} ${UI.yellow}  └─ Halaman #${curPage} kosong (ujung arsip Nekopoi). Mereset ke Halaman #1.${UI.reset}`);
                        saveCatalogState({ neko_page: 1 });
                        break;
                    }

                    if (verifiedTasks.length >= nekoTarget) {
                        console.log(`${UI.time()} ${UI.brightGreen}  └─ Target batch Nekopoi (${verifiedTasks.length}/${nekoTarget}) tercapai!${UI.reset}\n`);
                        break;
                    }

                    await sleep(500);
                } catch (nErr) {
                    console.log(`${UI.time()} ${UI.brightRed}  └─ Gagal membaca katalog Nekopoi: ${nErr.message}${UI.reset}`);
                    saveCatalogState({ neko_page: curPage + 1 });
                    await sleep(1000);
                }
            }
        }
    } catch (e) {
        console.log(`${UI.time()} ${UI.brightRed}[KATALOG ERROR] ${e.message}${UI.reset}`);
    } finally {
        if (page) {
            activeWorkerPages.delete(page);
            try { await page.close(); } catch (e) {}
        }
    }

    return verifiedTasks;
}

async function runBatch(browser) {
    const startTime = Date.now();
    console.log(`${UI.time()} ${UI.brightBlue}[SYNC]${UI.reset} Memeriksa tugas baru dari server... ${UI.gray}(mode: ${SOURCE_MODE}, limit: ${BATCH_LIMIT})${UI.reset}`);
    let tasks = await requestTasks(SOURCE_MODE, BATCH_LIMIT);

    // Jika tugas ongoing tidak ada, jalankan pemindaian katalog dari laptop ke server
    if (tasks.length === 0) {
        console.log(`${UI.time()} ${UI.brightCyan}[KATALOG]${UI.reset} Tugas ongoing selesai/kosong. Membaca katalog web untuk anime Completed...`);
        const catalogTasks = await scanAndVerifyCatalogBatch(browser, SOURCE_MODE);
        if (catalogTasks.length > 0) {
            tasks = catalogTasks;
        } else {
            console.log(`${UI.time()} ${UI.gray}[INFO] Tidak ada tugas baru setelah memindai katalog. Menunggu putaran berikutnya...${UI.reset}`);
            return 0;
        }
    }

    console.log(`${UI.time()} ${UI.brightGreen}[READY]${UI.reset} Ditemukan ${UI.brightWhite}${tasks.length}${UI.reset} tugas siap diproses.\n`);

    const kuramaTasks = tasks.filter(t => t.source === 'kuramanime');
    const nekoTasks   = tasks.filter(t => t.source === 'nekopoi');

    const runners = [];

    if (IS_MULTI_TAB) {
        if (kuramaTasks.length > 0 && nekoTasks.length > 0) {
            console.log(`${UI.time()} ${UI.brightCyan}[MULTI-TAB]${UI.reset} Menjalankan 2 Tab Paralel: ${UI.brightCyan}${kuramaTasks.length} Kurama${UI.reset} + ${UI.brightMagenta}${nekoTasks.length} Nekopoi${UI.reset}\n`);
            runners.push(processQueue(browser, kuramaTasks, 'TAB-1 KURAMA'));
            runners.push(processQueue(browser, nekoTasks, 'TAB-2 NEKOPOI'));
        } else if (kuramaTasks.length > 1) {
            const half = Math.ceil(kuramaTasks.length / 2);
            const part1 = kuramaTasks.slice(0, half);
            const part2 = kuramaTasks.slice(half);
            console.log(`${UI.time()} ${UI.brightCyan}[MULTI-TAB]${UI.reset} Membagi ${kuramaTasks.length} Kurama ke 2 Tab (${part1.length} + ${part2.length})\n`);
            runners.push(processQueue(browser, part1, 'TAB-1 KURAMA'));
            runners.push(processQueue(browser, part2, 'TAB-2 KURAMA'));
        } else if (kuramaTasks.length === 1) {
            runners.push(processQueue(browser, kuramaTasks, 'TAB-KURAMA'));
        } else if (nekoTasks.length > 0) {
            runners.push(processQueue(browser, nekoTasks, 'TAB-NEKOPOI'));
        }
    } else {
        let label = 'TAB-WORKER';
        if (SOURCE_MODE === 'neko' || (nekoTasks.length > 0 && kuramaTasks.length === 0)) {
            label = 'TAB-NEKOPOI';
        } else if (SOURCE_MODE === 'kurama' || (kuramaTasks.length > 0 && nekoTasks.length === 0)) {
            label = 'TAB-KURAMA';
        }
        console.log(`${UI.time()} ${UI.brightGreen}[SINGLE-TAB]${UI.reset} Memproses ${UI.brightWhite}${tasks.length}${UI.reset} tugas secara stabil dalam 1 Tab browser\n`);
        runners.push(processQueue(browser, tasks, label));
    }

    const results = await Promise.all(runners);
    const completed = results.reduce((acc, c) => acc + c, 0);
    const failed = tasks.length - completed;
    const durationSec = Math.round((Date.now() - startTime) / 1000);

    let serverStats = null;
    try { serverStats = await fetchServerAdminStats(); } catch (e) {}
    UI.batchSummary(tasks.length, completed, failed, durationSec, LOOP_MODE ? POLL_INTERVAL : null, serverStats);
    return completed;
}

async function main() {
    // 1. Cek jika hanya ingin mereset atau mengatur halaman katalog tanpa membuka browser
    const isResetOnly = args.includes('--reset-page') || args.includes('--reset') || args.includes('--set-page');
    const isRunWithReset = args.includes('--run') || args.includes('--loop') || args.includes('-l');

    if (isResetOnly || getArg('neko-page') !== undefined || getArg('kurama-page') !== undefined || getArg('movie-page') !== undefined) {
        const p = path.join(__dirname, 'catalog_state.json');
        let state = { kurama_page: 1, kurama_movie_page: 1, neko_page: 1 };
        if (fs.existsSync(p)) {
            try { state = Object.assign(state, JSON.parse(fs.readFileSync(p, 'utf8'))); } catch (e) {}
        }
        if (args.includes('--reset-page') || args.includes('--reset')) {
            state.kurama_page = 1;
            state.kurama_movie_page = 1;
            state.neko_page = 1;
        }
        const cliNekoPage = getArg('neko-page', getArg('page'));
        const cliKuramaPage = getArg('kurama-page', getArg('page'));
        const cliMoviePage = getArg('movie-page');
        if (cliNekoPage !== undefined) state.neko_page = Math.max(1, parseInt(cliNekoPage, 10));
        if (cliKuramaPage !== undefined) state.kurama_page = Math.max(1, parseInt(cliKuramaPage, 10));
        if (cliMoviePage !== undefined) state.kurama_movie_page = Math.max(1, parseInt(cliMoviePage, 10));

        fs.writeFileSync(p, JSON.stringify(state, null, 2), 'utf8');

        if (isResetOnly && !isRunWithReset) {
            console.log(`\n${UI.brightGreen}====================================================${UI.reset}`);
            console.log(`${UI.brightGreen}  BERHASIL MERESET / MENGATUR HALAMAN KATALOG!${UI.reset}`);
            console.log(`${UI.brightGreen}====================================================${UI.reset}`);
            console.log(`  ${UI.gray}├─ File State    :${UI.reset} ${p}`);
            console.log(`  ${UI.gray}├─ Kurama TV/All :${UI.reset} ${UI.brightCyan}Halaman #${state.kurama_page}${UI.reset}`);
            console.log(`  ${UI.gray}├─ Kurama Movie  :${UI.reset} ${UI.brightCyan}Halaman #${state.kurama_movie_page}${UI.reset}`);
            console.log(`  ${UI.gray}└─ Nekopoi       :${UI.reset} ${UI.brightMagenta}Halaman #${state.neko_page}${UI.reset}\n`);
            console.log(`${UI.yellow}Browser TIDAK dibuka karena hanya mode reset/set-page.${UI.reset}`);
            console.log(`${UI.gray}Untuk mulai scraping, jalankan worker seperti biasa.${UI.reset}\n`);
            process.exit(0);
        }
    }

    const browserInfo = getBrowserInfo();

    let initialStats = null;
    try { initialStats = await fetchServerAdminStats(); } catch (e) {}

    UI.banner(
        SOURCE_MODE,
        BATCH_LIMIT,
        HEADLESS,
        LOOP_MODE,
        POLL_INTERVAL,
        browserInfo.name,
        IS_MULTI_TAB,
        DOWNLOAD_MODE,
        VIDEO_STORAGE_DIR,
        initialStats
    );

    const launchOptions = {
        headless: HEADLESS,
        protocolTimeout: 0,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--ignore-certificate-errors',
            '--host-resolver-rules=MAP nekopoi.care 104.21.14.33, MAP *.nekopoi.care 104.21.14.33, MAP kuramanime.ing 104.21.66.92, MAP *.kuramanime.ing 104.21.66.92',
            '--blink-settings=imagesEnabled=false',
            '--disable-popup-blocking=false',
            '--disable-notifications',
        ],
    };

    const winX = getArg('win-x');
    const winY = getArg('win-y');
    const winW = getArg('win-w', '960');
    const winH = getArg('win-h', '520');
    if (winX !== undefined && winY !== undefined) {
        launchOptions.args.push(`--window-position=${winX},${winY}`);
        launchOptions.args.push(`--window-size=${winW},${winH}`);
    } else {
        launchOptions.args.push('--window-size=1280,720');
    }

    if (browserInfo.path) {
        console.log(`${UI.time()} ${UI.gray}Menghubungkan executable: ${browserInfo.path}${UI.reset}`);
        launchOptions.executablePath = browserInfo.path;
    }

    console.log(`${UI.time()} ${UI.yellow}Memulai browser instance...${UI.reset}`);
    const browser = await puppeteer.launch(launchOptions);
    console.log(`${UI.time()} ${UI.brightGreen}Browser siap beroperasi!${UI.reset}\n`);

    // Otomatis tutup tab popup iklan liar dari website nekopoi/kurama/ouo
    browser.on('targetcreated', async (target) => {
        if (target.type() === 'page' && target.opener()) {
            try {
                await sleep(300);
                const p = await target.page();
                if (p && !activeWorkerPages.has(p)) {
                    await p.close().catch(() => {});
                }
            } catch (e) {}
        }
    });

    process.on('SIGINT', async () => {
        console.log(`\n${UI.time()} ${UI.yellow}Menghentikan worker secara aman...${UI.reset}`);
        try { await browser.close(); } catch (e) {}
        process.exit(0);
    });

    try {
        if (LOOP_MODE) {
            while (true) {
                await runBatch(browser);
                await sleep(POLL_INTERVAL * 1000);
            }
        } else {
            await runBatch(browser);
        }
    } finally {
        await browser.close();
        console.log(`${UI.time()} ${UI.gray}Worker selesai ditutup.${UI.reset}`);
    }
}

// Global crash shield agar worker kebal dari ProtocolError akibat iklan liar
process.on('unhandledRejection', (reason) => {
    const msg = reason && reason.message ? reason.message : String(reason);
    if (msg.includes('ProtocolError') || msg.includes('Target closed') || msg.includes('Session closed')) return;
    console.log(`${UI.time()} ${UI.gray}[WARN] ${msg}${UI.reset}`);
});

process.on('uncaughtException', (err) => {
    const msg = err && err.message ? err.message : String(err);
    if (msg.includes('ProtocolError') || msg.includes('Target closed') || msg.includes('Session closed')) return;
    console.log(`${UI.time()} ${UI.brightRed}[ERROR] ${msg}${UI.reset}`);
});

main().catch(err => {
    console.error('\nFatal Error:', err);
    process.exit(1);
});
