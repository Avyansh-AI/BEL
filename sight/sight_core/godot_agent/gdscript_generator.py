"""GDScript 2.0 Generator and Validator for Godot 4.x (Stage 7).

Generates typed GDScript for character controllers, camera movement,
and UI event handling, with syntactic validation.
"""
from __future__ import annotations

import re


class GDScriptGenerator:
    """Generates standard Godot 4.x GDScript controllers."""

    @classmethod
    def generate_script(cls, archetype: str = "2d_character") -> str:
        arch = archetype.lower()
        if arch == "3d_character":
            return cls._script_3d_character()
        elif arch == "ui_menu":
            return cls._script_ui_menu()
        else:
            return cls._script_2d_character()

    @staticmethod
    def _script_2d_character() -> str:
        return """extends CharacterBody2D

const SPEED: float = 300.0
const JUMP_VELOCITY: float = -400.0

# Get gravity from project settings to match physics
var gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity")

func _physics_process(delta: float) -> void:
\t# Add gravity
\tif not is_on_floor():
\t\tvelocity.y += gravity * delta

\t# Handle Jump
\tif Input.is_action_just_pressed("ui_accept") and is_on_floor():
\t\tvelocity.y = JUMP_VELOCITY

\t# Handle horizontal movement
\tvar direction := Input.get_axis("ui_left", "ui_right")
\tif direction != 0.0:
\t\tvelocity.x = direction * SPEED
\telse:
\t\tvelocity.x = move_toward(velocity.x, 0, SPEED)

\tmove_and_slide()
"""

    @staticmethod
    def _script_3d_character() -> str:
        return """extends CharacterBody3D

const SPEED: float = 5.0
const JUMP_VELOCITY: float = 4.5

var gravity: float = ProjectSettings.get_setting("physics/3d/default_gravity")

func _physics_process(delta: float) -> void:
\tif not is_on_floor():
\t\tvelocity.y -= gravity * delta

\tif Input.is_action_just_pressed("ui_accept") and is_on_floor():
\t\tvelocity.y = JUMP_VELOCITY

\tvar input_dir := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
\tvar direction := (transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()
\tif direction:
\t\tvelocity.x = direction.x * SPEED
\t\tvelocity.z = direction.z * SPEED
\telse:
\t\tvelocity.x = move_toward(velocity.x, 0, SPEED)
\t\tvelocity.z = move_toward(velocity.z, 0, SPEED)

\tmove_and_slide()
"""

    @staticmethod
    def _script_ui_menu() -> str:
        return """extends Control

func _ready() -> void:
\tvar start_btn := get_node_or_null("VBoxContainer/StartButton") as Button
\tvar quit_btn := get_node_or_null("VBoxContainer/QuitButton") as Button
\tif start_btn:
\t\tstart_btn.pressed.connect(_on_start_pressed)
\tif quit_btn:
\t\tquit_btn.pressed.connect(_on_quit_pressed)

func _on_start_pressed() -> void:
\tprint("[BEL-Godot] Starting game...")

func _on_quit_pressed() -> void:
\tget_tree().quit()
"""

    @classmethod
    def validate_syntax(cls, script_content: str) -> tuple[bool, str | None]:
        """Perform static validation of GDScript structure."""
        if not script_content.strip():
            return False, "Script content is empty"

        lines = script_content.splitlines()
        has_extends = False

        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if stripped.startswith("extends "):
                has_extends = True

            # Check colon on func/if/for/while
            if re.match(r"^(?:func|if|elif|else|for|while|match)\b", stripped):
                if not stripped.endswith(":"):
                    return False, f"Line {i}: Missing trailing colon ':' in block statement"

        if not has_extends:
            return False, "Missing 'extends <Node>' declaration in GDScript root"

        return True, None
