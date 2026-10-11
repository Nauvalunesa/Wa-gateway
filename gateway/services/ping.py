"""Live server information for the WhatsApp ping response."""
import asyncio
import json
import os
from pathlib import Path
import platform
import shutil
import time

from gateway.config import PROJECT_ROOT

STARTED_AT = time.monotonic()
GIB = 1024 ** 3
preferences: dict[str, bool] = {}


def ping_enabled(username: str) -> bool:
    if username not in preferences:
        path = Path("storage") / username / "config" / "ping.json"
        try:
            enabled = json.loads(path.read_text())["enabled"]
            if not isinstance(enabled, bool):
                raise ValueError("Invalid ping preference")
            preferences[username] = enabled
        except FileNotFoundError:
            preferences[username] = True
        except (OSError, ValueError, KeyError, TypeError):
            preferences[username] = False
    return preferences[username]


def save_ping_enabled(username: str, enabled: bool):
    path = Path("storage") / username / "config" / "ping.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as target:
        json.dump({"enabled": enabled}, target)
        target.flush()
        os.fsync(target.fileno())
    temporary.replace(path)
    preferences[username] = enabled


def _read(path: str) -> str:
    try:
        return Path(path).read_text()
    except (OSError, UnicodeError):
        return ""


def _duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{days} hari {hours:02d}:{minutes:02d}:{seconds:02d}"


def process_memory_details() -> list[str]:
    """Read this process, including native Neonize allocations, from Linux procfs."""
    values = {}
    for line in _read("/proc/self/status").splitlines():
        label, _, raw = line.partition(":")
        parts = raw.split()
        try:
            if label == "Threads":
                count = int(parts[0])
                if count >= 0:
                    values[label] = str(count)
            elif label in ("VmRSS", "VmHWM", "VmSize", "RssAnon", "VmSwap") and parts[1] == "kB":
                size = int(parts[0])
                if size >= 0:
                    values[label] = f"{size / 1024:.1f}MiB"
        except (ValueError, IndexError):
            continue
    fields = [("rss", "VmRSS"), ("rssPeak", "VmHWM"), ("virtual", "VmSize"),
              ("anonymous", "RssAnon"), ("swap", "VmSwap"), ("threads", "Threads")]
    lines = ["", "ᯓ *MEMORY USAGE* ᯓ"]
    lines.extend(f"⊹ *{label}*: {values.get(field, 'Tidak tersedia')}" for label, field in fields)
    lines.extend(f"⊹ *{label}*: N/A" for label in ("heapTotal", "heapUsed", "external", "arrayBuffers"))
    lines.append("N/A: metrik Node.js/V8; proses bot ini memakai Python. RSS mencakup memori proses bot dan library native.")
    return lines


def server_details() -> list[str]:
    """Read local metrics without shell commands or a blocking CPU sample."""
    cpu = platform.machine() or "Tidak tersedia"
    for line in _read("/proc/cpuinfo").splitlines():
        label, _, value = line.partition(":")
        if label.strip() in ("model name", "Hardware") and value.strip():
            cpu = value.strip()
            break
    memory = {}
    for line in _read("/proc/meminfo").splitlines():
        label, _, value = line.partition(":")
        try:
            memory[label] = int(value.split()[0]) * 1024
        except (ValueError, IndexError):
            continue
    total = memory.get("MemTotal", 0)
    available = memory.get("MemAvailable", memory.get("MemFree", 0))
    ram = f"{max(0, total-available)/GIB:.2f} / {total/GIB:.2f} GiB terpakai" if total else "Tidak tersedia"
    try:
        disk = shutil.disk_usage(PROJECT_ROOT)
        disk_text = f"{disk.used/GIB:.2f} / {disk.total/GIB:.2f} GiB terpakai"
    except OSError:
        disk_text = "Tidak tersedia"
    try:
        load = " / ".join(f"{value:.2f}" for value in os.getloadavg())
    except (OSError, AttributeError):
        load = "Tidak tersedia"
    uptime = _read("/proc/uptime").split()
    try:
        system_uptime = _duration(float(uptime[0]))
    except (ValueError, IndexError):
        system_uptime = "Tidak tersedia"
    return [
        f"OS: {platform.system()} {platform.release()} ({platform.machine()})",
        f"CPU: {cpu}",
        f"CPU logis: {os.cpu_count() or 'Tidak tersedia'}",
        f"RAM server: {ram}",
        f"Disk aplikasi: {disk_text}",
        f"Load CPU (1/5/15 menit): {load}",
        f"Uptime server: {system_uptime}",
        f"Uptime bot: {_duration(time.monotonic()-STARTED_AT)}",
        f"Python: {platform.python_version()}",
    ] + process_memory_details()


async def build_ping_reply(started_at: float) -> str:
    details = await asyncio.to_thread(server_details)
    elapsed_ms = max(0, (time.perf_counter()-started_at)*1000)
    return "pong! 🏓\n\n" + f"⚡ Proses respons: {elapsed_ms:.2f} ms\n" + "\n".join(details) + "\n\nWaktu dihitung sejak event diterima sampai balasan disiapkan, sebelum pengiriman WhatsApp."
