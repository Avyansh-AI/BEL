import pytest
from sight_core.system_monitor import SystemMonitor, monitor


def test_system_monitor_ram():
    ram = monitor.get_ram()
    assert "total_mb" in ram and "available_mb" in ram and "used_mb" in ram and "percent" in ram
    assert ram["total_mb"] > 0
    assert ram["available_mb"] > 0
    assert ram["available_mb"] <= ram["total_mb"]
    assert 0.0 <= ram["percent"] <= 100.0


def test_system_monitor_cpu():
    cpu = monitor.get_cpu()
    assert "percent" in cpu
    assert 0.0 <= cpu["percent"] <= 100.0


def test_system_monitor_gpu():
    gpu = monitor.get_gpu()
    assert "available" in gpu
    assert "name" in gpu
    assert "total_vram_mb" in gpu
    assert "free_vram_mb" in gpu
    assert "used_vram_mb" in gpu
    assert "percent" in gpu
    if gpu["available"]:
        assert gpu["total_vram_mb"] > 0
        assert gpu["free_vram_mb"] <= gpu["total_vram_mb"]


def test_system_monitor_telemetry():
    t = monitor.get_telemetry()
    assert "ram" in t and "cpu" in t and "gpu" in t
    assert "safe_for_inference" in t
    assert isinstance(t["safe_for_inference"], bool)
    assert t["timestamp"] > 0


def test_memory_safety_check_pass():
    # 10 MiB is guaranteed to be available on any running machine
    safe, reason = monitor.check_memory_safety(min_ram_mb=10, min_vram_mb=10)
    assert safe is True
    assert "safe" in reason.lower()


def test_memory_safety_check_load_shedding():
    # 10,000,000 MiB (10 TB) RAM is guaranteed to fail and trigger load shedding
    safe, reason = monitor.check_memory_safety(min_ram_mb=10_000_000)
    assert safe is False
    assert "below required safety floor" in reason


def test_non_windows_fallback(monkeypatch):
    sm = SystemMonitor()
    sm.is_windows = False
    sm._kernel = None
    sm._nvml = None
    sm._nvml_initialized = False

    ram = sm.get_ram()
    assert ram["total_mb"] > 0
    cpu = sm.get_cpu()
    assert cpu["percent"] == 0.0
    gpu = sm.get_gpu()
    assert gpu["available"] is False


def test_system_telemetry_endpoint(client):
    res = client.get("/api/system/telemetry")
    assert res.status_code == 200
    data = res.json()
    assert "ram" in data and "cpu" in data and "gpu" in data
    assert "safe_for_inference" in data
    assert data["ram"]["total_mb"] > 0
