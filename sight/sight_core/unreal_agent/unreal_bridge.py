"""Unreal Engine Automation Bridge for BEL (Stage 7).

Provides Unreal Engine 5 discovery, Remote Control HTTP execution,
and Editor Python script generation.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Any

import httpx

from .models import (
    UnrealRemoteCall,
    UnrealScriptRequest,
    UnrealScriptResult,
    UnrealStatus,
)
from .script_generator import UnrealScriptGenerator


class UnrealAgent:
    """Manages Unreal Engine 5 scripting and Web Remote Control interaction."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self._engine_path, self._engine_version = self._discover_unreal()

    def _discover_unreal(self) -> tuple[Path | None, str | None]:
        env_path = os.environ.get("UNREAL_ENGINE_PATH")
        if env_path and Path(env_path).exists():
            return Path(env_path), "5.x (Custom ENV)"

        if os.name == "nt":
            candidates = glob.glob(r"C:\Program Files\Epic Games\UE_5.*")
            if candidates:
                cand = candidates[-1]
                version = Path(cand).name.replace("UE_", "")
                return Path(cand), version

        return None, None

    def get_status(self, remote_control_url: str = "http://localhost:30010") -> UnrealStatus:
        available = self._engine_path is not None
        rc_connected = False

        # Quick check on Web Remote Control port
        try:
            with httpx.Client(timeout=1.0) as client:
                res = client.get(f"{remote_control_url}/remote/info")
                if res.status_code == 200:
                    rc_connected = True
        except Exception:
            rc_connected = False

        return UnrealStatus(
            available=available,
            remote_control_connected=rc_connected,
            engine_path=str(self._engine_path) if self._engine_path else None,
            engine_version=self._engine_version,
        )

    def generate_script(self, request: UnrealScriptRequest) -> UnrealScriptResult:
        """Generate an Unreal Engine Python script."""
        script_code, desc = UnrealScriptGenerator.generate(
            task_type=request.task_type,
            actor_class=request.actor_class,
            params=request.parameters,
        )

        out_path: str | None = None
        if request.output_path:
            p = Path(request.output_path)
            if not p.is_absolute():
                p = self.workspace_root / p
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(script_code, encoding="utf-8")
            out_path = str(p)

        return UnrealScriptResult(
            script=script_code,
            output_path=out_path,
            task_type=request.task_type,
            description=desc,
        )

    async def call_remote(
        self,
        call: UnrealRemoteCall,
        base_url: str = "http://localhost:30010",
    ) -> dict[str, Any]:
        """Invoke an object method via Unreal Engine Web Remote Control API."""
        endpoint = f"{base_url}/remote/object/call"
        payload = {
            "objectPath": call.object_path,
            "functionName": call.function_name,
            "parameters": call.parameters,
            "generateTransaction": True,
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                res = await client.put(endpoint, json=payload)
                if res.status_code == 200:
                    return {"success": True, "data": res.json()}
                return {
                    "success": False,
                    "error": f"Remote control HTTP {res.status_code}: {res.text}",
                }
            except Exception as exc:
                return {
                    "success": False,
                    "error": f"Failed to connect to Unreal Remote Control server: {exc}",
                }
