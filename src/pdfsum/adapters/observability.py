"""Observabilidad local y durable para los ejecutores de lotes.

Los eventos JSONL se sincronizan en disco con cada escritura. El report.json usa
un reemplazo atómico, evitando que una caída deje un JSON escrito parcialmente.
Las métricas usan solo la biblioteca estándar y se degradan de forma segura si
el host no expone /proc, sensores térmicos o nvidia-smi.
"""

from __future__ import annotations

import json
import math
import os
import platform
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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


def _optional_float(value: str) -> float | None:
    try:
        return float(value.strip())
    except ValueError:
        return None


def _percentile(values: list[float], percentile: float) -> float | None:
    """Calcula el percentil usando el método nearest-rank."""
    if not values:
        return None

    ordered = sorted(values)
    rank = math.ceil(percentile * len(ordered))
    index = max(0, min(rank - 1, len(ordered) - 1))
    return ordered[index]


def _average(values: list[float]) -> float | None:
    """Calcula el promedio simple sin dependencias externas."""
    if not values:
        return None
    return sum(values) / len(values)


def _throttling_by_gpu() -> dict[str, dict[str, Any]]:
    reason_fields = {
        "sw_power_cap": "clocks_event_reasons.sw_power_cap",
        "sw_thermal_slowdown": "clocks_event_reasons.sw_thermal_slowdown",
        "hw_thermal_slowdown": "clocks_event_reasons.hw_thermal_slowdown",
        "hw_power_brake_slowdown": (
            "clocks_event_reasons.hw_power_brake_slowdown"
        ),
    }

    states: dict[str, dict[str, Any]] = {}

    for reason_name, field in reason_fields.items():
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    f"--query-gpu=index,{field}",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                check=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            continue

        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",", 1)]
            if len(parts) != 2:
                continue

            index, raw_value = parts
            value = raw_value.lower()

            active = value not in {
                "0",
                "0x0000000000000000",
                "n/a",
                "not active",
            }

            gpu_state = states.setdefault(
                index,
                {
                    "active": False,
                    "reasons": [],
                },
            )

            if active:
                gpu_state["active"] = True
                gpu_state["reasons"].append(reason_name)

    return states


def _gpu_metrics() -> dict[str, Any]:
    extended_fields = (
        "index,uuid,name,utilization.gpu,memory.used,memory.total,"
        "temperature.gpu,power.draw,power.limit,fan.speed,clocks.current.sm,"
        "clocks.current.memory,pstate"
    )
    basic_fields = (
        "index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu"
    )
    result: subprocess.CompletedProcess[str] | None = None
    detail_level = "extended"
    for fields in (extended_fields, basic_fields):
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    f"--query-gpu={fields}",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                check=True,
                text=True,
                timeout=2,
            )
            detail_level = "extended" if fields == extended_fields else "basic"
            break
        except FileNotFoundError:
            return {
                "available": False,
                "error": "nvidia-smi no encontrado",
                "devices": [],
            }
        except subprocess.TimeoutExpired:
            return {
                "available": False,
                "error": "tiempo de nvidia-smi agotado",
                "devices": [],
            }
        except subprocess.SubprocessError:
            continue
    if result is None:
        return {"available": False, "error": "nvidia-smi falló", "devices": []}
    throttling = _throttling_by_gpu()
    gpus: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        values = [value.strip() for value in line.split(",")]
        expected_fields = 13 if detail_level == "extended" else 7
        if len(values) != expected_fields:
            continue
        index, uuid, name = values[:3]
        numeric = [_optional_float(value) for value in values[3:]]
        numeric += [None] * (9 - len(numeric))
        throttle_state = throttling.get(index, {})
        gpus.append(
            {
                "index": int(index) if index.isdigit() else index,
                "uuid": uuid,
                "name": name,
                "utilization_percent": numeric[0],
                "memory_used_mb": numeric[1],
                "memory_total_mb": numeric[2],
                "temperature_c": numeric[3],
                "power_draw_w": numeric[4],
                "power_limit_w": numeric[5],
                "fan_speed_percent": numeric[6],
                "clock_sm_mhz": numeric[7],
                "clock_memory_mhz": numeric[8],
                "performance_state": values[12]
                if detail_level == "extended"
                else None,
                "throttling_active": throttle_state.get("active"),
                "throttling_reasons": throttle_state.get("reasons", []),
            }
        )
    if not gpus:
        return {
            "available": False,
            "error": "nvidia-smi no devolvió GPUs",
            "devices": [],
        }
    return {"available": True, "detail_level": detail_level, "devices": gpus}


