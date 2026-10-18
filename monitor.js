/**
 * Nipnime Server Admin Real-Time Monitor
 * 
 * Memantau secara live progres pengisian video Server Admin di CasaOS:
 * - Jumlah episode Nekopoi terisi vs total (persentase & sisa)
 * - Progres bar visual
 * - Total kapasitas disk CasaOS (GB / TB) & jumlah file MP4
 * - Episode yang bertambah hari ini
 * - 5 episode terakhir yang baru saja selesai diunduh
 * - Status keaktifan worker laptop
 * 
 * Menggunakan native fetch Node.js v24 (Zero dependencies, instant startup).
 */

const fs = require('fs');
const path = require('path');
const dns = require('dns');

if (dns.setDefaultResultOrder) {
    dns.setDefaultResultOrder('ipv4first');
}

// Manual parse .env agar mandiri tanpa butuh modul dotenv
let API_URL = 'https://nipnime.com/api/terop';
let WORKER_TOKEN = 'nipnime_terop_secret_key_2026';

const envCandidates = [
    path.join(__dirname, '.env'),
    'Z:\\tools\\terop-worker\\.env',
    'D:\\tools\\terop-worker\\.env',
];

for (const ep of envCandidates) {
    if (fs.existsSync(ep)) {
        try {
            const content = fs.readFileSync(ep, 'utf8');
            const lines = content.split('\n');
            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed || trimmed.startsWith('#')) continue;
                const eqIdx = trimmed.indexOf('=');
                if (eqIdx > 0) {
                    const key = trimmed.slice(0, eqIdx).trim();
                    const val = trimmed.slice(eqIdx + 1).trim().replace(/^["']|["']$/g, '');
                    if (key === 'API_URL') API_URL = val;
                    if (key === 'WORKER_TOKEN') WORKER_TOKEN = val;
                }
            }
            break;
        } catch (e) {}
    }
}

if (process.env.API_URL) API_URL = process.env.API_URL;
if (process.env.WORKER_TOKEN) WORKER_TOKEN = process.env.WORKER_TOKEN;

let refreshIntervalSec = 3;
let timer = null;
let isFetching = false;
let sessionStartFilled = null;
let previousData = null;
let alertMessage = null;
let alertTimer = null;

// ANSI Colors & Typography
const C = {
    reset: '\x1b[0m',
    bold: '\x1b[1m',
    dim: '\x1b[2m',
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
};

function makeProgressBar(percent, width = 38) {
    const p = Math.max(0, Math.min(100, percent));
    const filled = Math.round((p / 100) * width);
    const empty = width - filled;
    const bar = '█'.repeat(filled) + '░'.repeat(empty);
    return `${C.brightGreen}${bar}${C.reset}`;
}

function formatNumber(num) {
    if (num === undefined || num === null) return '0';
    return Number(num).toLocaleString('id-ID');
}

function truncate(str, maxLen) {
    if (!str) return '-';
    if (str.length <= maxLen) return str;
    return str.slice(0, maxLen - 2) + '..';
}

async function fetchStats() {
    if (isFetching) return;
    isFetching = true;
    try {
        const endpoint = API_URL.replace(/\/+$/, '') + '/status';
        const url = new URL(endpoint);
        url.searchParams.set('token', WORKER_TOKEN);

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 15000);

        const res = await fetch(url.toString(), {
            headers: {
                'X-Terop-Token': WORKER_TOKEN,
                'Accept': 'application/json',
            },
            signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!res.ok) {
            throw new Error(`HTTP ${res.status} ${res.statusText}`);
        }

        const data = await res.json();
        if (data && data.success) {
            handleDataUpdate(data);
        } else {
            renderError(data.error || 'Respon server tidak valid');
        }
    } catch (err) {
        renderError(err.message);
    } finally {
        isFetching = false;
    }
}

function handleDataUpdate(data) {
    const admin = data.server_admin || {};
    const currentFilled = admin.neko_episodes_filled || 0;

    if (sessionStartFilled === null) {
        sessionStartFilled = currentFilled;
    }

    if (previousData && previousData.server_admin) {
        const prevFilled = previousData.server_admin.neko_episodes_filled || 0;
        const prevFiles = previousData.server_admin.disk_files_count || 0;

        if (currentFilled > prevFilled) {
            const diff = currentFilled - prevFilled;
            triggerAlert(`🎉 ${C.bold}+${diff} EPISODE BARU BERHASIL DISIMPAN KE CASAOS!${C.reset}`);
        } else if (admin.disk_files_count > prevFiles) {
            const diffFiles = admin.disk_files_count - prevFiles;
            triggerAlert(`📥 ${C.bold}+${diffFiles} FILE VIDEO BARU TERVERIFIKASI DI DISK!${C.reset}`);
        }
    }

    previousData = data;
    renderDashboard(data);

    if (process.argv.includes('--once')) {
        setTimeout(() => process.exit(0), 200);
    }
}

