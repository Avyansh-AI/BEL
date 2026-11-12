"""Stage 9 Verification Tests: Personal Intelligence & Device Ecosystem."""
import time
from sight_core.personal_ecosystem import (
    ConnectedDevice,
    DeviceEcosystem,
    MemoryEntry,
    NotificationPolicy,
    PersonalMemoryManager,
    ProactiveIntelligence,
    VoiceExperienceManager,
)


def test_stage9_memory_audit_contradiction_and_export():
    mem = PersonalMemoryManager(default_retention_days=30)
    m1 = mem.add(MemoryEntry(project_id="bel", key="theme", content="dark mode", importance=0.8))
    m2 = mem.add(MemoryEntry(project_id="bel", key="theme", content="light mode", importance=0.6))
    stale = mem.add(MemoryEntry(key="old", content="legacy", updated_at=time.time() - 40 * 86400))

    assert stale in mem.detect_outdated()
    conflicts = mem.detect_contradictions()
    assert len(conflicts) == 1
    assert mem.resolve_contradiction(m1.id, m2.id)
    assert len(mem.detect_contradictions()) == 0

    exported = mem.export_json()
    mem2 = PersonalMemoryManager()
    assert mem2.restore_json(exported) == 2
    assert len(mem2.retrieve("dark mode", project_id="bel")) >= 1


def test_stage9_proactive_devices_and_multilingual_voice():
    now = time.time()
    pro = ProactiveIntelligence(NotificationPolicy(enabled=True, quiet_hours=False))
    pro.add_deadline("V1 Release", now + 600)
    alerts = pro.evaluate_alerts(now=now)
    assert len(alerts) == 1 and alerts[0].urgency == "high"

    eco = DeviceEcosystem(discovery_permitted=False)
    dev = ConnectedDevice(device_id="lamp-1", name="Desk Lamp", kind="light", host="192.168.1.50")
    try:
        eco.discover_devices([dev])
        assert False, "Should require discovery permission"
    except PermissionError:
        pass

    eco.discovery_permitted = True
    eco.discover_devices([dev])
    token = eco.authenticate_device("lamp-1")
    res = eco.send_command("lamp-1", token, {"power": "on"})
    assert res["state"]["power"] == "on"

    voice = VoiceExperienceManager()
    en_chunks = list(voice.stream_speech_chunks("Systems ready. Standing by.", "en_bel"))
    hi_chunks = list(voice.stream_speech_chunks("सिस्टम तैयार है।", "hi_bel"))
    assert len(en_chunks) == 2 and en_chunks[0]["language"] == "en-US"
    assert len(hi_chunks) == 1 and hi_chunks[0]["language"] == "hi-IN"
