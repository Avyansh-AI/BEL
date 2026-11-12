"""Stage 10: Production Hardening & V1 Certification Controls for BEL.

Provides:
- Centralized PermissionManager
- NetworkEgressGuard (loopback + explicit allowlist enforcement, SSRF protection)
- TamperEvidentAuditLog (SHA-256 hash-chained append-only action log)
- SignedUpdateVerifier (cryptographic update signature verification)
- APIKeyRotationManager (key age tracking & rotation)
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field


class PermissionManager:
    """Centralized capability & action permission manager."""

    def __init__(self) -> None:
        self._grants: dict[str, set[str]] = {}

    def grant(self, subject: str, scope: str) -> None:
        self._grants.setdefault(subject, set()).add(scope)

    def revoke(self, subject: str, scope: str) -> None:
        if subject in self._grants:
            self._grants[subject].discard(scope)

    def check(self, subject: str, scope: str) -> bool:
        return scope in self._grants.get(subject, set())


class NetworkEgressGuard:
    """Enforces strict network egress controls and blocks SSRF targets."""

    def __init__(self, *, allowed_hosts: set[str] | None = None, allow_loopback: bool = True) -> None:
        self.allowed_hosts = {h.lower() for h in (allowed_hosts or set())}
        self.allow_loopback = allow_loopback

    def is_allowed(self, url: str) -> tuple[bool, str]:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"Blocked scheme: {parsed.scheme}"
        host = (parsed.hostname or "").lower()
        if not host:
            return False, "Missing hostname"

        if host in ("localhost", "127.0.0.1", "::1"):
            return (True, "loopback_allowed") if self.allow_loopback else (False, "Loopback blocked")

        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False, f"Blocked private/reserved IP: {host}"
        except ValueError:
            pass

        if host in self.allowed_hosts:
            return True, "allowlisted"
        return False, f"Host '{host}' not in egress allowlist"


class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    seq: int
    timestamp: float
    actor: str
    action: str
    details: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    entry_hash: str


class TamperEvidentAuditLog:
    """Append-only SHA-256 hash-chained audit log."""

    GENESIS_HASH = "0" * 64

    def __init__(self, log_path: Path | str) -> None:
        self.log_path = Path(log_path).resolve()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _compute_hash(seq: int, timestamp: float, actor: str, action: str, details: dict[str, Any], prev_hash: str) -> str:
        canonical = json.dumps(
            {
                "seq": seq,
                "timestamp": timestamp,
                "actor": actor,
                "action": action,
                "details": details,
                "prev_hash": prev_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _read_records(self) -> list[AuditRecord]:
        if not self.log_path.exists():
            return []
        lines = [ln for ln in self.log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return [AuditRecord.model_validate_json(ln) for ln in lines]

    def append(self, actor: str, action: str, details: dict[str, Any] | None = None) -> AuditRecord:
        records = self._read_records()
        seq = len(records) + 1
        prev_hash = records[-1].entry_hash if records else self.GENESIS_HASH
        ts = time.time()
        det = details or {}
        entry_hash = self._compute_hash(seq, ts, actor, action, det, prev_hash)
        rec = AuditRecord(
            seq=seq,
            timestamp=ts,
            actor=actor,
            action=action,
            details=det,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(rec.model_dump_json() + "\n")
        return rec

    def verify_chain(self) -> tuple[bool, str | None]:
        records = self._read_records()
        expected_prev = self.GENESIS_HASH
        for idx, rec in enumerate(records, start=1):
            if rec.seq != idx:
                return False, f"Sequence mismatch at record {idx}"
            if rec.prev_hash != expected_prev:
                return False, f"Broken chain prev_hash at record {idx}"
            expected_hash = self._compute_hash(
                rec.seq, rec.timestamp, rec.actor, rec.action, rec.details, rec.prev_hash
            )
            if not hmac.compare_digest(rec.entry_hash, expected_hash):
                return False, f"Tampered entry_hash at record {idx}"
            expected_prev = rec.entry_hash
        return True, None


class SignedUpdateVerifier:
    """Verifies cryptographic HMAC-SHA256 signatures on software update packages."""

    def __init__(self, signing_key: bytes) -> None:
        self._key = signing_key

    def sign_payload(self, payload: bytes) -> str:
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def verify_payload(self, payload: bytes, signature_hex: str) -> bool:
        expected = self.sign_payload(payload)
        return hmac.compare_digest(expected, signature_hex)


class APIKeyRotationManager:
    """Tracks API key metadata, age, and rotation events without storing raw secrets."""

    def __init__(self, *, max_age_days: int = 90) -> None:
        self.max_age_days = max_age_days
        self._keys: dict[str, dict[str, Any]] = {}

    def record_key(self, provider: str, key_fingerprint: str, *, created_at: float | None = None) -> None:
        self._keys[provider] = {
            "fingerprint": key_fingerprint,
            "created_at": created_at or time.time(),
            "rotations": 0,
        }

    def needs_rotation(self, provider: str, *, now: float | None = None) -> bool:
        meta = self._keys.get(provider)
        if not meta:
            return False
        ts = now or time.time()
        return (ts - meta["created_at"]) > (self.max_age_days * 86400)

    def rotate(self, provider: str, new_fingerprint: str) -> dict[str, Any]:
        meta = self._keys.setdefault(provider, {"rotations": 0})
        meta["fingerprint"] = new_fingerprint
        meta["created_at"] = time.time()
        meta["rotations"] = meta.get("rotations", 0) + 1
        return dict(meta)