def _safe_ollama_host(host: str) -> str:
    try:
        parsed = urlsplit(host)
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        return "invalid"
    if not parsed.hostname:
        return "invalid"
    return f"{parsed.scheme or 'http'}://{parsed.hostname}{port}"


def _ollama_metrics(host: str) -> dict[str, Any]:
    safe_host = _safe_ollama_host(host)
    if not host or safe_host == "invalid":
        return {"available": False, "error": "host de Ollama no configurado"}
    endpoint = f"{host.rstrip('/')}/api/ps"
    try:
        request = urllib.request.Request(endpoint, method="GET")
        with urllib.request.urlopen(request, timeout=1) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("respuesta demasiado grande")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("respuesta inválida")
        raw_models = payload.get("models", [])
        if not isinstance(raw_models, list):
            raise ValueError("modelos inválidos")
    except urllib.error.HTTPError as exc:
        return {
            "available": False,
            "host": safe_host,
            "error": f"Ollama HTTP {exc.code}",
        }
    except (OSError, ValueError):
        return {
            "available": False,
            "host": safe_host,
            "error": "Ollama no disponible",
        }

    models: list[dict[str, Any]] = []
    for raw_model in raw_models:
        if not isinstance(raw_model, dict):
            continue
        details = raw_model.get("details", {})
        if not isinstance(details, dict):
            details = {}
        size = raw_model.get("size", 0)
        size_vram = raw_model.get("size_vram", 0)
        context_length = raw_model.get("context_length")
        models.append(
            {
                "name": str(
                    raw_model.get("name") or raw_model.get("model") or "unknown"
                ),
                "size_mb": round(size / 1024 / 1024, 3)
                if isinstance(size, (int, float))
                else None,
                "size_vram_mb": round(size_vram / 1024 / 1024, 3)
                if isinstance(size_vram, (int, float))
                else None,
                "context_length": context_length
                if isinstance(context_length, (int, float))
                else None,
                "parameter_size": details.get("parameter_size"),
                "quantization_level": details.get("quantization_level"),
                "expires_at": raw_model.get("expires_at"),
            }
        )
    return {"available": True, "host": safe_host, "models": models}


