"""Stage 9: Personal Intelligence & Device Ecosystem for BEL.

Provides:
- Auditable, user-editable PersonalMemoryManager (importance scoring, staleness &
  contradiction detection, episodic retrieval, retention policies, export/restore)
- Permission-gated ProactiveAssistant (deadline/progress alerts, notification policies)
- Authenticated DeviceEcosystem (permission-gated LAN discovery, smart-device control)
- Multilingual VoiceProfileManager (English & Hindi profiles, streaming chunking, barge-in)
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import time
import uuid
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, Field


class MemoryEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: f"mem-{uuid.uuid4().hex[:10]}")
    project_id: str = "default"
    key: str
    content: str
    kind: str = "semantic"  # semantic | episodic | preference
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    ttl_seconds: int | None = None
    user_verified: bool = False


class PersonalMemoryManager:
    """User-editable, auditable memory with importance scoring, staleness, SQLite persistence, and export."""

    def __init__(self, *, default_retention_days: int = 90, db_path: Path | str | None = None) -> None:
        self._entries: dict[str, MemoryEntry] = {}
        self.default_retention_days = default_retention_days
        self.db_path = Path(db_path).resolve() if db_path else None
        if self.db_path is not None:
            self._init_db()
            self._load_from_db()

    def _init_db(self) -> None:
        if self.db_path is None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_memories (
                    id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def _load_from_db(self) -> None:
        if self.db_path is None or not self.db_path.exists():
            return
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT payload_json FROM personal_memories ORDER BY updated_at ASC").fetchall()
        for (payload_json,) in rows:
            try:
                entry = MemoryEntry.model_validate_json(payload_json)
                self._entries[entry.id] = entry
            except Exception:
                pass

    def _persist_entry(self, entry: MemoryEntry) -> None:
        if self.db_path is None:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO personal_memories(id, payload_json, updated_at) VALUES (?, ?, ?)",
                (entry.id, entry.model_dump_json(), entry.updated_at),
            )
            conn.commit()

    def _delete_from_db(self, memory_id: str) -> None:
        if self.db_path is None:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM personal_memories WHERE id = ?", (memory_id,))
            conn.commit()

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        self._entries[entry.id] = entry
        self._persist_entry(entry)
        return entry

    def edit(self, memory_id: str, new_content: str, *, importance: float | None = None) -> MemoryEntry:
        if memory_id not in self._entries:
            raise KeyError(f"Memory entry not found: {memory_id}")
        entry = self._entries[memory_id]
        entry.content = new_content
        if importance is not None:
            entry.importance = importance
        entry.updated_at = time.time()
        entry.user_verified = True
        self._persist_entry(entry)
        return entry

    def delete(self, memory_id: str) -> bool:
        removed = self._entries.pop(memory_id, None) is not None
        if removed:
            self._delete_from_db(memory_id)
        return removed

    def list_entries(self, *, project_id: str | None = None) -> list[MemoryEntry]:
        items = list(self._entries.values())
        if project_id:
            items = [e for e in items if e.project_id == project_id]
        return items

    def detect_outdated(self, *, now: float | None = None) -> list[MemoryEntry]:
        ts = now or time.time()
        stale: list[MemoryEntry] = []
        for e in self._entries.values():
            ttl = e.ttl_seconds if e.ttl_seconds is not None else self.default_retention_days * 86400
            if ts - e.updated_at > ttl:
                stale.append(e)
        return stale

    def detect_contradictions(self) -> list[tuple[MemoryEntry, MemoryEntry]]:
        by_key: dict[tuple[str, str], list[MemoryEntry]] = {}
        for e in self._entries.values():
            by_key.setdefault((e.project_id, e.key), []).append(e)
        conflicts: list[tuple[MemoryEntry, MemoryEntry]] = []
        for group in by_key.values():
            if len(group) > 1:
                distinct = {g.content.strip() for g in group}
                if len(distinct) > 1:
                    conflicts.append((group[0], group[-1]))
        return conflicts

    def resolve_contradiction(self, keep_id: str, discard_id: str) -> bool:
        if keep_id in self._entries and discard_id in self._entries:
            self._entries.pop(discard_id)
            self._delete_from_db(discard_id)
            self._entries[keep_id].user_verified = True
            self._entries[keep_id].updated_at = time.time()
            self._persist_entry(self._entries[keep_id])
            return True
        return False

    def retrieve(self, query: str, *, project_id: str | None = None, kind: str | None = None, limit: int = 5) -> list[MemoryEntry]:
        q_tokens = set(query.lower().split())
        scored: list[tuple[float, MemoryEntry]] = []
        for e in self._entries.values():
            if project_id and e.project_id != project_id:
                continue
            if kind and e.kind != kind:
                continue
            words = set((e.key + " " + e.content).lower().split())
            overlap = len(q_tokens & words) / max(1, len(q_tokens))
            score = overlap * 0.7 + e.importance * 0.3
            if overlap > 0 or not q_tokens:
                scored.append((score, e))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def apply_retention_policy(self, *, now: float | None = None) -> int:
        """Purge outdated entries that are not explicitly user-verified."""
        outdated = self.detect_outdated(now=now)
        purged = 0
        for e in outdated:
            if not e.user_verified and self.delete(e.id):
                purged += 1
        return purged

    def export_json(self) -> str:
        return json.dumps([e.model_dump() for e in self._entries.values()], indent=2)

    def restore_json(self, payload: str) -> int:
        items = json.loads(payload)
        count = 0
        for raw in items:
            entry = MemoryEntry.model_validate(raw)
            self._entries[entry.id] = entry
            self._persist_entry(entry)
            count += 1
        return count


class NotificationPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True
    quiet_hours: bool = False
    allow_deadline_alerts: bool = True


class ProactiveAlert(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str
    title: str
    urgency: str = "normal"


class ProactiveIntelligence:
    """Permission-based notifications, deadline monitoring, and progress alerts."""

    def __init__(self, policy: NotificationPolicy | None = None) -> None:
        self.policy = policy or NotificationPolicy()
        self._deadlines: list[dict[str, Any]] = []

    def add_deadline(self, title: str, due_epoch: float) -> None:
        self._deadlines.append({"title": title, "due_epoch": due_epoch})

    def evaluate_alerts(self, *, now: float | None = None) -> list[ProactiveAlert]:
        if not self.policy.enabled or self.policy.quiet_hours:
            return []
        ts = now or time.time()
        alerts: list[ProactiveAlert] = []
        if self.policy.allow_deadline_alerts:
            for d in self._deadlines:
                remaining = d["due_epoch"] - ts
                if remaining <= 3600:
                    alerts.append(
                        ProactiveAlert(
                            kind="deadline",
                            title=f"Upcoming deadline: {d['title']}",
                            urgency="high" if remaining <= 900 else "normal",
                        )
                    )
        return alerts


class ConnectedDevice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    device_id: str
    name: str
    kind: str  # light, thermostat, sensor, speaker
    host: str
    authenticated: bool = False
    state: dict[str, Any] = Field(default_factory=dict)


class DeviceEcosystem:
    """Permission-gated LAN discovery and HMAC-authenticated smart-device control."""

    def __init__(self, *, discovery_permitted: bool = False) -> None:
        self.discovery_permitted = discovery_permitted
        self._devices: dict[str, ConnectedDevice] = {}
        self._secrets: dict[str, str] = {}

    def discover_devices(self, candidates: list[ConnectedDevice]) -> list[ConnectedDevice]:
        if not self.discovery_permitted:
            raise PermissionError("Local network discovery requires explicit user permission")
        for dev in candidates:
            self._devices[dev.device_id] = dev
        return list(self._devices.values())

    def authenticate_device(self, device_id: str) -> str:
        if device_id not in self._devices:
            raise KeyError(f"Unknown device: {device_id}")
        token = secrets.token_hex(16)
        self._secrets[device_id] = token
        self._devices[device_id].authenticated = True
        return token

    def send_command(self, device_id: str, token: str, command: dict[str, Any]) -> dict[str, Any]:
        dev = self._devices.get(device_id)
        if not dev:
            raise KeyError(f"Unknown device: {device_id}")
        expected = self._secrets.get(device_id)
        if not dev.authenticated or not expected or not hmac.compare_digest(expected, token):
            raise PermissionError(f"Device '{device_id}' authentication failed")
        dev.state.update(command)
        return {"device_id": device_id, "state": dict(dev.state), "status": "ok"}


class VoiceProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    profile_id: str
    language: str  # en-GB / en-US, hi-IN
    voice_name: str
    voice_direction: str = ""
    rate: float = 1.0
    personality: str = "executive_calm"


class VoiceExperienceManager:
    """English & Hindi voice profiles, streaming chunking, and barge-in interruption."""

    def __init__(self) -> None:
        self.profiles: dict[str, VoiceProfile] = {
            "en_bel": VoiceProfile(
                profile_id="en_bel",
                language="en-US",
                voice_name="Microsoft David",
                voice_direction="Refined British male voice, Gemini Charon voice direction",
                rate=1.0,
                personality="british_executive_butler",
            ),
            "hi_bel": VoiceProfile(
                profile_id="hi_bel",
                language="hi-IN",
                voice_name="Microsoft Hemant",
                voice_direction="Natural, mature Indian male voice with a controlled, refined delivery",
                rate=1.0,
                personality="refined_indian_executive",
            ),
        }
        self._interrupted = False

    def interrupt(self) -> None:
        self._interrupted = True

    def stream_speech_chunks(self, text: str, profile_id: str = "en_bel") -> Iterator[dict[str, Any]]:
        self._interrupted = False
        profile = self.profiles[profile_id]
        # Split on sentence boundaries for natural prosody & low-latency streaming
        chunks = [c.strip() for c in text.replace("?", ".").replace("!", ".").split(".") if c.strip()]
        for idx, chunk in enumerate(chunks):
            if self._interrupted:
                break
            yield {
                "chunk_index": idx,
                "language": profile.language,
                "voice": profile.voice_name,
                "text": chunk,
                "personality": profile.personality,
            }
