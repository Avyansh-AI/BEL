"""BEL Input Understanding Engine.

Performs natural language understanding, intent classification, entity extraction,
multi-part instruction splitting, and ambiguity detection without requiring remote models.
"""
from __future__ import annotations

from enum import Enum
import re
from typing import Any
from pydantic import Field
from ..tools import StrictModel


class IntentType(str, Enum):
    CONVERSATION = "conversation"
    TOOL_ACTION = "tool_action"
    TASK_PLAN = "task_plan"
    SERIOUS_MODE = "serious_mode"
    CLARIFICATION_RESPONSE = "clarification_response"
    CORRECTION = "correction"
    SYSTEM_QUERY = "system_query"


class ParsedInput(StrictModel):
    raw_text: str
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    entities: dict[str, Any] = Field(default_factory=dict)
    is_ambiguous: bool = False
    ambiguity_reason: str | None = None
    clarification_prompt: str | None = None
    is_serious_mode_requested: bool = False
    reasoning_depth: str = "standard"
    sub_instructions: list[str] = Field(default_factory=list)


class InputUnderstanding:
    """Natural Language Understanding & Intent Extraction for BEL."""

    FILE_PATTERN = re.compile(
        r"\b([A-Za-z0-9_\-/\\]+\.(?:txt|md|docx|json|py|csv|html|js|ts|step|stl|pdf))\b",
        re.IGNORECASE,
    )
    APP_PATTERN = re.compile(
        r"\b(notepad|calculator|calc|explorer|paint)\b",
        re.IGNORECASE,
    )
    SERIOUS_MODE_PATTERN = re.compile(
        r"\b(serious mode|deliberate|think deeply|multi-model|critical decision|compare models|deep analysis)\b",
        re.IGNORECASE,
    )
    SYSTEM_QUERY_PATTERN = re.compile(
        r"^(status|help|what can you do|system telemetry|specs|hardware status|who are you)$",
        re.IGNORECASE,
    )
    CORRECTION_PATTERN = re.compile(
        r"^(no,? (?:i meant|not that|actually)|wait,? (?:change that to|i meant)|correction:?)\b",
        re.IGNORECASE,
    )
    MULTI_STEP_CONJUNCTIONS = re.compile(
        r"\b(?:and then|after that|then|next|followed by)\b",
        re.IGNORECASE,
    )

    def parse(self, text: str, context_entities: dict[str, Any] | None = None) -> ParsedInput:
        """Parse natural language input into structured understanding."""
        text_clean = text.strip()
        entities: dict[str, Any] = {}
        context_entities = context_entities or {}

        # 1. Check for Serious Mode invocation
        is_serious = bool(self.SERIOUS_MODE_PATTERN.search(text_clean))

        # 2. Extract Entities
        files = self.FILE_PATTERN.findall(text_clean)
        if files:
            entities["files"] = files
            entities["primary_file"] = files[0]
        else:
            if "primary_file" in context_entities and re.search(r"\b(that file|the file|it)\b", text_clean, re.IGNORECASE):
                entities["primary_file"] = context_entities["primary_file"]
                entities["anaphoric_resolved"] = True
            if "files" in context_entities and re.search(r"\b(those files|both files|them)\b", text_clean, re.IGNORECASE):
                entities["files"] = context_entities["files"]
                entities["anaphoric_resolved"] = True

        app_match = self.APP_PATTERN.search(text_clean)
        if app_match:
            app_name = app_match.group(1).lower()
            if app_name == "calc":
                app_name = "calculator"
            entities["application"] = app_name
        elif "application" in context_entities and re.search(r"\b(that app|the app|that application)\b", text_clean, re.IGNORECASE):
            entities["application"] = context_entities["application"]
            entities["anaphoric_resolved"] = True

        # 3. Detect Multi-part instructions
        sub_parts = [p.strip() for p in self.MULTI_STEP_CONJUNCTIONS.split(text_clean) if p.strip()]
        if len(sub_parts) > 1:
            entities["multi_part"] = True
            sub_instructions = sub_parts
        else:
            sub_instructions = [text_clean]

        # 4. Intent Classification
        if is_serious:
            intent = IntentType.SERIOUS_MODE
            confidence = 0.95
        elif self.SYSTEM_QUERY_PATTERN.search(text_clean):
            intent = IntentType.SYSTEM_QUERY
            confidence = 0.98
        elif self.CORRECTION_PATTERN.search(text_clean):
            intent = IntentType.CORRECTION
            confidence = 0.90
        elif len(sub_parts) > 1:
            intent = IntentType.TASK_PLAN
            confidence = 0.92
        elif self._is_tool_action(text_clean, entities):
            intent = IntentType.TOOL_ACTION
            confidence = 0.88
        else:
            intent = IntentType.CONVERSATION
            confidence = 0.85

        # 5. Ambiguity & Contradiction Detection
        is_ambiguous, reason, prompt = self._detect_ambiguity(text_clean, intent, entities)

        # 6. Reasoning Depth Selection (avoid unnecessary deep deliberation for fast/direct queries)
        if is_serious:
            reasoning_depth = "deep"
        elif intent in (IntentType.SYSTEM_QUERY, IntentType.TOOL_ACTION) and len(sub_instructions) == 1:
            reasoning_depth = "fast"
        elif intent == IntentType.TASK_PLAN or len(sub_instructions) > 1:
            reasoning_depth = "deep"
        else:
            reasoning_depth = "standard"

        return ParsedInput(
            raw_text=text_clean,
            intent=intent,
            confidence=confidence,
            entities=entities,
            is_ambiguous=is_ambiguous,
            ambiguity_reason=reason,
            clarification_prompt=prompt,
            is_serious_mode_requested=is_serious,
            reasoning_depth=reasoning_depth,
            sub_instructions=sub_instructions,
        )

    def _is_tool_action(self, text: str, entities: dict[str, Any]) -> bool:
        low = text.lower()
        tool_verbs = (
            "open", "launch", "create", "write", "edit", "modify",
            "rename", "delete", "remove", "undo", "list files",
            "search memory", "remember", "search files",
        )
        has_verb = any(v in low for v in tool_verbs)
        has_target = bool(entities.get("files") or entities.get("application") or "undo" in low or "list" in low)
        return has_verb and (has_target or len(low.split()) <= 6)

    def _detect_ambiguity(
        self, text: str, intent: IntentType, entities: dict[str, Any]
    ) -> tuple[bool, str | None, str | None]:
        low = text.lower()

        # Contradictory instructions check (e.g. create and delete the same single target in one prompt)
        files = entities.get("files") or []
        if len(files) == 1 or (len(files) > 1 and len(set(f.lower() for f in files)) == 1):
            if any(w in low for w in ("create ", "write ")) and any(w in low for w in ("delete ", "remove ")):
                return (
                    True,
                    "Contradictory file operations requested on the same file.",
                    f"You asked to both create and delete '{files[0]}'. Which action should I perform?",
                )

        # Action without target
        if intent == IntentType.TOOL_ACTION:
            if any(w in low for w in ("create a file", "make a file", "new file")) and "files" not in entities:
                return (
                    True,
                    "File creation requested without filename.",
                    "What should the file be named, and what content would you like in it?",
                )
            if any(w in low for w in ("open app", "launch app", "open the app")) and "application" not in entities:
                return (
                    True,
                    "Application launch requested without application name.",
                    "Which application would you like me to open? (e.g. Notepad, Calculator)",
                )
            if any(w in low for w in ("edit the file", "change the file")) and "files" not in entities and "primary_file" not in entities:
                return (
                    True,
                    "File modification requested without identifying the target file.",
                    "Which file would you like to edit, and what changes should be made?",
                )

        return False, None, None