function triggerAlert(msg) {
    alertMessage = msg;
    process.stdout.write('\x07'); // Suara beep bell notification
    if (alertTimer) clearTimeout(alertTimer);
    alertTimer = setTimeout(() => {
        alertMessage = null;
        if (previousData) renderDashboard(previousData);
    }, 8000);
}

function renderError(errMsg) {
    console.clear();
    console.log(`\n${C.brightRed}========================================================================${C.reset}`);
    console.log(`  ${C.brightRed}${C.bold}[KONEKSI ERROR] GAGAL MENGHUBUNGI SERVER NIPNIME${C.reset}`);
    console.log(`${C.brightRed}========================================================================${C.reset}`);
    console.log(`  ${C.gray}Server   :${C.reset} ${API_URL}`);
    console.log(`  ${C.gray}Pesan    :${C.reset} ${errMsg}`);
    console.log(`  ${C.gray}Waktu    :${C.reset} ${new Date().toLocaleTimeString('id-ID')}`);
    console.log(`\n  ${C.yellow}Mencoba menghubungkan kembali dalam ${refreshIntervalSec} detik...${C.reset}`);
    console.log(`  ${C.gray}Tekan [Q] untuk keluar | [R] untuk coba sekarang${C.reset}\n`);
}

function stripAnsi(str) {
    return str.replace(/\x1b\[[0-9;]*m/g, '');
}

function padBox(content, width = 80, border = '║') {
    const clean = stripAnsi(content);
    const spaces = Math.max(0, width - clean.length);
    return `${border} ${content}${' '.repeat(spaces)} ${border}`;
}

function renderDashboard(data) {
    const admin = data.server_admin || {};
    const worker = data.worker_stats || {};
    const now = new Date().toLocaleTimeString('id-ID');

    const nekoFilled = admin.neko_episodes_filled || 0;
    const nekoTotal = admin.neko_total_episodes || 0;
    const nekoRemaining = admin.neko_remaining_episodes || 0;
    const nekoPercent = admin.neko_percent || (nekoTotal > 0 ? ((nekoFilled / nekoTotal) * 100).toFixed(1) : 0);
    const nekoAnimeDone = admin.neko_anime_completed || 0;
    const nekoAnimeTotal = admin.neko_total_anime || 0;

    const allFilled = admin.all_episodes_filled || 0;
    const addedToday = admin.added_today || 0;
    const diskFiles = admin.disk_files_count || 0;
    const diskSizeFormatted = admin.disk_size_formatted || '0 GB';
    const latestList = admin.latest_filled || [];

    // Bersihkan layar & scrollback terminal sepenuhnya agar tidak bertumpuk/scroll
    console.clear();

    const topBorder = `╔${'═'.repeat(82)}╗`;
    const midBorder = `╠${'═'.repeat(82)}╣`;
    const botBorder = `╚${'═'.repeat(82)}╝`;

    console.log(`${C.brightCyan}${topBorder}${C.reset}`);
    
    const rowTitle = `${C.brightWhite}${C.bold}N I P N I M E   S E R V E R   A D M I N   M O N I T O R${C.reset}  ${C.brightGreen}● LIVE${C.reset}  ${C.gray}v1.0${C.reset}`;
    console.log(`${C.brightCyan}${padBox(rowTitle, 80)}${C.reset}`);
    
    const rowServer = `${C.gray}Server :${C.reset} ${C.white}${API_URL}${C.reset}  ${C.gray}│ Refresh:${C.reset} ${C.brightYellow}${refreshIntervalSec}s${C.reset}  ${C.gray}│ Jam:${C.reset} ${C.brightCyan}${now}${C.reset}`;
    console.log(`${C.brightCyan}${padBox(rowServer, 80)}${C.reset}`);
    
    console.log(`${C.brightCyan}${midBorder}${C.reset}`);
    
    // Progres bar + persentase
    const bar = makeProgressBar(nekoPercent, 26);
    const pctStr = `${String(nekoPercent).padStart(5, ' ')}%`;
    const countStr = `${formatNumber(nekoFilled)}/${formatNumber(nekoTotal)} ep`;
    const rowProgress = `${C.brightMagenta}Nekopoi 18+${C.reset}  ${bar} ${C.brightYellow}${C.bold}${pctStr}${C.reset}  ${C.brightGreen}${countStr}${C.reset}`;
    console.log(`${C.brightCyan}${padBox(rowProgress, 80)}${C.reset}`);
    
    // Ringkasan metrik 2 baris
    const line1 = `${C.gray}Sisa: ${C.brightYellow}${formatNumber(nekoRemaining)} ep${C.reset} │ ${C.gray}Tamat: ${C.brightCyan}${formatNumber(nekoAnimeDone)}/${formatNumber(nekoAnimeTotal)}${C.reset} │ ${C.gray}Hari Ini: ${C.brightGreen}+${formatNumber(addedToday)} ep${C.reset}`;
    const line2 = `${C.gray}CasaOS Disk: ${C.brightCyan}${diskSizeFormatted}${C.reset} (${formatNumber(diskFiles)} MP4) │ ${C.gray}Global Server: ${C.white}${formatNumber(allFilled)} ep${C.reset}`;
    
    console.log(`${C.brightCyan}${padBox(line1, 80)}${C.reset}`);
    console.log(`${C.brightCyan}${padBox(line2, 80)}${C.reset}`);
    
    if (alertMessage) {
        console.log(`${C.brightCyan}${padBox(`${C.brightGreen}🔔 ${alertMessage}${C.reset}`, 80)}${C.reset}`);
    }
    console.log(`${C.brightCyan}${botBorder}${C.reset}`);

    // Tabel 5 Episode Terakhir
    const tblTop = `┌── 5 EPISODE TERAKHIR DIUNDUH KE CASAOS ${'─'.repeat(42)}┐`;
    const tblDiv = `├${'─'.repeat(16)}┼${'─'.repeat(5)}┼${'─'.repeat(22)}┼${'─'.repeat(36)}┤`;
    const tblBot = `└${'─'.repeat(16)}┴${'─'.repeat(5)}┴${'─'.repeat(22)}┴${'─'.repeat(36)}┘`;

    console.log(`${C.gray}${tblTop}${C.reset}`);
    console.log(`${C.gray}│ ${C.white}WAKTU         ${C.gray} │ ${C.white}EP ${C.gray} │ ${C.white}KUALITAS            ${C.gray} │ ${C.white}JUDUL ANIME                        ${C.gray}│${C.reset}`);
    console.log(`${C.gray}${tblDiv}${C.reset}`);

    if (latestList.length === 0) {
        console.log(`${C.gray}│  Belum ada riwayat aktivitas terbaru yang tercatat.                              │${C.reset}`);
    } else {
        latestList.slice(0, 5).forEach(item => {
            const timeStr = truncate(item.created_at || 'Baru saja', 14).padEnd(14, ' ');
            const epStr = String(item.episode_number || 1).padStart(3, ' ');
            const qStr = truncate(item.server_name || 'Server Admin', 20).padEnd(20, ' ');
            const titleStr = truncate(item.anime_title || 'Unknown', 34).padEnd(34, ' ');

            let qColor = C.brightCyan;
            if (item.server_name && item.server_name.includes('720')) qColor = C.brightGreen;
            else if (item.server_name && item.server_name.includes('480')) qColor = C.brightYellow;
            else if (item.server_name && item.server_name.includes('360')) qColor = C.gray;

            console.log(`${C.gray}│${C.reset} ${C.gray}${timeStr}${C.reset} │ ${C.brightWhite}#${epStr}${C.reset} │ ${qColor}${qStr}${C.reset} │ ${C.white}${titleStr}${C.reset} ${C.gray}│${C.reset}`);
        });
    }
    console.log(`${C.gray}${tblBot}${C.reset}`);

    // Footer Navigasi
    console.log(`  ${C.gray}Navigasi:${C.reset} ${C.brightYellow}[R]${C.reset} Refresh  ${C.brightCyan}[+]${C.reset} Percepat (${refreshIntervalSec}s)  ${C.brightCyan}[-]${C.reset} Perlambat  ${C.brightRed}[Q]${C.reset} Keluar`);
}

function startPolling() {
    if (timer) clearInterval(timer);
    fetchStats();
    timer = setInterval(fetchStats, refreshIntervalSec * 1000);
}

// Tangani input keyboard langsung tanpa perlu tekan Enter
if (process.stdin.isTTY) {
    try {
        process.stdin.setRawMode(true);
        process.stdin.resume();
        process.stdin.setEncoding('utf8');

        process.stdin.on('data', (key) => {
            if (key === '\u0003' || key.toLowerCase() === 'q') {
                console.log(`\n  ${C.yellow}Monitor dihentikan.${C.reset}\n`);
                process.exit(0);
            }

            if (key.toLowerCase() === 'r') {
                fetchStats();
            }

            if (key === '+' || key === '=') {
                if (refreshIntervalSec > 1) {
                    refreshIntervalSec = Math.max(1, refreshIntervalSec - 1);
                    startPolling();
                }
            }

            if (key === '-' || key === '_') {
                if (refreshIntervalSec < 30) {
                    refreshIntervalSec = Math.min(30, refreshIntervalSec + 1);
                    startPolling();
                }
            }
        });
    } catch (e) {}
}

process.on('SIGINT', () => {
    console.log(`\n  ${C.yellow}Monitor dihentikan.${C.reset}\n`);
    process.exit(0);
});

// Jalankan monitor
console.log(`\n  ${C.cyan}Menghubungkan ke server Nipnime...${C.reset}`);
startPolling();
