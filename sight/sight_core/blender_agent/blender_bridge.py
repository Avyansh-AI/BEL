"""Blender 3D Automation Bridge for BEL (Stage 7).

Manages headless Blender automation via bpy script generation and subprocess
execution, with graceful pure-Python procedural fallback.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from .models import (
    BlenderStatus,
    MaterialProperties,
    MeshRequest,
    MeshResult,
    RenderRequest,
    RenderResult,
)
from .procedural_mesh import MeshGenerator


class BlenderAgent:
    """Manages 3D asset generation and rendering via Blender CLI or fallback engine."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self._executable: Path | None = self._discover_blender()

    def _discover_blender(self) -> Path | None:
        env_path = os.environ.get("BLENDER_BIN")
        if env_path and Path(env_path).exists():
            return Path(env_path)

        # Check PATH
        which_path = shutil.which("blender")
        if which_path:
            return Path(which_path)

        # Check standard Windows paths
        if os.name == "nt":
            patterns = [
                r"C:\Program Files\Blender Foundation\Blender *\blender.exe",
                r"C:\Program Files (x86)\Blender Foundation\Blender *\blender.exe",
                r"D:\Program Files\Blender Foundation\Blender *\blender.exe",
            ]
            for pat in patterns:
                candidates = sorted(glob.glob(pat))
                if candidates:
                    return Path(candidates[-1])  # Latest version
        return None

    def get_status(self) -> BlenderStatus:
        available = self._executable is not None and self._executable.exists()
        version = None
        if available:
            try:
                proc = subprocess.run(
                    [str(self._executable), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                first_line = proc.stdout.splitlines()[0] if proc.stdout else ""
                version = first_line.strip()
            except Exception:
                version = "Installed (Version query failed)"

        capabilities = [
            "procedural_3d_mesh_synthesis",
            "binary_gltf_glb_export",
            "wavefront_obj_export",
            "software_preview_rasterizer",
        ]
        if available:
            capabilities.extend([
                "blender_headless_cli",
                "cycles_raytracing",
                "eevee_realtime_render",
                "principled_bsdf_materials",
            ])

        return BlenderStatus(
            available=available,
            version=version,
            executable_path=str(self._executable) if self._executable else None,
            fallback_mode=not available,
            capabilities=capabilities,
        )

    def generate_mesh(self, request: MeshRequest) -> MeshResult:
        """Generate a 3D mesh model as .glb or .obj."""
        output_format = request.output_format.lower()
        if output_format not in ("glb", "obj", "gltf"):
            output_format = "glb"

        # Determine target file path
        if request.output_path:
            target_path = Path(request.output_path)
            if not target_path.is_absolute():
                target_path = self.workspace_root / target_path
        else:
            ext = f".{output_format}"
            target_path = self.workspace_root / f"{request.mesh_type}_{int(time.time())}{ext}"

        target_path.parent.mkdir(parents=True, exist_ok=True)

        # If Blender is available, we can run headless Blender export
        if self._executable and self._executable.exists():
            try:
                script = self._build_export_script(
                    mesh_type=request.mesh_type,
                    output_path=target_path,
                    output_format=output_format,
                    material=request.material,
                    params=request.parameters,
                )
                with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
                    tf.write(script)
                    temp_script = tf.name

                try:
                    proc = subprocess.run(
                        [str(self._executable), "-b", "-P", temp_script],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    if proc.returncode == 0 and target_path.exists():
                        return MeshResult(
                            success=True,
                            file_path=str(target_path),
                            format=output_format,
                            generated_by="blender_headless",
                        )
                finally:
                    try:
                        os.unlink(temp_script)
                    except Exception:
                        pass
            except Exception:
                # On any error, fall through to procedural engine
                pass

        # Fallback procedural generation
        mesh = MeshGenerator.generate(request.mesh_type, **request.parameters)
        if output_format == "obj":
            obj_text = mesh.to_obj()
            target_path.write_text(obj_text, encoding="utf-8")
        else:
            glb_bytes = mesh.to_glb()
            target_path.write_bytes(glb_bytes)

        return MeshResult(
            success=True,
            file_path=str(target_path),
            format=output_format,
            vertex_count=mesh.vertex_count,
            face_count=mesh.face_count,
            generated_by="procedural_engine",
        )

    def render_mesh(self, request: RenderRequest) -> RenderResult:
        """Render a 2D preview image of the 3D mesh."""
        start_t = time.monotonic()
        if request.output_path:
            target_path = Path(request.output_path)
            if not target_path.is_absolute():
                target_path = self.workspace_root / target_path
        else:
            target_path = self.workspace_root / f"{request.mesh_type}_render_{int(time.time())}.png"

        target_path.parent.mkdir(parents=True, exist_ok=True)

        # If Blender is available, use Blender Cycles/EEVEE headless render
        if self._executable and self._executable.exists():
            try:
                script = self._build_render_script(
                    mesh_type=request.mesh_type,
                    output_path=target_path,
                    res_x=request.resolution[0],
                    res_y=request.resolution[1],
                    material=request.material,
                    samples=request.samples,
                )
                with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
                    tf.write(script)
                    temp_script = tf.name

                try:
                    proc = subprocess.run(
                        [str(self._executable), "-b", "-P", temp_script],
                        capture_output=True,
                        text=True,
                        timeout=90,
                    )
                    if proc.returncode == 0 and target_path.exists():
                        duration = time.monotonic() - start_t
                        return RenderResult(
                            success=True,
                            image_path=str(target_path),
                            resolution=request.resolution,
                            engine="blender_headless",
                            duration_sec=round(duration, 3),
                        )
                finally:
                    try:
                        os.unlink(temp_script)
                    except Exception:
                        pass
            except Exception:
                pass

        # Fallback software rasterizer
        mesh = MeshGenerator.generate(request.mesh_type, **request.parameters)
        color_rgba = request.material.base_color
        r = int(color_rgba[0] * 255) if len(color_rgba) > 0 else 64
        g = int(color_rgba[1] * 255) if len(color_rgba) > 1 else 160
        b = int(color_rgba[2] * 255) if len(color_rgba) > 2 else 240

        img = mesh.render_preview(width=request.resolution[0], height=request.resolution[1], color=(r, g, b))
        img.save(str(target_path), format="PNG")
        duration = time.monotonic() - start_t

        return RenderResult(
            success=True,
            image_path=str(target_path),
            resolution=request.resolution,
            engine="software_rasterizer",
            duration_sec=round(duration, 3),
        )

    def _build_export_script(
        self,
        mesh_type: str,
        output_path: Path,
        output_format: str,
        material: MaterialProperties,
        params: dict,
    ) -> str:
        out_esc = str(output_path).replace("\\", "\\\\")
        return f"""
import bpy
import sys

# Reset scene
bpy.ops.wm.read_factory_settings(use_empty=True)

# Create mesh
mesh_type = "{mesh_type.lower()}"
if mesh_type == "sphere":
    bpy.ops.mesh.primitive_uv_sphere_add(radius={params.get('radius', 1.0)})
elif mesh_type == "cylinder":
    bpy.ops.mesh.primitive_cylinder_add(radius={params.get('radius', 1.0)}, depth={params.get('height', 2.0)})
else:
    bpy.ops.mesh.primitive_cube_add(size={params.get('size', 2.0)})

obj = bpy.context.active_object
mat = bpy.data.materials.new(name="BEL_Material")
mat.use_nodes = True
nodes = mat.node_tree.nodes
bsdf = nodes.get("Principled BSDF")
if bsdf:
    bsdf.inputs['Base Color'].default_value = {material.base_color}
    bsdf.inputs['Metallic'].default_value = {material.metallic}
    bsdf.inputs['Roughness'].default_value = {material.roughness}

obj.data.materials.append(mat)

# Export
format_choice = "{output_format.lower()}"
if format_choice in ("glb", "gltf"):
    bpy.ops.export_scene.gltf(filepath="{out_esc}", export_format='GLB')
elif format_choice == "obj":
    try:
        bpy.ops.wm.obj_export(filepath="{out_esc}")
    except Exception:
        bpy.ops.export_scene.obj(filepath="{out_esc}")
"""

    def _build_render_script(
        self,
        mesh_type: str,
        output_path: Path,
        res_x: int,
        res_y: int,
        material: MaterialProperties,
        samples: int,
    ) -> str:
        out_esc = str(output_path).replace("\\", "\\\\")
        return f"""
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)

# Create object
mesh_type = "{mesh_type.lower()}"
if mesh_type == "sphere":
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0)
elif mesh_type == "cylinder":
    bpy.ops.mesh.primitive_cylinder_add(radius=1.0, depth=2.0)
else:
    bpy.ops.mesh.primitive_cube_add(size=2.0)

obj = bpy.context.active_object

# Create Camera
bpy.ops.object.camera_add(location=(4.0, -4.0, 3.5), rotation=(1.0, 0.0, 0.785))
camera = bpy.context.active_object
bpy.context.scene.camera = camera

# Create Sun Light
bpy.ops.object.light_add(type='SUN', location=(5.0, -5.0, 10.0))
light = bpy.context.active_object
light.data.energy = 3.0

# Render settings
scene = bpy.context.scene
scene.render.resolution_x = {res_x}
scene.render.resolution_y = {res_y}
scene.render.filepath = "{out_esc}"
scene.render.image_settings.file_format = 'PNG'

bpy.ops.render.render(write_still=True)
"""
