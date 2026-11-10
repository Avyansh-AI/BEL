"""Capability Gap Detector (Scout) for BEL RSI Subsystem.

Inspired by Ada-SI's Scout agent. Monitors conversational intent and execution
failures to identify capability deficiencies and formulate structured extension goals.
"""
from __future__ import annotations

import re
import uuid
from typing import Any
from .types import CapabilityGap, GapType


class CapabilityScout:
    """Detects missing capabilities, tool gaps, and operational bottlenecks."""

    def __init__(self, registered_tools: set[str] | None = None) -> None:
        self.registered_tools = registered_tools or {
            "fs.read",
            "fs.write",
            "fs.list",
            "fs.search",
            "fs.delete",
            "git.status",
            "git.diff",
            "proc.inspect",
            "sys.telemetry",
            "memory.search",
            "rag.search",
        }

    def inspect_request(
        self,
        user_text: str,
        detected_intent: str,
        active_entities: dict[str, Any] | None = None,
    ) -> CapabilityGap | None:
        """Analyze a request to determine if it exceeds current tool capabilities."""
        if not user_text or not user_text.strip():
            return None

        entities = active_entities or {}
        low = user_text.lower().strip()

        # 1. Explicit request to create or synthesize a skill/tool
        m_explicit = re.search(
            r"(?:create|build|write|synthesize|make|add)\s+(?:a\s+)?(?:new\s+)?(?:tool|skill|function|capability)\s+(?:called\s+|named\s+)?([a-z0-9_-]+)",
            low,
        )
        if m_explicit:
            name = m_explicit.group(1).replace("-", "_")
            return CapabilityGap(
                id=f"gap-{uuid.uuid4().hex[:8]}",
                user_request=user_text,
                detected_intent=detected_intent,
                gap_type=GapType.USER_REQUESTED_EXTENSION,
                missing_capability=f"Skill '{name}' requested explicitly by user.",
                suggested_tool_name=name,
                context=entities,
            )

        # 2. Heuristic capability pattern recognition for common utility gaps
        patterns: list[tuple[re.Pattern, str, str]] = [
            (
                re.compile(r"(?:convert|calculate|transform).*?(?:celsius|fahrenheit|kelvin|temperature)"),
                "temperature_converter",
                "Conversion between temperature scales (Celsius, Fahrenheit, Kelvin).",
            ),
            (
                re.compile(r"(?:parse|convert|extract)\s+(?:markdown\s+table|table\s+to\s+json)"),
                "markdown_table_parser",
                "Parsing markdown tables into structured JSON lists.",
            ),
            (
                re.compile(r"(?:calculate|generate|compute)\s+(?:sha256|hash|md5|checksum)"),
                "hash_calculator",
                "Cryptographic hashing and checksum calculation for strings or files.",
            ),
            (
                re.compile(r"(?:validate|check|verify)\s+(?:email|url|ip\s+address|semver)"),
                "format_validator",
                "Validation of standard internet formats (email, URL, IP address, semantic version).",
            ),
            (
                re.compile(r"(?:generate|batch)\s+(?:uuid|unique\s+id)"),
                "uuid_generator",
                "Batch generation of cryptographically secure UUIDs.",
            ),
        ]

        for regex, tool_name, desc in patterns:
            if regex.search(low):
                if tool_name not in self.registered_tools:
                    return CapabilityGap(
                        id=f"gap-{uuid.uuid4().hex[:8]}",
                        user_request=user_text,
                        detected_intent=detected_intent,
                        gap_type=GapType.MISSING_TOOL,
                        missing_capability=desc,
                        suggested_tool_name=tool_name,
                        context=entities,
                    )

        # 3. Check requested tool entity against registered tools
        if "tool" in entities:
            target_tool = entities["tool"]
            if target_tool not in self.registered_tools:
                return CapabilityGap(
                    id=f"gap-{uuid.uuid4().hex[:8]}",
                    user_request=user_text,
                    detected_intent=detected_intent,
                    gap_type=GapType.MISSING_TOOL,
                    missing_capability=f"Unregistered tool '{target_tool}' was referenced in prompt.",
                    suggested_tool_name=target_tool.replace(".", "_"),
                    context=entities,
                )

        return None

    def inspect_failure(
        self,
        tool_name: str,
        error_message: str,
        user_request: str = "",
    ) -> CapabilityGap:
        """Create a capability gap from an execution failure."""
        return CapabilityGap(
            id=f"gap-{uuid.uuid4().hex[:8]}",
            user_request=user_request or f"Execution of tool '{tool_name}' failed.",
            detected_intent="tool_execution",
            gap_type=GapType.EXECUTION_FAILURE,
            missing_capability=f"Tool '{tool_name}' failed with error: {error_message[:200]}",
            suggested_tool_name=tool_name,
            context={"error": error_message, "tool_name": tool_name},
        )
