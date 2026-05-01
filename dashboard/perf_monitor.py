"""
Performance Monitor – In CPU/RAM ra terminal.
Bật/tắt qua API hoặc gọi trực tiếp: perf_monitor.start() / perf_monitor.stop()
"""
import threading
import time
import os
import sys

try:
    import psutil
except ImportError:
    psutil = None

# ── State ──
_running = False
_thread = None
_interval = 5        # giây giữa mỗi lần in
_process = None


def _get_process():
    global _process
    if _process is None and psutil:
        _process = psutil.Process(os.getpid())
    return _process


def _fmt_bytes(b):
    """Chuyển bytes → MB"""
    return f"{b / 1024 / 1024:.1f}"


def _monitor_loop():
    global _running
    proc = _get_process()
    if not proc:
        print("[PerfMon] ❌ psutil không khả dụng. pip install psutil")
        _running = False
        return

    print(f"[PerfMon] ▶ Bắt đầu giám sát (interval={_interval}s)")
    print(f"[PerfMon]   PID={proc.pid}")
    print(f"{'─'*70}")

    while _running:
        try:
            # CPU của process (%)
            cpu_proc = proc.cpu_percent(interval=0)

            # Memory của process
            mem = proc.memory_info()
            rss = mem.rss           # Resident Set Size – bộ nhớ thực dùng
            vms = mem.vms           # Virtual Memory Size

            # Threads count
            threads = proc.num_threads()

            # System totals
            cpu_sys = psutil.cpu_percent(interval=0)
            mem_sys = psutil.virtual_memory()

            ts = time.strftime("%H:%M:%S")

            line = (
                f"[PerfMon {ts}] "
                f"CPU: {cpu_proc:5.1f}% (sys {cpu_sys:.0f}%) │ "
                f"RAM: {_fmt_bytes(rss)}MB (vms {_fmt_bytes(vms)}MB) │ "
                f"Sys RAM: {mem_sys.percent:.0f}% │ "
                f"Threads: {threads}"
            )
            print(line, flush=True)

        except Exception as e:
            print(f"[PerfMon] ⚠ Lỗi: {e}", flush=True)

        time.sleep(_interval)

    print(f"[PerfMon] ⏹ Đã dừng giám sát")


def start(interval=5):
    """Bật monitor. interval = giây giữa mỗi lần in."""
    global _running, _thread, _interval
    if _running:
        print("[PerfMon] Đang chạy rồi.")
        return False
    if not psutil:
        print("[PerfMon] ❌ Cần cài psutil: pip install psutil")
        return False

    _interval = interval
    _running = True
    _thread = threading.Thread(target=_monitor_loop, daemon=True, name="PerfMonitor")
    _thread.start()
    return True


def stop():
    """Tắt monitor."""
    global _running, _thread
    if not _running:
        print("[PerfMon] Chưa chạy.")
        return False
    _running = False
    if _thread:
        _thread.join(timeout=_interval + 1)
        _thread = None
    return True


def is_running():
    return _running


def get_snapshot():
    """Trả về dict snapshot hiện tại (dùng cho API)."""
    proc = _get_process()
    if not proc or not psutil:
        return {"error": "psutil not available"}

    try:
        mem = proc.memory_info()
        mem_sys = psutil.virtual_memory()
        return {
            "running": _running,
            "pid": proc.pid,
            "cpu_process": round(proc.cpu_percent(interval=0), 1),
            "cpu_system": round(psutil.cpu_percent(interval=0), 1),
            "ram_rss_mb": round(mem.rss / 1024 / 1024, 1),
            "ram_vms_mb": round(mem.vms / 1024 / 1024, 1),
            "ram_system_pct": round(mem_sys.percent, 1),
            "threads": proc.num_threads(),
        }
    except Exception as e:
        return {"error": str(e)}
