"""Populate Owner's Real Cloud API Credentials into BEL DPAPI Vault and Keyring."""
from __future__ import annotations

import os
from pathlib import Path
import sys

# Ensure sight_core is discoverable
workspace_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(workspace_root))

from sight_core.config import default_data_directory
from sight_core.vault_dpapi import DPAPIVault
from sight_core.security import Vault

CREDENTIALS = {
    "openrouter": os.environ.get("OPENROUTER_API_KEY", ""),
    "groq": os.environ.get("GROQ_API_KEY", ""),
    "gemini": os.environ.get("GEMINI_API_KEY", ""),
    "fish_audio": os.environ.get("FISH_AUDIO_API_KEY", ""),
    "token_harbor": os.environ.get("TOKEN_HARBOR_API_KEY", ""),
    "tokenharbor": os.environ.get("TOKEN_HARBOR_API_KEY", ""),
}


def populate():
    print("================================================================================")
    print("POPULATING REAL CREDENTIALS INTO BEL DPAPI VAULT & KEYRING")
    print("================================================================================")

    data_dir = default_data_directory()
    vault_dir = data_dir / "vault"
    print(f"Target DPAPI Vault directory: {vault_dir}")
    vault = DPAPIVault(vault_dir=vault_dir)

    os_vault = Vault()

    for key, value in CREDENTIALS.items():
        # Store in DPAPI vault
        vault.store_secret(key, value)
        # Store primary provider keys in OS Keyring
        if key in os_vault.ALLOWED:
            try:
                os_vault.set(key, value)
                print(f"   [+] Stored '{key}' in DPAPI Vault & OS Keyring (WinVault)")
            except Exception as e:
                print(f"   [+] Stored '{key}' in DPAPI Vault (Keyring notice: {e})")
        else:
            print(f"   [+] Stored '{key}' in DPAPI Vault")

    status = vault.get_status()
    print("--------------------------------------------------------------------------------")
    print(f"DPAPI Active: {status.dpapi_active} (Backend: {status.backend})")
    print(f"Total Stored Secrets in Vault: {status.total_keys}")
    print(f"Stored Key Names: {', '.join(vault.list_keys())}")
    print("================================================================================")


if __name__ == "__main__":
    populate()
