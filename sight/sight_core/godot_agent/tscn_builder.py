"""Godot 4.x Text Scene (.tscn) Builder and Parser for BEL (Stage 7).

Generates and parses Godot 4 scene trees with UID identifiers,
external resource links, and archetype node hierarchies.
"""
from __future__ import annotations

import re
import uuid


class TSCNBuilder:
    """Builder for Godot 4 scene (.tscn) format."""

    @staticmethod
    def generate_uid() -> str:
        return f"uid://{uuid.uuid4().hex[:12]}"

    @classmethod
    def build_scene(
        cls,
        archetype: str = "2d_character",
        scene_name: str = "Main",
        script_res_path: str | None = None,
    ) -> tuple[str, str, list[str]]:
        """
        Build a .tscn file content string for a given archetype.
        Returns: (tscn_content, root_type, list_of_node_names)
        """
        arch = archetype.lower()
        if arch == "3d_character":
            return cls._build_3d_character(scene_name, script_res_path)
        elif arch == "ui_menu":
            return cls._build_ui_menu(scene_name, script_res_path)
        else:
            return cls._build_2d_character(scene_name, script_res_path)

    @classmethod
    def _build_2d_character(cls, name: str, script_res: str | None) -> tuple[str, str, list[str]]:
        uid = cls.generate_uid()
        lines = [f'[gd_scene load_steps=2 format=3 uid="{uid}"]', ""]
        if script_res:
            lines.extend([
                f'[ext_resource type="Script" path="{script_res}" id="1_script"]',
                "",
            ])

        script_prop = 'script = ExtResource("1_script")' if script_res else ""
        lines.extend([
            f'[node name="{name}" type="CharacterBody2D"]',
            script_prop,
            "",
            f'[node name="CollisionShape2D" type="CollisionShape2D" parent="."]',
            "",
            f'[node name="Sprite2D" type="Sprite2D" parent="."]',
            "",
            f'[node name="Camera2D" type="Camera2D" parent="."]',
            "",
        ])
        nodes = [name, "CollisionShape2D", "Sprite2D", "Camera2D"]
        return "\n".join(lines), "CharacterBody2D", nodes

    @classmethod
    def _build_3d_character(cls, name: str, script_res: str | None) -> tuple[str, str, list[str]]:
        uid = cls.generate_uid()
        lines = [f'[gd_scene load_steps=2 format=3 uid="{uid}"]', ""]
        if script_res:
            lines.extend([
                f'[ext_resource type="Script" path="{script_res}" id="1_script"]',
                "",
            ])

        script_prop = 'script = ExtResource("1_script")' if script_res else ""
        lines.extend([
            f'[node name="{name}" type="CharacterBody3D"]',
            script_prop,
            "",
            f'[node name="CollisionShape3D" type="CollisionShape3D" parent="."]',
            "",
            f'[node name="MeshInstance3D" type="MeshInstance3D" parent="."]',
            "",
            f'[node name="Camera3D" type="Camera3D" parent="."]',
            "",
        ])
        nodes = [name, "CollisionShape3D", "MeshInstance3D", "Camera3D"]
        return "\n".join(lines), "CharacterBody3D", nodes

    @classmethod
    def _build_ui_menu(cls, name: str, script_res: str | None) -> tuple[str, str, list[str]]:
        uid = cls.generate_uid()
        lines = [f'[gd_scene load_steps=2 format=3 uid="{uid}"]', ""]
        if script_res:
            lines.extend([
                f'[ext_resource type="Script" path="{script_res}" id="1_script"]',
                "",
            ])

        script_prop = 'script = ExtResource("1_script")' if script_res else ""
        lines.extend([
            f'[node name="{name}" type="Control"]',
            'layout_mode = 3',
            'anchors_preset = 15',
            script_prop,
            "",
            f'[node name="VBoxContainer" type="VBoxContainer" parent="."]',
            'layout_mode = 1',
            'anchors_preset = 8',
            "",
            f'[node name="TitleLabel" type="Label" parent="VBoxContainer"]',
            'layout_mode = 2',
            'text = "BEL Game Title"',
            "",
            f'[node name="StartButton" type="Button" parent="VBoxContainer"]',
            'layout_mode = 2',
            'text = "Start Game"',
            "",
            f'[node name="QuitButton" type="Button" parent="VBoxContainer"]',
            'layout_mode = 2',
            'text = "Quit"',
            "",
        ])
        nodes = [name, "VBoxContainer", "TitleLabel", "StartButton", "QuitButton"]
        return "\n".join(lines), "Control", nodes

    @classmethod
    def parse_nodes(cls, content: str) -> list[dict[str, str]]:
        """Extract node entries from a .tscn text."""
        node_pattern = re.compile(r'\[node\s+name="([^"]+)"(?:\s+type="([^"]+)")?(?:\s+parent="([^"]+)")?')
        results = []
        for match in node_pattern.finditer(content):
            results.append({
                "name": match.group(1),
                "type": match.group(2) or "Node",
                "parent": match.group(3) or ".",
            })
        return results
