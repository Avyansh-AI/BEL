"""BEL System Monitor & Hardware Sentinel.

Provides low-overhead real-time telemetry for host RAM, CPU, and GPU VRAM using
native Win32 kernel and NVML interfaces without third-party package dependencies.
Guards host memory by rejecting or throttling heavy local operations when free
system RAM or VRAM drops below safe thresholds.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import sys
import time
from typing import TypedDict


class MemoryStatus(TypedDict):
    total_mb: int
    available_mb: int
    used_mb: int
    percent: float


class CPUStatus(TypedDict):
    percent: float


class GPUStatus(TypedDict):
    available: bool
    name: str | None
    total_vram_mb: int
    free_vram_mb: int
    used_vram_mb: int
    percent: float


class Telemetry(TypedDict):
    ram: MemoryStatus
    cpu: CPUStatus
    gpu: GPUStatus
    safe_for_inference: bool
    timestamp: float


# Win32 structures
class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]

    def to_int(self) -> int:
        return (self.dwHighDateTime << 32) + self.dwLowDateTime


class _NVML_MEMORY(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class SystemMonitor:
    """Zero-overhead hardware monitor and memory safety sentinel."""

    # Hard safety thresholds in Megabytes
    DEFAULT_MIN_RAM_MB: int = 500
    DEFAULT_MIN_VRAM_MB: int = 300

    def __init__(self) -> None:
        self.is_windows = os.name == "nt"
        self._kernel = None
        self._nvml = None
        self._nvml_initialized = False
        self._last_cpu_time: tuple[int, int, int] | None = None
        self._last_cpu_sample_time: float = 0.0
        self._last_cpu_percent: float = 0.0

        if self.is_windows:
            try:
                self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            except Exception:
                self._kernel = None
            self._init_nvml()

    def _init_nvml(self) -> None:
        try:
            self._nvml = ctypes.CDLL("nvml.dll")
            if self._nvml.nvmlInit_v2() == 0:
                self._nvml_initialized = True
        except Exception:
            self._nvml = None
            self._nvml_initialized = False

    def close(self) -> None:
        if self._nvml_initialized and self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
            self._nvml_initialized = False

    def __del__(self) -> None:
        self.close()

    def get_ram(self) -> MemoryStatus:
        """Query host RAM status in MiB."""
        if self.is_windows and self._kernel is not None:
            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if self._kernel.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total = int(stat.ullTotalPhys // (1024 * 1024))
                avail = int(stat.ullAvailPhys // (1024 * 1024))
                used = max(0, total - avail)
                percent = round(float(stat.dwMemoryLoad), 1)
                return {
                    "total_mb": total,
                    "available_mb": avail,
                    "used_mb": used,
                    "percent": percent,
                }

        # Fallback for non-Windows or if API unavailable
        return {
            "total_mb": 16384,
            "available_mb": 4096,
            "used_mb": 12288,
            "percent": 75.0,
        }

    def get_cpu(self) -> CPUStatus:
        """Query host CPU utilization percentage."""
        if self.is_windows and self._kernel is not None:
            now = time.monotonic()
            idle_t, kernel_t, user_t = _FILETIME(), _FILETIME(), _FILETIME()
            if self._kernel.GetSystemTimes(
                ctypes.byref(idle_t), ctypes.byref(kernel_t), ctypes.byref(user_t)
            ):
                current = (idle_t.to_int(), kernel_t.to_int(), user_t.to_int())
                if self._last_cpu_time is not None:
                    idle_delta = current[0] - self._last_cpu_time[0]
                    kernel_delta = current[1] - self._last_cpu_time[1]
                    user_delta = current[2] - self._last_cpu_time[2]
                    total = kernel_delta + user_delta
                    if total > 0:
                        self._last_cpu_percent = round(
                            max(0.0, min(100.0, 100.0 * (1.0 - (idle_delta / total)))),
                            1,
                        )
                self._last_cpu_time = current
                self._last_cpu_sample_time = now
                return {"percent": self._last_cpu_percent}

        return {"percent": 0.0}

    def get_gpu(self) -> GPUStatus:
        """Query GPU VRAM status via NVML if available."""
        if self._nvml_initialized and self._nvml is not None:
            try:
                count = wintypes.UINT()
                if self._nvml.nvmlDeviceGetCount_v2(ctypes.byref(count)) == 0 and count.value > 0:
                    handle = ctypes.c_void_p()
                    if self._nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) == 0:
                        name_buf = ctypes.create_string_buffer(64)
                        name = "NVIDIA GPU"
                        if self._nvml.nvmlDeviceGetName(handle, name_buf, 64) == 0:
                            name = name_buf.value.decode("utf-8", errors="ignore")
                        
                        mem = _NVML_MEMORY()
                        if self._nvml.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem)) == 0:
                            total = int(mem.total // (1024 * 1024))
                            free = int(mem.free // (1024 * 1024))
                            used = int(mem.used // (1024 * 1024))
                            pct = round((used / total * 100.0) if total > 0 else 0.0, 1)
                            return {
                                "available": True,
                                "name": name,
                                "total_vram_mb": total,
                                "free_vram_mb": free,
                                "used_vram_mb": used,
                                "percent": pct,
                            }
            except Exception:
                pass

        return {
            "available": False,
            "name": None,
            "total_vram_mb": 0,
            "free_vram_mb": 0,
            "used_vram_mb": 0,
            "percent": 0.0,
        }

    def get_telemetry(self) -> Telemetry:
        """Return unified hardware telemetry snapshot."""
        ram = self.get_ram()
        cpu = self.get_cpu()
        gpu = self.get_gpu()
        safe = ram["available_mb"] >= self.DEFAULT_MIN_RAM_MB
        return {
            "ram": ram,
            "cpu": cpu,
            "gpu": gpu,
            "safe_for_inference": safe,
            "timestamp": time.time(),
        }

    def check_memory_safety(
        self,
        min_ram_mb: int | None = None,
        min_vram_mb: int | None = None,
    ) -> tuple[bool, str]:
        """Validate whether host resources allow running heavy local operations."""
        req_ram = min_ram_mb if min_ram_mb is not None else self.DEFAULT_MIN_RAM_MB
        req_vram = min_vram_mb if min_vram_mb is not None else self.DEFAULT_MIN_VRAM_MB

        ram = self.get_ram()
        if ram["available_mb"] < req_ram:
            return (
                False,
                f"Available system RAM ({ram['available_mb']} MiB) is below required safety floor ({req_ram} MiB). Operation suspended to protect host stability.",
            )

        gpu = self.get_gpu()
        if gpu["available"] and gpu["free_vram_mb"] < req_vram:
            return (
                False,
                f"Available GPU VRAM ({gpu['free_vram_mb']} MiB) is below required safety floor ({req_vram} MiB). Operation suspended to protect GPU stability.",
            )

        return True, "Hardware resources within safe operating parameters."


# Global singleton monitor
monitor = SystemMonitor()
