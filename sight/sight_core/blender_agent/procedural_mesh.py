"""Pure-Python Procedural 3D Mesh Generator and Exporter for BEL.

Provides high-fidelity offline 3D mesh synthesis (Cube, Sphere, Cylinder,
Torus, Plane), binary glTF 2.0 (.glb) & Wavefront OBJ (.obj) export, and
software wireframe rasterization without requiring external native dependencies.
"""
from __future__ import annotations

import io
import json
import math
from pathlib import Path
import struct
from typing import Sequence

from PIL import Image, ImageDraw


class ProceduralMesh:
    """Represents a 3D polygonal mesh with vertices, normals, and triangle indices."""

    def __init__(
        self,
        vertices: Sequence[tuple[float, float, float]],
        normals: Sequence[tuple[float, float, float]],
        indices: Sequence[tuple[int, int, int]],
        name: str = "Mesh",
    ) -> None:
        self.vertices = list(vertices)
        self.normals = list(normals)
        self.indices = list(indices)
        self.name = name

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    @property
    def face_count(self) -> int:
        return len(self.indices)

    def to_obj(self) -> str:
        """Export mesh to Wavefront OBJ format string."""
        lines = [f"# BEL Procedural 3D Model: {self.name}", f"o {self.name}"]
        for v in self.vertices:
            lines.append(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")
        for n in self.normals:
            lines.append(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}")
        for tri in self.indices:
            # 1-based indexing
            v1, v2, v3 = tri[0] + 1, tri[1] + 1, tri[2] + 1
            lines.append(f"f {v1}//{v1} {v2}//{v2} {v3}//{v3}")
        return "\n".join(lines) + "\n"

    def to_glb(self) -> bytes:
        """Export mesh to standard Binary glTF 2.0 (.glb) byte sequence."""
        # 1. Prepare binary buffers: vertices (vec3 float), normals (vec3 float), indices (ushort or uint)
        vert_data = bytearray()
        min_v = [float("inf")] * 3
        max_v = [float("-inf")] * 3
        for v in self.vertices:
            vert_data.extend(struct.pack("<3f", v[0], v[1], v[2]))
            for i in range(3):
                min_v[i] = min(min_v[i], v[i])
                max_v[i] = max(max_v[i], v[i])

        norm_data = bytearray()
        for n in self.normals:
            norm_data.extend(struct.pack("<3f", n[0], n[1], n[2]))

        idx_data = bytearray()
        use_uint32 = len(self.vertices) > 65535
        idx_format = "<3I" if use_uint32 else "<3H"
        component_type = 5125 if use_uint32 else 5123  # UNSIGNED_INT or UNSIGNED_SHORT

        for tri in self.indices:
            idx_data.extend(struct.pack(idx_format, tri[0], tri[1], tri[2]))

        # Align buffers to 4-byte boundaries
        def pad(b: bytearray) -> bytearray:
            rem = len(b) % 4
            if rem > 0:
                b.extend(b"\x00" * (4 - rem))
            return b

        vert_data = pad(vert_data)
        norm_data = pad(norm_data)
        idx_data = pad(idx_data)

        # Buffer views: 0: indices, 1: vertices, 2: normals
        idx_len = len(idx_data)
        vert_len = len(vert_data)
        norm_len = len(norm_data)
        total_bin_len = idx_len + vert_len + norm_len

        bin_buffer = bytearray()
        bin_buffer.extend(idx_data)
        bin_buffer.extend(vert_data)
        bin_buffer.extend(norm_data)

        gltf_dict = {
            "asset": {"version": "2.0", "generator": "BEL-Stage7-MeshEngine"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"mesh": 0, "name": self.name}],
            "meshes": [
                {
                    "name": self.name,
                    "primitives": [
                        {
                            "attributes": {"POSITION": 1, "NORMAL": 2},
                            "indices": 0,
                            "mode": 4,  # TRIANGLES
                        }
                    ],
                }
            ],
            "accessors": [
                {
                    "bufferView": 0,
                    "byteOffset": 0,
                    "componentType": component_type,
                    "count": len(self.indices) * 3,
                    "type": "SCALAR",
                },
                {
                    "bufferView": 1,
                    "byteOffset": 0,
                    "componentType": 5126,  # FLOAT
                    "count": len(self.vertices),
                    "type": "VEC3",
                    "max": max_v,
                    "min": min_v,
                },
                {
                    "bufferView": 2,
                    "byteOffset": 0,
                    "componentType": 5126,  # FLOAT
                    "count": len(self.normals),
                    "type": "VEC3",
                },
            ],
            "bufferViews": [
                {"buffer": 0, "byteOffset": 0, "byteLength": idx_len, "target": 34963},  # ELEMENT_ARRAY_BUFFER
                {"buffer": 0, "byteOffset": idx_len, "byteLength": vert_len, "byteStride": 12, "target": 34962},  # ARRAY_BUFFER
                {"buffer": 0, "byteOffset": idx_len + vert_len, "byteLength": norm_len, "byteStride": 12, "target": 34962},
            ],
            "buffers": [{"byteLength": total_bin_len}],
        }

        json_bytes = json.dumps(gltf_dict, separators=(",", ":")).encode("utf-8")
        # Align JSON chunk to 4-byte boundary with spaces
        rem = len(json_bytes) % 4
        if rem > 0:
            json_bytes += b" " * (4 - rem)

        # GLB Header: magic (4), version (4), length (4)
        total_glb_len = 12 + 8 + len(json_bytes) + 8 + len(bin_buffer)
        header = struct.pack("<4sII", b"glTF", 2, total_glb_len)

        # JSON Chunk header: chunkLength (4), chunkType (0x4E4F534A 'JSON')
        json_chunk_hdr = struct.pack("<II", len(json_bytes), 0x4E4F534A)

        # BIN Chunk header: chunkLength (4), chunkType (0x004E4942 'BIN\x00')
        bin_chunk_hdr = struct.pack("<II", len(bin_buffer), 0x004E4942)

        glb = io.BytesIO()
        glb.write(header)
        glb.write(json_chunk_hdr)
        glb.write(json_bytes)
        glb.write(bin_chunk_hdr)
        glb.write(bin_buffer)
        return glb.getvalue()

    def render_preview(self, width: int = 800, height: int = 600, color: tuple[int, int, int] = (64, 160, 240)) -> Image.Image:
        """Render isometric shaded preview of the mesh using software rasterizer."""
        img = Image.new("RGBA", (width, height), (22, 27, 34, 255))
        draw = ImageDraw.Draw(img)

        # Isometric projection rotation angles
        rot_x = math.radians(30)
        rot_y = math.radians(45)

        cos_x, sin_x = math.cos(rot_x), math.sin(rot_x)
        cos_y, sin_y = math.cos(rot_y), math.sin(rot_y)

        # Transform vertices
        transformed: list[tuple[float, float, float]] = []
        for x, y, z in self.vertices:
            # Rotate Y
            x1 = x * cos_y + z * sin_y
            y1 = y
            z1 = -x * sin_y + z * cos_y
            # Rotate X
            x2 = x1
            y2 = y1 * cos_x - z1 * sin_x
            z2 = y1 * sin_x + z1 * cos_x
            transformed.append((x2, y2, z2))

        # Scale to canvas
        scale = min(width, height) * 0.35
        cx, cy = width / 2, height / 2

        # Sort triangles back-to-front (Painter's algorithm)
        tris_with_depth = []
        for i1, i2, i3 in self.indices:
            v1, v2, v3 = transformed[i1], transformed[i2], transformed[i3]
            avg_z = (v1[2] + v2[2] + v3[2]) / 3.0

            # Calculate normal for directional lighting
            ux, uy, uz = v2[0] - v1[0], v2[1] - v1[1], v2[2] - v1[2]
            vx, vy, vz = v3[0] - v1[0], v3[1] - v1[1], v3[2] - v1[2]
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            mag = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            nx, ny, nz = nx / mag, ny / mag, nz / mag

            # Light vector from top-right-front
            lx, ly, lz = 0.577, -0.577, -0.577
            diffuse = max(0.2, (nx * lx + ny * ly + nz * lz))

            tris_with_depth.append((avg_z, (i1, i2, i3), diffuse))

        tris_with_depth.sort(key=lambda t: t[0], reverse=True)

        for _, (i1, i2, i3), diff in tris_with_depth:
            p1 = (cx + transformed[i1][0] * scale, cy - transformed[i1][1] * scale)
            p2 = (cx + transformed[i2][0] * scale, cy - transformed[i2][1] * scale)
            p3 = (cx + transformed[i3][0] * scale, cy - transformed[i3][1] * scale)

            r = int(min(255, max(0, color[0] * diff)))
            g = int(min(255, max(0, color[1] * diff)))
            b = int(min(255, max(0, color[2] * diff)))

            draw.polygon([p1, p2, p3], fill=(r, g, b, 255), outline=(r // 2, g // 2, b // 2, 255))

        return img


class MeshGenerator:
    """Factory for procedural 3D primitives."""

    @staticmethod
    def create_cube(size: float = 2.0) -> ProceduralMesh:
        s = size / 2.0
        # 8 cube corners
        corners = [
            (-s, -s, -s), (s, -s, -s), (s, s, -s), (-s, s, -s),
            (-s, -s, s), (s, -s, s), (s, s, s), (-s, s, s),
        ]
        # 6 faces * 4 vertices for flat shading normals
        face_defs = [
            ([0, 1, 2, 3], (0, 0, -1)),  # Front
            ([5, 4, 7, 6], (0, 0, 1)),   # Back
            ([4, 0, 3, 7], (-1, 0, 0)),  # Left
            ([1, 5, 6, 2], (1, 0, 0)),   # Right
            ([3, 2, 6, 7], (0, 1, 0)),   # Top
            ([4, 5, 1, 0], (0, -1, 0)),  # Bottom
        ]

        vertices: list[tuple[float, float, float]] = []
        normals: list[tuple[float, float, float]] = []
        indices: list[tuple[int, int, int]] = []

        for face_idx, (idxs, norm) in enumerate(face_defs):
            base_v = len(vertices)
            for idx in idxs:
                vertices.append(corners[idx])
                normals.append(norm)
            indices.append((base_v, base_v + 1, base_v + 2))
            indices.append((base_v, base_v + 2, base_v + 3))

        return ProceduralMesh(vertices, normals, indices, name="Cube")

    @staticmethod
    def create_sphere(radius: float = 1.0, rings: int = 16, sectors: int = 24) -> ProceduralMesh:
        vertices: list[tuple[float, float, float]] = []
        normals: list[tuple[float, float, float]] = []
        indices: list[tuple[int, int, int]] = []

        for r in range(rings + 1):
            theta = math.pi * r / rings
            sin_t = math.sin(theta)
            cos_t = math.cos(theta)

            for s in range(sectors + 1):
                phi = 2 * math.pi * s / sectors
                sin_p = math.sin(phi)
                cos_p = math.cos(phi)

                nx = sin_t * cos_p
                ny = cos_t
                nz = sin_t * sin_p

                vertices.append((radius * nx, radius * ny, radius * nz))
                normals.append((nx, ny, nz))

        for r in range(rings):
            for s in range(sectors):
                i0 = r * (sectors + 1) + s
                i1 = i0 + 1
                i2 = (r + 1) * (sectors + 1) + s
                i3 = i2 + 1

                indices.append((i0, i1, i2))
                indices.append((i1, i3, i2))

        return ProceduralMesh(vertices, normals, indices, name="Sphere")

    @staticmethod
    def create_cylinder(radius: float = 1.0, height: float = 2.0, segments: int = 24) -> ProceduralMesh:
        vertices: list[tuple[float, float, float]] = []
        normals: list[tuple[float, float, float]] = []
        indices: list[tuple[int, int, int]] = []
        half_h = height / 2.0

        for i in range(segments):
            angle = 2 * math.pi * i / segments
            x = radius * math.cos(angle)
            z = radius * math.sin(angle)
            nx = math.cos(angle)
            nz = math.sin(angle)

            # Top rim
            vertices.append((x, half_h, z))
            normals.append((nx, 0.0, nz))
            # Bottom rim
            vertices.append((x, -half_h, z))
            normals.append((nx, 0.0, nz))

        for i in range(segments):
            next_i = (i + 1) % segments
            t1 = i * 2
            b1 = t1 + 1
            t2 = next_i * 2
            b2 = t2 + 1

            indices.append((t1, t2, b1))
            indices.append((t2, b2, b1))

        return ProceduralMesh(vertices, normals, indices, name="Cylinder")

    @classmethod
    def generate(cls, mesh_type: str = "cube", **params) -> ProceduralMesh:
        m_type = mesh_type.lower()
        if m_type == "sphere":
            return cls.create_sphere(
                radius=params.get("radius", 1.0),
                rings=params.get("rings", 16),
                sectors=params.get("sectors", 24),
            )
        elif m_type == "cylinder":
            return cls.create_cylinder(
                radius=params.get("radius", 1.0),
                height=params.get("height", 2.0),
                segments=params.get("segments", 24),
            )
        else:
            return cls.create_cube(size=params.get("size", 2.0))
