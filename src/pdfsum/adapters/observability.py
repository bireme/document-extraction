"""Observabilidad local y durable para los ejecutores de lotes.

Los eventos JSONL se sincronizan en disco con cada escritura. El report.json usa
un reemplazo atómico, evitando que una caída deje un JSON escrito parcialmente.
Las métricas usan solo la biblioteca estándar y se degradan de forma segura si
el host no expone /proc, sensores térmicos o nvidia-smi.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_directory(path: Path) -> None:
    """Sincroniza los metadatos del directorio si la plataforma lo permite."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Escribe el JSON completo y lo publica mediante un renombrado atómico."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


class EventLog:
    """Log JSONL append-only; cada registro se vacía y sincroniza en disco."""

    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self._lock = threading.Lock()

    def write(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp": utc_now(),
            "run_id": self.run_id,
            "event": event,
            **fields,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())


def _read_key_values(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            token = raw.strip().split()[0]
            values[key] = int(token) * 1024
    except (OSError, ValueError, IndexError):
        return {}
    return values


def _process_rss_bytes() -> int | None:
    try:
        pages = int(Path("/proc/self/statm").read_text().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        if resource is None:
            return None
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if not usage:
            return None
        # Linux informa KiB; macOS informa bytes.
        return int(usage * 1024 if platform.system() == "Linux" else usage)


def _cpu_temperature() -> float | None:
    candidates = list(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
    candidates += list(Path("/sys/class/hwmon").glob("hwmon*/temp*_input"))
    readings: list[float] = []
    for sensor in candidates:
        try:
            value = float(sensor.read_text().strip())
        except (OSError, ValueError):
            continue
        celsius = value / 1000 if abs(value) > 1000 else value
        if -20 <= celsius <= 200:
            readings.append(celsius)
    return max(readings) if readings else None


def _gpu_metrics() -> list[dict[str, float]]:
    command = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    gpus: list[dict[str, float]] = []
    for line in result.stdout.splitlines():
        try:
            utilization, used, total, temperature = (
                float(value.strip()) for value in line.split(",")
            )
        except (ValueError, TypeError):
            continue
        gpus.append(
            {
                "utilization_percent": utilization,
                "memory_used_mb": used,
                "memory_total_mb": total,
                "temperature_c": temperature,
            }
        )
    return gpus


def collect_snapshot(disk_path: Path) -> dict[str, Any]:
    """Recopila una muestra portátil, omitiendo métricas no disponibles."""
    process: dict[str, Any] = {
        "cpu_seconds": round(time.process_time(), 6),
        "threads": threading.active_count(),
    }
    rss = _process_rss_bytes()
    if rss is not None:
        process["rss_mb"] = round(rss / 1024 / 1024, 3)

    host: dict[str, Any] = {"cpu_count": os.cpu_count()}
    try:
        load_1m, load_5m, load_15m = os.getloadavg()
        host.update(
            {
                "load_1m": round(load_1m, 3),
                "load_5m": round(load_5m, 3),
                "load_15m": round(load_15m, 3),
            }
        )
    except OSError:
        pass
    memory = _read_key_values(Path("/proc/meminfo"))
    for source, target in (
        ("MemTotal", "memory_total_mb"),
        ("MemAvailable", "memory_available_mb"),
        ("SwapTotal", "swap_total_mb"),
        ("SwapFree", "swap_free_mb"),
    ):
        if source in memory:
            host[target] = round(memory[source] / 1024 / 1024, 3)
    try:
        disk = shutil.disk_usage(disk_path)
        host["disk_free_gb"] = round(disk.free / 1024**3, 3)
        host["disk_used_percent"] = round(disk.used / disk.total * 100, 3)
    except OSError:
        pass
    temperature = _cpu_temperature()
    if temperature is not None:
        host["temperature_max_c"] = round(temperature, 2)

    snapshot: dict[str, Any] = {
        "timestamp": utc_now(),
        "process": process,
        "host": host,
    }
    gpus = _gpu_metrics()
    if gpus:
        snapshot["gpus"] = gpus
    return snapshot


def _host_cpu_counters() -> tuple[int, int] | None:
    """Devuelve (total, idle) de /proc/stat para calcular entre muestras."""
    try:
        fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
        ticks = [int(value) for value in fields.split()[1:]]
    except (OSError, ValueError, IndexError):
        return None
    if len(ticks) < 4:
        return None
    idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
    return sum(ticks), idle


class InfrastructureMonitor:
    """Muestrea infraestructura en segundo plano y mantiene máximos/mínimos."""

    def __init__(self, path: Path, disk_path: Path, interval: float = 5.0) -> None:
        self.path = path
        self.disk_path = disk_path
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._samples: list[dict[str, Any]] = []
        self._last_process_cpu: float | None = None
        self._last_monotonic: float | None = None
        self._last_host_cpu: tuple[int, int] | None = None

    def start(self) -> None:
        self.sample()
        self._thread = threading.Thread(
            target=self._run,
            name="pdfsum-infrastructure-monitor",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self.sample()

    def sample(self) -> dict[str, Any]:
        snapshot = collect_snapshot(self.disk_path)
        now = time.monotonic()
        process_cpu = snapshot["process"]["cpu_seconds"]
        host_cpu = _host_cpu_counters()
        if self._last_process_cpu is not None and self._last_monotonic is not None:
            elapsed = now - self._last_monotonic
            if elapsed > 0:
                snapshot["process"]["cpu_percent"] = round(
                    (process_cpu - self._last_process_cpu) / elapsed * 100, 3
                )
        if host_cpu is not None and self._last_host_cpu is not None:
            total_delta = host_cpu[0] - self._last_host_cpu[0]
            idle_delta = host_cpu[1] - self._last_host_cpu[1]
            if total_delta > 0:
                snapshot["host"]["cpu_percent"] = round(
                    (total_delta - idle_delta) / total_delta * 100, 3
                )
        self._last_process_cpu = process_cpu
        self._last_monotonic = now
        self._last_host_cpu = host_cpu
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._samples.append(snapshot)
        return snapshot

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval + 1.0))
        self.sample()

    def summary(self) -> dict[str, Any]:
        with self._lock:
            samples = list(self._samples)
        summary: dict[str, Any] = {"sample_count": len(samples)}

        def values(section: str, key: str) -> list[float]:
            return [
                sample[section][key]
                for sample in samples
                if key in sample.get(section, {})
            ]

        mappings = (
            ("process", "rss_mb", "process_rss_peak_mb", max),
            ("process", "cpu_percent", "process_cpu_percent_max", max),
            ("host", "memory_available_mb", "memory_available_min_mb", min),
            ("host", "swap_free_mb", "swap_free_min_mb", min),
            ("host", "disk_free_gb", "disk_free_min_gb", min),
            ("host", "disk_used_percent", "disk_used_percent_max", max),
            ("host", "load_1m", "load_1m_max", max),
            ("host", "cpu_percent", "host_cpu_percent_max", max),
            ("host", "temperature_max_c", "host_temperature_max_c", max),
        )
        for section, key, output, aggregate in mappings:
            found = values(section, key)
            if found:
                summary[output] = round(aggregate(found), 3)

        cpu_seconds = values("process", "cpu_seconds")
        if len(cpu_seconds) >= 2:
            summary["process_cpu_seconds"] = round(
                max(cpu_seconds) - min(cpu_seconds), 3
            )

        gpus = [gpu for sample in samples for gpu in sample.get("gpus", [])]
        if gpus:
            summary.update(
                {
                    "gpu_utilization_max_percent": max(
                        gpu["utilization_percent"] for gpu in gpus
                    ),
                    "gpu_memory_peak_mb": max(gpu["memory_used_mb"] for gpu in gpus),
                    "gpu_temperature_max_c": max(
                        gpu["temperature_c"] for gpu in gpus
                    ),
                }
            )
        return summary
