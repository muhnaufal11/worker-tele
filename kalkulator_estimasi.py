#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
NIPNIME WORKER - ESTIMATOR & THROUGHPUT CALCULATOR (CLI)
================================================================================
Kalkulator estimasi kecepatan pemrosesan episode (Ep/Jam) dan perkiraan sisa waktu
penyelesaian (ETA) antrean database berdasarkan spesifikasi hardware worker atau
seluruh cluster aktif.

Penggunaan:
    python kalkulator_estimasi.py                      # Auto-detect spek mesin lokal saat ini
    python kalkulator_estimasi.py --cluster            # Hitung gabungan seluruh node aktif
    python kalkulator_estimasi.py --cores 4 --ram 8    # Simulasi spek worker tertentu
    python kalkulator_estimasi.py --json               # Output format JSON
================================================================================
"""

import os
import sys
import json
import time
import argparse
import subprocess
from datetime import datetime, timedelta

# Fix encoding di terminal Windows (cp1252 / cmd / powershell)
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import psutil
except ImportError:
    psutil = None

# ANSI Color codes
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE = "\033[34m"
C_MAGENTA = "\033[35m"
C_WHITE = "\033[37m"

def get_base_dir():
    return os.path.dirname(os.path.abspath(__file__))

def detect_hardware():
    """Mendeteksi spesifikasi hardware mesin lokal."""
    # CPU
    cores = os.cpu_count() or 2
    
    # RAM
    ram_gb = 4.0
    if psutil:
        try:
            ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
        except Exception:
            pass
            
    # GPU Detection
    has_gpu = False
    gpu_name = "None (CPU Only)"
    try:
        smi = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], 
                             capture_output=True, text=True, timeout=2)
        if smi.returncode == 0 and smi.stdout.strip():
            has_gpu = True
            gpu_name = smi.stdout.strip().split("\n")[0]
    except Exception:
        pass
        
    return {
        "cores": cores,
        "ram_gb": ram_gb,
        "has_gpu": has_gpu,
        "gpu_name": gpu_name,
        "platform": sys.platform
    }

def calculate_recommended_concurrency(cores, ram_gb, has_gpu):
    """Menghitung nilai paralel / concurrency paling stabil untuk spek yang diberikan."""
    if has_gpu:
        return min(max(2, int(ram_gb // 2)), 6)
    
    # Tiap proses butuh ~1 - 1.5 GB RAM dan ~1 - 2 core
    by_ram = int(ram_gb // 1.5)
    by_cpu = max(1, int(cores * 0.75))
    concurrency = max(1, min(by_ram, by_cpu))
    return min(concurrency, 6)

def estimate_throughput(cores, ram_gb, has_gpu, concurrency, network="cloud"):
    """
    Menghitung estimasi throughput episode per jam.
    
    Benchmark riil:
    - Ongoing Fast-Ingest: ~30-40 detik per Ep per task -> ~80-100 Ep/jam per task (Cloud)
    - Completed / Watermark Transcode:
        - CPU 2 Core: ~45 Ep/jam (mix res)
        - CPU 4 Core: ~75-85 Ep/jam (mix res)
        - CPU 8 Core: ~150-160 Ep/jam (mix res)
        - GPU NVENC: ~200-300 Ep/jam
    """
    net_multiplier = 1.0 if network == "cloud" else 0.75
    
    # 1. Mode Rilis Cepat Ongoing
    # 1 task ongoing di Cloud memproses ~90 ep/jam
    ep_per_hour_ongoing = int(concurrency * 90 * net_multiplier)
    
    # 2. Mode Transcode Watermark / Completed
    if has_gpu:
        ep_per_hour_completed = int(concurrency * 65 * net_multiplier)
    else:
        # Tiap core CPU menghasilkan ~20 ep/jam secara rata-rata multi-resolusi
        core_power = cores * 19.5
        # Dibatasi oleh concurrency
        ep_per_hour_completed = int(min(core_power, concurrency * 35) * net_multiplier)
        ep_per_hour_completed = max(15, ep_per_hour_completed)
        
    # 3. Rata-rata Campuran (Mix Workload)
    avg_speed = int(round((ep_per_hour_ongoing * 0.3) + (ep_per_hour_completed * 0.7)))
    
    return {
        "concurrency": concurrency,
        "ep_per_hour_ongoing": ep_per_hour_ongoing,
        "ep_per_hour_completed": ep_per_hour_completed,
        "ep_per_hour_avg": avg_speed,
        "ep_per_day_avg": avg_speed * 24
    }

def read_database_queue():
    """Membaca sisa antrean aktual dari file state."""
    base = get_base_dir()
    comp_file = os.path.join(base, ".completed_anime_state.json")
    ong_file = os.path.join(base, ".ongoing_quality_state.json")
    
    # Fallback ke drive Z: jika di Windows D: file belum lengkap
    if sys.platform == "win32" and not os.path.exists(comp_file) and os.path.exists("Z:/tools/terop-worker/.completed_anime_state.json"):
        comp_file = "Z:/tools/terop-worker/.completed_anime_state.json"
        ong_file = "Z:/tools/terop-worker/.ongoing_quality_state.json"
    
    completed_pending_batches = 0
    completed_progress_batches = 0
    completed_done_batches = 0
    
    if os.path.exists(comp_file):
        try:
            with open(comp_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                for item in d.get("queue", []):
                    st = item.get("status", "pending")
                    if st == "pending":
                        completed_pending_batches += 1
                    elif st == "in_progress":
                        completed_progress_batches += 1
                    elif st == "complete":
                        completed_done_batches += 1
        except Exception:
            pass
            
    ongoing_partial_episodes = 0
    if os.path.exists(ong_file):
        try:
            with open(ong_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                for k, v in d.items():
                    if isinstance(v, dict) and not v.get("complete", False):
                        ongoing_partial_episodes += 1
        except Exception:
            pass
            
    # Estimasi 12 episode per batch anime tamat
    remaining_batches = completed_pending_batches + completed_progress_batches
    est_completed_episodes = remaining_batches * 12
    total_remaining_episodes = est_completed_episodes + ongoing_partial_episodes
    
    return {
        "completed_pending_batches": completed_pending_batches,
        "completed_progress_batches": completed_progress_batches,
        "completed_done_batches": completed_done_batches,
        "total_remaining_batches": remaining_batches,
        "est_completed_episodes": est_completed_episodes,
        "ongoing_partial_episodes": ongoing_partial_episodes,
        "total_remaining_episodes": total_remaining_episodes
    }

def read_cluster_nodes():
    """Membaca seluruh worker aktif dari .active_workers.json."""
    base = get_base_dir()
    candidate_files = [os.path.join(base, ".active_workers.json")]
    if sys.platform == "win32" and os.path.exists("Z:/tools/terop-worker/.active_workers.json"):
        candidate_files.append("Z:/tools/terop-worker/.active_workers.json")
        
    now = time.time()
    active_nodes = []
    
    for act_file in candidate_files:
        if not os.path.exists(act_file):
            continue
        try:
            with open(act_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                for wid, w in d.items():
                    last_active = w.get("last_active", 0)
                    if (now - last_active) <= 180: # Aktif dalam 3 menit terakhir
                        hw = w.get("hardware", {})
                        gpu = hw.get("gpu", {})
                        active_nodes.append({
                            "worker_id": wid,
                            "hostname": w.get("hostname", "Node"),
                            "role": w.get("role", "worker"),
                            "platform": w.get("platform", "linux"),
                            "ram_total_gb": hw.get("ram_total_gb", 4.0),
                            "has_gpu": gpu.get("available", False) if isinstance(gpu, dict) else False,
                            "last_active_wib": w.get("last_active_wib", "-")
                        })
        except Exception:
            pass
    # Jika di Windows SMB cache membuat file stale (0 node aktif), ambil langsung via SSH ke CasaOS
    if not active_nodes and sys.platform == "win32":
        try:
            res = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=2", "naufal@192.168.100.65", "cat /home/naufal/Web-Anime/tools/terop-worker/.active_workers.json"],
                capture_output=True, text=True, timeout=3
            )
            if res.returncode == 0 and res.stdout.strip():
                d = json.loads(res.stdout)
                for wid, w in d.items():
                    last_active = w.get("last_active", 0)
                    if (now - last_active) <= 180:
                        hw = w.get("hardware", {})
                        gpu = hw.get("gpu", {})
                        active_nodes.append({
                            "worker_id": wid,
                            "hostname": w.get("hostname", "Node"),
                            "role": w.get("role", "worker"),
                            "platform": w.get("platform", "linux"),
                            "ram_total_gb": hw.get("ram_total_gb", 4.0),
                            "has_gpu": gpu.get("available", False) if isinstance(gpu, dict) else False,
                            "last_active_wib": w.get("last_active_wib", "-")
                        })
        except Exception:
            pass

    return active_nodes

def format_eta_duration(hours):
    """Memformat jam menjadi format yang mudah dibaca."""
    if hours <= 0:
        return "Selesai / Antrean Kosong"
    days = int(hours // 24)
    rem_h = int(hours % 24)
    rem_m = int(round((hours - int(hours)) * 60))
    parts = []
    if days > 0:
        parts.append(f"{days} Hari")
    if rem_h > 0 or days > 0:
        parts.append(f"{rem_h} Jam")
    parts.append(f"{rem_m} Menit")
    return " ".join(parts)

def format_target_date(hours):
    """Menghitung target tanggal dan jam selesai dalam WIB."""
    target_dt = datetime.now() + timedelta(hours=hours)
    return target_dt.strftime("%d %B %Y, %H:%M WIB")

def print_banner():
    print(f"{C_CYAN}{C_BOLD}╔═════════════════════════════════════════════════════════════════════════════╗{C_RESET}")
    print(f"{C_CYAN}{C_BOLD}║         NIPNIME WORKER - ESTIMATOR & THROUGHPUT CALCULATOR (CLI)            ║{C_RESET}")
    print(f"{C_CYAN}{C_BOLD}╚═════════════════════════════════════════════════════════════════════════════╝{C_RESET}")

def main():
    parser = argparse.ArgumentParser(description="Kalkulator Throughput & Estimasi Waktu Selesai Worker Nipnime")
    parser.add_argument("--cluster", action="store_true", help="Hitung kapasitas gabungan seluruh node aktif di cluster")
    parser.add_argument("--cores", type=int, default=None, help="Jumlah core CPU (default: deteksi otomatis)")
    parser.add_argument("--ram", type=float, default=None, help="Ukuran RAM dalam GB (default: deteksi otomatis)")
    parser.add_argument("--gpu", action="store_true", default=None, help="Gunakan akselerasi GPU")
    parser.add_argument("--concurrency", type=int, default=None, help="Jumlah paralel task worker")
    parser.add_argument("--network", choices=["cloud", "home"], default="cloud", help="Tipe koneksi jaringan")
    parser.add_argument("--json", action="store_true", help="Tampilkan hasil dalam format JSON")
    args = parser.parse_args()

    queue_data = read_database_queue()
    total_ep = queue_data["total_remaining_episodes"]

    if args.cluster:
        # MODE CLUSTER GABUNGAN
        active_nodes = read_cluster_nodes()
        total_speed_ongoing = 0
        total_speed_completed = 0
        node_details = []

        for node in active_nodes:
            role = node["role"]
            ram = node["ram_total_gb"]
            has_gpu = node["has_gpu"]
            
            # Estimasi core berdasarkan peran
            if "4cpu" in node["hostname"].lower():
                cores = 4
                conc = 3
            elif "2cpu" in node["hostname"].lower():
                cores = 2
                conc = 2
            elif role == "warnet":
                cores = 6
                conc = 4
                has_gpu = True
            elif role == "codespace":
                cores = 4
                conc = 3
            else:
                cores = 2
                conc = 2

            t = estimate_throughput(cores, ram, has_gpu, conc, network="cloud")
            total_speed_ongoing += t["ep_per_hour_ongoing"]
            total_speed_completed += t["ep_per_hour_completed"]
            node_details.append({
                "hostname": node["hostname"],
                "role": role,
                "cores": cores,
                "ram_gb": ram,
                "speed_completed": t["ep_per_hour_completed"],
                "speed_ongoing": t["ep_per_hour_ongoing"]
            })

        avg_cluster_speed = int(round((total_speed_ongoing * 0.25) + (total_speed_completed * 0.75)))
        avg_cluster_speed = max(1, avg_cluster_speed)
        hours_needed = round(total_ep / avg_cluster_speed, 1)

        result = {
            "mode": "cluster",
            "active_nodes_count": len(active_nodes),
            "nodes": node_details,
            "total_speed_ongoing_hour": total_speed_ongoing,
            "total_speed_completed_hour": total_speed_completed,
            "avg_cluster_speed_hour": avg_cluster_speed,
            "avg_cluster_speed_day": avg_cluster_speed * 24,
            "queue": queue_data,
            "hours_needed": hours_needed,
            "eta_formatted": format_eta_duration(hours_needed),
            "target_date_wib": format_target_date(hours_needed)
        }

        if args.json:
            print(json.dumps(result, indent=2))
            return

        print_banner()
        print(f"\n{C_BOLD}📊 MODE: GABUNGAN CLUSTER AKTIF ({len(active_nodes)} Node Terdeteksi){C_RESET}")
        print(f"{C_DIM}{'─'*77}{C_RESET}")
        for i, n in enumerate(node_details, 1):
            print(f"  {i}. {C_CYAN}{n['hostname']:<26}{C_RESET} [{n['role'].upper()}] - {n['cores']} Core, {n['ram_gb']}G RAM "
                  f"→ {C_GREEN}~{n['speed_completed']} Ep/Jam{C_RESET} (Render) / {C_YELLOW}~{n['speed_ongoing']} Ep/Jam{C_RESET} (Ongoing)")
        print(f"{C_DIM}{'─'*77}{C_RESET}")
        print(f"{C_BOLD}🚀 TOTAL KAPASITAS CLUSTER:{C_RESET}")
        print(f"  • Rilis Cepat Ongoing : {C_YELLOW}{total_speed_ongoing:>5} Episode / Jam{C_RESET}  ({total_speed_ongoing * 24:,} Ep / Hari)")
        print(f"  • Render Full Tamat   : {C_GREEN}{total_speed_completed:>5} Episode / Jam{C_RESET}  ({total_speed_completed * 24:,} Ep / Hari)")
        print(f"  • Rata-rata Gabungan  : {C_CYAN}{C_BOLD}{avg_cluster_speed:>5} Episode / Jam{C_RESET}  ({avg_cluster_speed * 24:,} Ep / Hari)")
        print(f"\n{C_BOLD}📦 STATUS ANTREAN DATABASE SAAT INI:{C_RESET}")
        print(f"  • Batch Anime Tamat   : {queue_data['total_remaining_batches']} Judul (~{queue_data['est_completed_episodes']:,} Episode)")
        print(f"  • Resolusi Ongoing    : {queue_data['ongoing_partial_episodes']} Episode belum lengkap")
        print(f"  • {C_BOLD}Total Sisa Pengerjaan{C_RESET}: {C_MAGENTA}{C_BOLD}{total_ep:,} Episode{C_RESET}")
        print(f"\n{C_BOLD}⏱️  ESTIMASI WAKTU PENYELESAIAN (ETA):{C_RESET}")
        print(f"  • Waktu Diperlukan    : {C_GREEN}{C_BOLD}{format_eta_duration(hours_needed)}{C_RESET} (~{hours_needed} jam kerja nonstop)")
        print(f"  • Target Selesai      : {C_CYAN}{C_BOLD}{format_target_date(hours_needed)}{C_RESET}")
        print()
        return

    # MODE MESIN TERTENTU / LOKAL
    hw = detect_hardware()
    cores = args.cores if args.cores is not None else hw["cores"]
    ram_gb = args.ram if args.ram is not None else hw["ram_gb"]
    has_gpu = args.gpu if args.gpu is not None else hw["has_gpu"]
    concurrency = args.concurrency if args.concurrency is not None else calculate_recommended_concurrency(cores, ram_gb, has_gpu)

    t = estimate_throughput(cores, ram_gb, has_gpu, concurrency, network=args.network)
    avg_speed = t["ep_per_hour_avg"]
    hours_needed = round(total_ep / avg_speed, 1) if avg_speed > 0 else 0

    result = {
        "mode": "single_worker",
        "hardware": {
            "cores": cores,
            "ram_gb": ram_gb,
            "has_gpu": has_gpu,
            "concurrency": concurrency,
            "network": args.network
        },
        "throughput": t,
        "queue": queue_data,
        "hours_needed": hours_needed,
        "eta_formatted": format_eta_duration(hours_needed),
        "target_date_wib": format_target_date(hours_needed)
    }

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print_banner()
    print(f"\n{C_BOLD}⚙️  SPESIFIKASI WORKER:{C_RESET}")
    gpu_txt = f"{C_GREEN}Aktif ({hw['gpu_name']}){C_RESET}" if has_gpu else f"{C_DIM}Tidak Ada (CPU Only){C_RESET}"
    print(f"  • CPU Cores     : {C_CYAN}{cores} Cores{C_RESET}")
    print(f"  • Kapasitas RAM : {C_CYAN}{ram_gb} GB{C_RESET}")
    print(f"  • Akselerasi GPU: {gpu_txt}")
    print(f"  • Concurrency   : {C_YELLOW}{concurrency} Paralel Task{C_RESET} (Rekomendasi stabil)")
    print(f"  • Jalur Jaringan: {C_WHITE}{args.network.upper()} ({'1 Gbps Datacenter' if args.network == 'cloud' else 'Home 50-100 Mbps'}){C_RESET}")

    print(f"\n{C_BOLD}🚀 ESTIMASI KECEPATAN PENGERJAAN:{C_RESET}")
    print(f"  • Rilis Cepat Ongoing : {C_YELLOW}{t['ep_per_hour_ongoing']:>4} Ep / Jam{C_RESET}  ({t['ep_per_hour_ongoing']*24:,} Ep / Hari)")
    print(f"  • Render Full Tamat   : {C_GREEN}{t['ep_per_hour_completed']:>4} Ep / Jam{C_RESET}  ({t['ep_per_hour_completed']*24:,} Ep / Hari)")
    print(f"  • Rata-rata Campuran  : {C_CYAN}{C_BOLD}{t['ep_per_hour_avg']:>4} Ep / Jam{C_RESET}  ({t['ep_per_day_avg']:,} Ep / Hari)")

    print(f"\n{C_BOLD}📦 STATUS ANTREAN DATABASE SAAT INI:{C_RESET}")
    print(f"  • Batch Anime Tamat   : {queue_data['total_remaining_batches']} Judul (~{queue_data['est_completed_episodes']:,} Episode)")
    print(f"  • Resolusi Ongoing    : {queue_data['ongoing_partial_episodes']} Episode belum lengkap")
    print(f"  • {C_BOLD}Total Sisa Pengerjaan{C_RESET}: {C_MAGENTA}{C_BOLD}{total_ep:,} Episode{C_RESET}")

    print(f"\n{C_BOLD}⏱️  ESTIMASI WAKTU PENYELESAIAN (ETA JIKA DIKERJAKAN MESIN INI SAJA):{C_RESET}")
    print(f"  • Waktu Diperlukan    : {C_GREEN}{C_BOLD}{format_eta_duration(hours_needed)}{C_RESET} (~{hours_needed} jam kerja nonstop)")
    print(f"  • Target Selesai      : {C_CYAN}{C_BOLD}{format_target_date(hours_needed)}{C_RESET}")
    
    print(f"\n{C_DIM}💡 Tip: Gunakan argumen '--cluster' untuk melihat total kapasitas gabungan seluruh node aktif.{C_RESET}")
    print()

if __name__ == "__main__":
    main()
