"""Unit tests for Stage 9 Host DPAPI Credential Vault."""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from sight_core.vault_dpapi import DPAPIVault


def test_vault_store_and_retrieve():
    with tempfile.TemporaryDirectory() as tmp_dir:
        vault = DPAPIVault(tmp_dir)

        # Store secret
        vault.store_secret("groq_api_token", "gsk_test_secret_token_12345")
        vault.store_secret("custom_db_password", "super_secret_pw!#99")

        # Verify disk file contains zero plaintext
        enc_file = Path(tmp_dir) / "vault.enc"
        assert enc_file.exists()
        raw_disk_text = enc_file.read_text(encoding="utf-8")
        assert "gsk_test_secret_token_12345" not in raw_disk_text
        assert "super_secret_pw!#99" not in raw_disk_text

        # Retrieve secret
        val1 = vault.retrieve_secret("groq_api_token")
        assert val1 == "gsk_test_secret_token_12345"

        val2 = vault.retrieve_secret("custom_db_password")
        assert val2 == "super_secret_pw!#99"

        # Non-existent key
        assert vault.retrieve_secret("unknown_key") is None

        # Key list
        keys = vault.list_keys()
        assert keys == ["custom_db_password", "groq_api_token"]

        # Delete key
        deleted = vault.delete_secret("custom_db_password")
        assert deleted is True
        assert vault.retrieve_secret("custom_db_password") is None
        assert vault.list_keys() == ["groq_api_token"]


def test_vault_status():
    with tempfile.TemporaryDirectory() as tmp_dir:
        vault = DPAPIVault(tmp_dir)
        status = vault.get_status()

        assert status.storage_path != ""
        assert status.backend in ("win32_dpapi", "aes_gcm")
        assert status.total_keys == 0
