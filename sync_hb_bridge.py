import json, time, os, glob
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
    tz = ZoneInfo('Asia/Jakarta')
except Exception:
    from datetime import timezone, timedelta
    tz = timezone(timedelta(hours=7))

hb_path = '/app/.worker_heartbeat.json'
tmp_dir = '/app/temp_videos'
tot_bytes = 745.5 * 1024 * 1024

last_cur = 0
last_time = time.time()

for _ in range(120): # Maksimal 4 menit
    parts = glob.glob(tmp_dir + '/cang-yuan-tu-3_ep26_1080p.part_*.tmp')
    if not parts:
        break

    now = time.time()
    cur_bytes = sum(os.path.getsize(p) for p in parts)
    cur_mb = round(cur_bytes / (1024 * 1024), 1)
    tot_mb = 745.5
    pct = round((cur_bytes / tot_bytes) * 100, 1)

    dt = max(0.5, now - last_time)
    spd = max(0.0, ((cur_bytes - last_cur) / dt) / (1024 * 1024)) if last_cur > 0 else 1.2
    last_cur = cur_bytes
    last_time = now

    eta_s = int((tot_bytes - cur_bytes) / (spd * 1024 * 1024)) if spd > 0.1 else 60
    eta_str = f"{eta_s}s"

    try:
        with open(hb_path, 'r') as f:
            data = json.load(f)

        data['timestamp'] = int(time.time())
        data['last_heartbeat'] = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S WIB')
        data['current_task'] = f"[1080p Multi-Stream] cang-yuan-tu-3_ep26_1080p.mp4: {pct}% ({cur_mb}/{tot_mb} MB) @ {spd:.1f}MB/s | ETA: {eta_str}"
        data['active_tasks'] = [{
            'key': 'cang-yuan-tu-3_ep26_1080p.mp4',
            'label': '[1080p Multi-Stream] cang-yuan-tu-3_ep26_1080p.mp4',
            'pct': pct,
            'cur_mb': cur_mb,
            'tot_mb': tot_mb,
            'speed_mb': round(spd, 1),
            'eta_str': eta_str,
            'status_text': f"{cur_mb}/{tot_mb} MB"
        }]

        with open(hb_path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

    time.sleep(2)
