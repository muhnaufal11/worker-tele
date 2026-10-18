#!/usr/bin/env python3
"""
Smart Anti-Stuck & Auto-Debug Engine for Nipnime Worker Cluster
==============================================================
Based on Zero-Delta Velocity Tracking:
Memantau pergerakan data nyata (bytes, frame, progress), BUKAN sekadar timeout kaku.
Jika delta == 0 melewati ambang batas:
1. Rekam lokasi baris kode yang stuck via stacktrace coroutine.
2. Auto-kill subprocess yang macet (ffmpeg, 7z).
3. Batalkan asyncio Task yang menggantung agar loop bisa auto-heal/retry.
4. Kirim laporan insiden ke Halaman Admin Nipnime.
"""

import os
import sys
import time
import asyncio
import traceback
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List

try:
    import psutil
except ImportError:
    psutil = None


class SmartWorkerDebugger:
    """
    Sistem Pintar Anti-Stuck & Auto-Debug untuk memantau seluruh aktivitas worker:
    - Download Sumber / Vault (HTTP / Pixeldrain / Acefile / GDrive / Telegram CDN)
    - Ekstraksi Arsip Batch (7z / unrar / tar)
    - Render Video FFmpeg (Mode 1 Turbo / Mode 2 Eco / Mode 3 Ultra-Slow / CPU Fallback)
    - Upload Telegram MTProto
    """
    def __init__(self, worker_id: str, api_report_callback: Optional[Callable[[Dict[str, Any]], Any]] = None):
        self.worker_id = worker_id
        self.api_report_callback = api_report_callback
        self.current_phase: str = "idle"
        self.current_context: Dict[str, Any] = {}
        self.active_task: Optional[asyncio.Task] = None
        self.active_subprocess_pid: Optional[int] = None
        self.watched_file_path: Optional[Path] = None

        # Pelacak Pergerakan Data (Zero-Delta Velocity Tracker)
        self.last_progress_value: float = 0.0
        self.last_delta_timestamp: float = time.time()
        self.phase_start_timestamp: float = time.time()
        self.velocity_str: str = "idle"
        self.stuck_incidents_log: List[Dict[str, Any]] = []

        # Ambang batas toleransi 0 pergerakan (detik) per kategori (sesuai PRD)
        self.zero_delta_thresholds: Dict[str, int] = {
            "downloading_source": 75,
            "securing_file": 75,
            "extracting_batch": 60,
            "rendering_ffmpeg": 90,
            "uploading_telegram": 90,
            "worker_main_loop": 120,
        }

        self.check_interval: float = 5.0
        self._running: bool = True
        self._watchdog_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def start_watchdog_task(self):
        """Memulai loop watchdog jika belum berjalan."""
        if self._watchdog_task is None or self._watchdog_task.done():
            self._running = True
            self._watchdog_task = asyncio.create_task(self.watchdog_loop())

    def stop_watchdog_task(self):
        """Menghentikan loop watchdog."""
        self._running = False
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()

    def start_watching(
        self,
        phase: str,
        context: Optional[Dict[str, Any]] = None,
        task: Optional[asyncio.Task] = None,
        subprocess_pid: Optional[int] = None,
        watched_file: Optional[Path] = None
    ):
        """Dipanggil setiap kali worker memulai tahap download, ekstrak, render, atau upload."""
        now = time.time()
        self.current_phase = phase
        self.current_context = context or {}
        self.active_task = task
        self.active_subprocess_pid = subprocess_pid
        self.watched_file_path = watched_file
        self.last_progress_value = 0.0
        self.last_delta_timestamp = now
        self.phase_start_timestamp = now
        self.velocity_str = "starting..."
        self.start_watchdog_task()

    def beat_progress(self, current_value: float, unit_label: str = "MB"):
        """
        Dipanggil oleh callback download, FFmpeg progress, atau upload Telegram.
        Jika nilai bertambah (delta > 0), timer anti-stuck di-reset!
        """
        now = time.time()
        delta = current_value - self.last_progress_value
        if delta > 0:
            elapsed = max(0.1, now - self.last_delta_timestamp)
            speed = delta / elapsed
            self.velocity_str = f"{speed:.2f} {unit_label}/s"
            self.last_progress_value = current_value
            self.last_delta_timestamp = now

    def stop_watching(self):
        """Dipanggil saat tahap selesai dengan normal."""
        self.current_phase = "idle"
        self.current_context = {}
        self.active_task = None
        self.active_subprocess_pid = None
        self.watched_file_path = None
        self.velocity_str = "idle"

    def get_status_summary(self) -> Dict[str, Any]:
        """Mengembalikan metrik velocity dan status debug untuk heartbeat telemetri."""
        now = time.time()
        zero_delta_sec = round(now - self.last_delta_timestamp, 1) if self.current_phase != "idle" else 0
        step_elapsed = round(now - self.phase_start_timestamp, 1) if self.current_phase != "idle" else 0
        return {
            "current_phase": self.current_phase,
            "velocity_metric": self.velocity_str,
            "last_delta_age_sec": zero_delta_sec,
            "step_elapsed_sec": step_elapsed,
            "health_status": "healthy" if zero_delta_sec < self.zero_delta_thresholds.get(self.current_phase, 90) else "stuck",
            "last_progress_value": round(self.last_progress_value, 2),
            "incidents_count": len(self.stuck_incidents_log),
        }

    def _capture_coroutine_stack(self) -> str:
        """Mengambil baris kode persis di mana fungsi async sedang nyangkut/stuck."""
        if not self.active_task:
            return "No active asyncio.Task attached."
        try:
            frames = self.active_task.get_stack(limit=5)
            lines = []
            for f in frames:
                lines.append(f"File '{f.f_code.co_filename}', line {f.f_lineno}, in {f.f_code.co_name}")
            return " -> ".join(lines) if lines else "Empty stack"
        except Exception as e:
            return f"Stack capture error: {e}"

    def _kill_hung_process_tree(self, pid: int) -> str:
        """Membunuh subprocess (ffmpeg / 7z) beserta seluruh child process-nya yang macet."""
        if psutil is None:
            try:
                os.kill(pid, 9)
                return f"Killed hung PID {pid} via os.kill"
            except Exception as e:
                return f"Failed killing PID {pid}: {e}"
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except Exception:
                    pass
            parent.kill()
            return f"Killed hung PID {pid} (+{len(children)} children)"
        except psutil.NoSuchProcess:
            return f"PID {pid} already terminated"
        except Exception as e:
            return f"Failed killing PID {pid}: {e}"

    async def watchdog_loop(self):
        """Loop latar belakang yang memeriksa apakah ada proses yang stuck setiap interval."""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)
                if self.current_phase == "idle":
                    continue

                now = time.time()

                # Cek juga apakah ukuran file di disk bertambah (sebagai cadangan jika callback tidak terpanggil)
                if self.watched_file_path and self.watched_file_path.exists():
                    try:
                        disk_mb = self.watched_file_path.stat().st_size / (1024 * 1024)
                        if disk_mb > self.last_progress_value:
                            self.beat_progress(disk_mb, "MB")
                    except Exception:
                        pass

                zero_delta_sec = now - self.last_delta_timestamp
                max_allowed_sec = self.zero_delta_thresholds.get(self.current_phase, 90)

                if zero_delta_sec >= max_allowed_sec:
                    # 🚨 PROSES TERDETEKSI STUCK! Jalankan Auto-Debug & Auto-Heal!
                    stack_info = self._capture_coroutine_stack()
                    proc_action = "None"
                    if self.active_subprocess_pid:
                        proc_action = self._kill_hung_process_tree(self.active_subprocess_pid)

                    stuck_task = self.active_task
                    stuck_phase = self.current_phase
                    stuck_ctx = dict(self.current_context)

                    incident = {
                        "timestamp": int(now),
                        "worker_id": self.worker_id,
                        "stuck_phase": stuck_phase,
                        "zero_delta_duration_sec": round(zero_delta_sec, 1),
                        "last_progress_val": round(self.last_progress_value, 2),
                        "context": stuck_ctx,
                        "stuck_code_location": stack_info,
                        "recovery_action_taken": f"Cancelled stalled task & {proc_action}",
                    }
                    self.stuck_incidents_log.append(incident)
                    self.stuck_incidents_log = self.stuck_incidents_log[-50:]

                    # Reset state aktif agar tidak re-trigger di loop berikutnya
                    self.stop_watching()

                    if stuck_task and not stuck_task.done():
                        stuck_task.cancel()

                    # Kirim laporan peringatan & diagnosis ke Halaman Admin
                    if self.api_report_callback:
                        try:
                            res = self.api_report_callback(incident)
                            if asyncio.iscoroutine(res):
                                await res
                        except Exception as e:
                            print(f"[SmartDebugger] Gagal kirim laporan insiden: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[SmartDebugger] Error di watchdog_loop: {e}")
                await asyncio.sleep(5)
