"""Host DPAPI Credential Vault for BEL (Stage 9).

Encrypts API keys, tokens, and sensitive secrets using the Windows Data
Protection API (DPAPI via crypt32.dll) tied to the owner's Windows user login.
Provides zero-plaintext storage on disk with AES-GCM portable fallback.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, Field


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


class VaultStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dpapi_active: bool = False
    storage_path: str
    total_keys: int = 0
    backend: str = "win32_dpapi"


class DPAPIVault:
    """Secure credential vault leveraging Windows DPAPI or AES-GCM."""

    def __init__(self, vault_dir: Path | str, fallback_passphrase: str = "BEL_SOVEREIGN_FALLBACK_KEY_32B") -> None:
        self.vault_dir = Path(vault_dir).resolve()
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self.vault_file = self.vault_dir / "vault.enc"
        self._is_windows = os.name == "nt"
        # 32-byte key for AES-GCM fallback
        self._fallback_key = (fallback_passphrase.encode("utf-8") * 2)[:32]
        self._cache: dict[str, str] = {}
        self._load()

    def is_dpapi_available(self) -> bool:
        if not self._is_windows:
            return False
        try:
            return hasattr(ctypes.windll, "crypt32")
        except Exception:
            return False

    def _dpapi_encrypt(self, plaintext_bytes: bytes) -> bytes:
        """Encrypt bytes using Windows CryptProtectData."""
        in_blob = DATA_BLOB()
        in_blob.cbData = len(plaintext_bytes)
        in_blob.pbData = ctypes.cast(ctypes.create_string_buffer(plaintext_bytes), ctypes.POINTER(ctypes.c_byte))

        out_blob = DATA_BLOB()
        flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN

        success = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "BEL_DPAPI_SECRET",
            None,
            None,
            None,
            flags,
            ctypes.byref(out_blob),
        )
        if not success:
            raise RuntimeError(f"CryptProtectData failed with error code: {ctypes.GetLastError()}")

        try:
            enc_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return enc_bytes
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)

    def _dpapi_decrypt(self, cipher_bytes: bytes) -> bytes:
        """Decrypt bytes using Windows CryptUnprotectData."""
        in_blob = DATA_BLOB()
        in_blob.cbData = len(cipher_bytes)
        in_blob.pbData = ctypes.cast(ctypes.create_string_buffer(cipher_bytes), ctypes.POINTER(ctypes.c_byte))

        out_blob = DATA_BLOB()
        flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN

        success = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(out_blob),
        )
        if not success:
            raise RuntimeError(f"CryptUnprotectData failed with error code: {ctypes.GetLastError()}")

        try:
            dec_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return dec_bytes
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)

    def _aes_encrypt(self, plaintext_bytes: bytes) -> bytes:
        """AES-GCM fallback encryption."""
        aesgcm = AESGCM(self._fallback_key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, None)
        return nonce + ciphertext

    def _aes_decrypt(self, cipher_bytes: bytes) -> bytes:
        """AES-GCM fallback decryption."""
        nonce = cipher_bytes[:12]
        ciphertext = cipher_bytes[12:]
        aesgcm = AESGCM(self._fallback_key)
        return aesgcm.decrypt(nonce, ciphertext, None)

    def _encrypt_value(self, value_str: str) -> str:
        b = value_str.encode("utf-8")
        if self.is_dpapi_available():
            try:
                enc = self._dpapi_encrypt(b)
                return "dpapi:" + base64.b64encode(enc).decode("ascii")
            except Exception:
                pass
        enc = self._aes_encrypt(b)
        return "aes:" + base64.b64encode(enc).decode("ascii")

    def _decrypt_value(self, enc_str: str) -> str:
        if enc_str.startswith("dpapi:"):
            raw = base64.b64decode(enc_str[6:])
            return self._dpapi_decrypt(raw).decode("utf-8")
        elif enc_str.startswith("aes:"):
            raw = base64.b64decode(enc_str[4:])
            return self._aes_decrypt(raw).decode("utf-8")
        else:
            raise ValueError("Unknown vault encryption format")

    def _load(self) -> None:
        if not self.vault_file.exists():
            self._cache = {}
            return
        try:
            data = json.loads(self.vault_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._cache = data
        except Exception:
            self._cache = {}

    def _save(self) -> None:
        temp_file = self.vault_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")
        temp_file.replace(self.vault_file)

    def store_secret(self, key: str, value: str) -> None:
        """Store an encrypted secret in the vault."""
        if not key.strip():
            raise ValueError("Secret key name cannot be empty")
        encrypted = self._encrypt_value(value)
        self._cache[key] = encrypted
        self._save()

    def retrieve_secret(self, key: str) -> str | None:
        """Retrieve and decrypt a secret from the vault."""
        if key not in self._cache:
            return None
        return self._decrypt_value(self._cache[key])

    def delete_secret(self, key: str) -> bool:
        """Remove a secret from the vault."""
        if key in self._cache:
            del self._cache[key]
            self._save()
            return True
        return False

    def list_keys(self) -> list[str]:
        """List all secret key names currently stored."""
        return sorted(list(self._cache.keys()))

    def get_status(self) -> VaultStatus:
        return VaultStatus(
            dpapi_active=self.is_dpapi_available(),
            storage_path=str(self.vault_file),
            total_keys=len(self._cache),
            backend="win32_dpapi" if self.is_dpapi_available() else "aes_gcm",
        )