def collect_snapshot(disk_path: Path, ollama_host: str = "") -> dict[str, Any]:
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
    gpu = _gpu_metrics()
    snapshot["gpu"] = gpu
    if gpu["devices"]:
        snapshot["gpus"] = gpu["devices"]  # compatibilidad con reportes 3.0
    if ollama_host:
        snapshot["ollama"] = _ollama_metrics(ollama_host)
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

    def __init__(
        self,
        path: Path,
        disk_path: Path,
        interval: float = 5.0,
        ollama_host: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.path = path
        self.disk_path = disk_path
        self.interval = interval
        self.run_id = run_id
        metrics_enabled = os.getenv("PDFSUM_OLLAMA_METRICS", "1").lower() not in {
            "0",
            "false",
            "no",
        }
        configured_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.ollama_host = (configured_host if ollama_host is None else ollama_host)
        if not metrics_enabled:
            self.ollama_host = ""
        self.ollama_metrics_enabled = bool(self.ollama_host)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._samples: list[dict[str, Any]] = []
        self._context: dict[str, str] = {}
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

    def set_context(
        self, *, doc_id: str | None = None, phase: str | None = None
    ) -> None:
        """Asocia las próximas muestras con el documento y la fase actuales."""
        with self._lock:
            self._context = {
                key: value
                for key, value in (("doc_id", doc_id), ("phase", phase))
                if value is not None
            }

    def sample(self) -> dict[str, Any]:
        snapshot = collect_snapshot(self.disk_path, self.ollama_host)
        if not self.ollama_metrics_enabled:
            snapshot["ollama"] = {
                "available": False,
                "disabled": True,
                "error": "métricas de Ollama desactivadas",
            }
        if self.run_id is not None:
            snapshot["run_id"] = self.run_id
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
        with self._lock:
            snapshot.update(self._context)
            line = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
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


        # Memoria del proceso
        process_rss = values("process", "rss_mb")
        if process_rss:
            summary["process_rss_peak_mb"] = round(max(process_rss), 3)
        
        
        # CPU del proceso
        process_cpu = values("process", "cpu_percent")
        if process_cpu:
            average = _average(process_cpu)
            if average is not None:
                summary["process_cpu_percent_avg"] = round(average, 3)
        
            summary["process_cpu_percent_max"] = round(
                max(process_cpu),
                3,
            )
        
        
        # Memoria disponible en el host
        memory_available = values("host", "memory_available_mb")
        if memory_available:
            average = _average(memory_available)
            if average is not None:
                summary["memory_available_avg_mb"] = round(average, 3)
        
            summary["memory_available_min_mb"] = round(
                min(memory_available),
                3,
            )
        
        
        # Swap mínimo
        swap_free = values("host", "swap_free_mb")
        if swap_free:
            summary["swap_free_min_mb"] = round(
                min(swap_free),
                3,
            )
        
        
        # Disco
        disk_free = values("host", "disk_free_gb")
        if disk_free:
            summary["disk_free_min_gb"] = round(
                min(disk_free),
                3,
            )
        
        disk_used = values("host", "disk_used_percent")
        if disk_used:
            summary["disk_used_percent_max"] = round(
                max(disk_used),
                3,
            )
        
        
        # Load average
        load_1m = values("host", "load_1m")
        if load_1m:
            average = _average(load_1m)
            if average is not None:
                summary["load_1m_avg"] = round(average, 3)
        
            summary["load_1m_max"] = round(
                max(load_1m),
                3,
            )
        
        
        # CPU total del host
        host_cpu = values("host", "cpu_percent")
        if host_cpu:
            average = _average(host_cpu)
            if average is not None:
                summary["host_cpu_percent_avg"] = round(average, 3)
        
            summary["host_cpu_percent_max"] = round(
                max(host_cpu),
                3,
            )
        
        
        # Temperatura del host
        host_temperature = values("host", "temperature_max_c")
        if host_temperature:
            average = _average(host_temperature)
            if average is not None:
                summary["host_temperature_avg_c"] = round(
                    average,
                    3,
                )
        
            p95 = _percentile(host_temperature, 0.95)
            if p95 is not None:
                summary["host_temperature_p95_c"] = round(
                    p95,
                    3,
                )
        
            summary["host_temperature_max_c"] = round(
                max(host_temperature),
                3,
            )
        
        cpu_seconds = values("process", "cpu_seconds")
        if len(cpu_seconds) >= 2:
            summary["process_cpu_seconds"] = round(
                max(cpu_seconds) - min(cpu_seconds), 3
            )

        gpu_observations = [sample.get("gpu", {}) for sample in samples]
        gpus = [gpu for sample in samples for gpu in sample.get("gpus", [])]
        ollama_observations = [
            sample["ollama"] for sample in samples if "ollama" in sample
        ]
        gpu_monitoring: dict[str, Any] = {
            "nvidia_smi_available": any(
                observation.get("available", False)
                for observation in gpu_observations
            ),
            "ollama_api_available": any(
                observation.get("available", False)
                for observation in ollama_observations
            ),
            "ollama_metrics_enabled": any(
                not observation.get("disabled", False)
                for observation in ollama_observations
            ),
        }
        nvidia_errors = [
            observation.get("error")
            for observation in gpu_observations
            if observation.get("error")
        ]
        if nvidia_errors and not gpu_monitoring["nvidia_smi_available"]:
            gpu_monitoring["nvidia_smi_error"] = nvidia_errors[-1]
        detail_levels = [
            observation.get("detail_level")
            for observation in gpu_observations
            if observation.get("detail_level")
        ]
        if detail_levels:
            gpu_monitoring["nvidia_smi_detail_level"] = (
                "extended" if "extended" in detail_levels else detail_levels[-1]
            )
        ollama_errors = [
            observation.get("error")
            for observation in ollama_observations
            if observation.get("error")
        ]
        if ollama_errors and not gpu_monitoring["ollama_api_available"]:
            gpu_monitoring["ollama_error"] = ollama_errors[-1]
        ollama_hosts = [
            observation.get("host")
            for observation in ollama_observations
            if observation.get("host")
        ]
        if ollama_hosts:
            gpu_monitoring["ollama_host"] = ollama_hosts[-1]

        def gpu_values(key: str) -> list[float]:
            return [
                float(value)
                for gpu in gpus
                if isinstance((value := gpu.get(key)), (int, float))
            ]


# Uso de la GPU
        gpu_utilization = gpu_values("utilization_percent")
        if gpu_utilization:
            average = _average(gpu_utilization)
            if average is not None:
                summary["gpu_utilization_avg_percent"] = round(
                    average,
                    3,
                )
        
            p95 = _percentile(gpu_utilization, 0.95)
            if p95 is not None:
                summary["gpu_utilization_p95_percent"] = round(
                    p95,
                    3,
                )
        
            summary["gpu_utilization_max_percent"] = round(
                max(gpu_utilization),
                3,
            )
        
        
        # VRAM
        gpu_memory = gpu_values("memory_used_mb")
        if gpu_memory:
            summary["gpu_memory_peak_mb"] = round(
                max(gpu_memory),
                3,
            )
        
        
        # Temperatura de la GPU
        gpu_temperature = gpu_values("temperature_c")
        if gpu_temperature:
            average = _average(gpu_temperature)
            if average is not None:
               summary["gpu_temperature_avg_c"] = round(
                    average,
                    3,
                )
        
            summary["gpu_temperature_max_c"] = round(
                max(gpu_temperature),
                3,
            )
        
        
        # Potencia de la GPU
        gpu_power = gpu_values("power_draw_w")
        if gpu_power:
            average = _average(gpu_power)
            if average is not None:
                summary["gpu_power_draw_avg_w"] = round(
                    average,
                    3,
                )
        
            summary["gpu_power_draw_max_w"] = round(
                max(gpu_power),
                3,
            )
        
        
        # Ventilador
        gpu_fan = gpu_values("fan_speed_percent")
        if gpu_fan:
            summary["gpu_fan_speed_max_percent"] = round(
                max(gpu_fan),
                3,
            )

        device_groups: dict[str, list[dict[str, Any]]] = {}
        for gpu in gpus:
            identity = str(gpu.get("uuid") or gpu.get("index") or "unknown")
            device_groups.setdefault(identity, []).append(gpu)
        devices: list[dict[str, Any]] = []
        for identity, observations in sorted(device_groups.items()):
            first = observations[0]
            device: dict[str, Any] = {
                "id": identity,
                "index": first.get("index"),
                "name": first.get("name"),
                "throttling_observed": any(
                    gpu.get("throttling_active") is not None
                    for gpu in observations
                ),
                "throttling_detected": any(
                    gpu.get("throttling_active") is True for gpu in observations
                ),
            }

            throttling_reasons = sorted(
                {
                    reason
                    for gpu in observations
                    for reason in gpu.get("throttling_reasons", [])
                }
            )

            if throttling_reasons:
                device["throttling_reasons_seen"] = throttling_reasons

            performance_states = sorted(
                {
                    str(gpu["performance_state"])
                    for gpu in observations
                    if gpu.get("performance_state")
                }
            )
            if performance_states:
                device["performance_states_seen"] = performance_states
            for source, target in (
                ("utilization_percent", "utilization_max_percent"),
                ("memory_used_mb", "memory_peak_mb"),
                ("memory_total_mb", "memory_total_mb"),
                ("temperature_c", "temperature_max_c"),
                ("power_draw_w", "power_draw_max_w"),
                ("power_limit_w", "power_limit_w"),
                ("fan_speed_percent", "fan_speed_max_percent"),
                ("clock_sm_mhz", "clock_sm_max_mhz"),
                ("clock_memory_mhz", "clock_memory_max_mhz"),
            ):
                found = [
                    value
                    for gpu in observations
                    if isinstance((value := gpu.get(source)), (int, float))
                ]
                if found:
                    device[target] = round(max(found), 3)
            devices.append(device)
        if devices:
            gpu_monitoring["devices"] = devices
            gpu_monitoring["throttling_detected"] = any(
                device["throttling_detected"] for device in devices
            )

        ollama_models: dict[str, list[dict[str, Any]]] = {}
        ollama_vram_totals: list[float] = []
        for observation in ollama_observations:
            models = observation.get("models", [])
            total_vram = 0.0
            for model in models:
                name = str(model.get("name", "unknown"))
                ollama_models.setdefault(name, []).append(model)
                size_vram = model.get("size_vram_mb")
                if isinstance(size_vram, (int, float)):
                    total_vram += size_vram
            ollama_vram_totals.append(total_vram)
        if ollama_vram_totals:
            gpu_monitoring["ollama_vram_loaded_peak_mb"] = round(
                max(ollama_vram_totals), 3
            )
        if ollama_models:
            gpu_monitoring["ollama_models"] = [
                {
                    "name": name,
                    "vram_peak_mb": round(
                        max(
                            model.get("size_vram_mb", 0) or 0
                            for model in observations
                        ),
                        3,
                    ),
                    "context_length_max": max(
                        model.get("context_length", 0) or 0
                        for model in observations
                    ),
                    "parameter_size": observations[-1].get("parameter_size"),
                    "quantization_level": observations[-1].get(
                        "quantization_level"
                    ),
                }
                for name, observations in sorted(ollama_models.items())
            ]
        summary["gpu_monitoring"] = gpu_monitoring
        return summary
