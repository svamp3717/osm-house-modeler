from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
import queue
import secrets
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from PIL import Image, ImageDraw, ImageEnhance, ImageTk

from .builder import BUILDING_TYPE_OVERRIDES, build_way
from .styles import (
    clear_country_profile_cache,
    country_selector_label,
    discover_country_style_dir,
    discover_style_dir,
    find_country_profile,
    load_country_profiles,
    load_profiles,
)

Vec3 = tuple[float, float, float]
UV = tuple[float, float]


def _settings_path() -> Path:
    """Return a writable per-user settings path without external dependencies."""
    override = os.environ.get("OSM_HOUSE_MODELER_SETTINGS")
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        return base / "OSM House Modeler" / "settings.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OSM House Modeler" / "settings.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "osm-house-modeler" / "settings.json"


def _load_last_way_id() -> str:
    path = _settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = str(data.get("last_way_id", "")).strip()
        return value if value.isdigit() and int(value) > 0 else ""
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return ""


def _save_last_way_id(way_id: int) -> None:
    if int(way_id) <= 0:
        return
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"last_way_id": int(way_id)}, indent=2) + "\n"
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(payload, encoding="utf-8")
    temp.replace(path)


@dataclass(slots=True)
class PreviewMaterial:
    name: str
    colour: tuple[int, int, int] = (184, 184, 184)
    texture_path: Path | None = None


@dataclass(slots=True)
class PreviewFace:
    vertices: tuple[int, int, int]
    uvs: tuple[int | None, int | None, int | None]
    material: str


@dataclass(slots=True)
class PreviewDoorAnimation:
    hinge: Vec3
    open_angle_degrees: float
    vertex_indices: tuple[int, ...]


@dataclass(slots=True)
class PreviewMesh:
    vertices: list[Vec3]
    uvs: list[UV]
    faces: list[PreviewFace]
    materials: dict[str, PreviewMaterial]
    lo: Vec3
    hi: Vec3
    door_animations: list[PreviewDoorAnimation]


def _parse_mtl(path: Path) -> dict[str, PreviewMaterial]:
    materials: dict[str, PreviewMaterial] = {}
    current: PreviewMaterial | None = None
    if not path.is_file():
        return materials
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            key = parts[0]
            if key == "newmtl" and len(parts) >= 2:
                current = PreviewMaterial(parts[1])
                materials[current.name] = current
            elif current is not None and key == "Kd" and len(parts) >= 4:
                try:
                    rgb = tuple(max(0, min(255, round(float(v) * 255))) for v in parts[1:4])
                    current.colour = rgb  # type: ignore[assignment]
                except ValueError:
                    pass
            elif current is not None and key == "map_Kd" and len(parts) >= 2:
                try:
                    tokens = shlex.split(line[len("map_Kd"):].strip())
                except ValueError:
                    tokens = parts[1:]
                if tokens:
                    # Our exporter writes a simple filename. Taking the final token
                    # also behaves reasonably for many MTL option forms.
                    texture = Path(tokens[-1])
                    current.texture_path = texture if texture.is_absolute() else (path.parent / texture).resolve()
    return materials


def _obj_index(raw: str, count: int) -> int | None:
    if not raw:
        return None
    idx = int(raw)
    idx = count + idx if idx < 0 else idx - 1
    return idx if 0 <= idx < count else None


def load_obj_preview(path: Path) -> PreviewMesh:
    """Load OBJ geometry, UVs, MTL colours, and diffuse texture paths."""
    path = path.expanduser().resolve()
    vertices: list[Vec3] = []
    uvs: list[UV] = []
    faces: list[PreviewFace] = []
    materials: dict[str, PreviewMaterial] = {}
    material = "default"
    door_animations: list[PreviewDoorAnimation] = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("# osm3d_door_animation "):
                fields: dict[str, str] = {}
                for token in line[len("# osm3d_door_animation "):].split():
                    if "=" in token:
                        key, value = token.split("=", 1)
                        fields[key] = value
                try:
                    hinge_values = tuple(float(v) for v in fields["hinge"].split(","))
                    vertices_values = tuple(int(v) - 1 for v in fields["vertices"].split(",") if v)
                    if len(hinge_values) == 3 and vertices_values:
                        door_animations.append(PreviewDoorAnimation(
                            hinge_values, float(fields.get("open_angle", "0")), vertices_values
                        ))
                except (KeyError, ValueError):
                    pass
                continue
            if line.startswith("#"):
                continue
            if line.startswith("mtllib "):
                for filename in shlex.split(line.split(maxsplit=1)[1]):
                    materials.update(_parse_mtl((path.parent / filename).resolve()))
            elif line.startswith("v "):
                parts = line.split()
                if len(parts) >= 4:
                    vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif line.startswith("vt "):
                parts = line.split()
                if len(parts) >= 3:
                    uvs.append((float(parts[1]), float(parts[2])))
            elif line.startswith("usemtl "):
                material = line.split(maxsplit=1)[1].strip() or "default"
            elif line.startswith("f "):
                refs: list[tuple[int, int | None]] = []
                for token in line.split()[1:]:
                    fields = token.split("/")
                    vi = _obj_index(fields[0], len(vertices))
                    ti = _obj_index(fields[1], len(uvs)) if len(fields) > 1 else None
                    if vi is not None:
                        refs.append((vi, ti))
                if len(refs) >= 3:
                    for i in range(1, len(refs) - 1):
                        tri = (refs[0], refs[i], refs[i + 1])
                        faces.append(PreviewFace(
                            tuple(item[0] for item in tri),  # type: ignore[arg-type]
                            tuple(item[1] for item in tri),  # type: ignore[arg-type]
                            material,
                        ))
    if not vertices:
        raise ValueError(f"No vertices found in {path}")
    materials.setdefault("default", PreviewMaterial("default"))
    xs, ys, zs = zip(*vertices)
    return PreviewMesh(
        vertices, uvs, faces, materials,
        (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)),
        door_animations,
    )


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _add(a: Vec3, b: Vec3) -> Vec3:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _mul(a: Vec3, scalar: float) -> Vec3:
    return a[0] * scalar, a[1] * scalar, a[2] * scalar


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _normalise(a: Vec3) -> Vec3:
    length = math.sqrt(_dot(a, a)) or 1.0
    return a[0] / length, a[1] / length, a[2] / length


def _shade_rgb(colour: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.25, amount))
    return tuple(max(0, min(255, round(c * amount))) for c in colour)  # type: ignore[return-value]


def _affine_axis(dst: tuple[tuple[float, float], ...], values: tuple[float, float, float]) -> tuple[float, float, float] | None:
    (x0, y0), (x1, y1), (x2, y2) = dst
    q0, q1, q2 = values
    den = x0 * (y1 - y2) + x1 * (y2 - y0) + x2 * (y0 - y1)
    if abs(den) < 1e-8:
        return None
    a = (q0 * (y1 - y2) + q1 * (y2 - y0) + q2 * (y0 - y1)) / den
    b = (q0 * (x2 - x1) + q1 * (x0 - x2) + q2 * (x1 - x0)) / den
    c = (
        q0 * (x1 * y2 - x2 * y1)
        + q1 * (x2 * y0 - x0 * y2)
        + q2 * (x0 * y1 - x1 * y0)
    ) / den
    return a, b, c


class ModelCanvas(tk.Canvas):
    """Software textured 3D preview rendered into a Tk canvas with Pillow."""

    MATERIAL_COLOURS = {
        "wall": (201, 173, 140),
        "roof": (113, 92, 82),
        "window": (77, 122, 153),
        "window_frame": (210, 205, 192),
        "door": (87, 51, 28),
        "door_openable": (87, 51, 28),
        "interior_wall": (214, 210, 198),
        "interior_floor": (151, 128, 101),
        "interior_ceiling": (226, 223, 214),
        "foundation": (107, 110, 105),
        "balcony": (135, 132, 126),
        "detail_masonry": (139, 136, 128),
        "detail_wood": (139, 96, 61),
        "detail_metal": (100, 108, 112),
        "default": (184, 184, 184),
    }

    def __init__(self, master: tk.Misc, **kwargs) -> None:
        super().__init__(master, background="#17191d", highlightthickness=0, **kwargs)
        self.mesh: PreviewMesh | None = None
        self.model_path: Path | None = None
        self.target: Vec3 = (0.0, 0.0, 0.0)
        self.home_target: Vec3 = self.target
        self.distance = 10.0
        self.home_distance = 10.0
        self.yaw = math.radians(45)
        self.pitch = math.radians(28)
        self.wireframe = False
        self.show_axes = True
        self._drag_button = 0
        self._last_xy = (0, 0)
        self._pending_redraw: str | None = None
        self._textures: dict[str, Image.Image] = {}
        self._tile_cache: dict[tuple[str, int, int], Image.Image] = {}
        self._frame_photo: ImageTk.PhotoImage | None = None
        self._last_frame: Image.Image | None = None
        self._door_open_vertices: list[Vec3] = []
        self._door_is_open = True

        self.bind("<Configure>", lambda _e: self.request_redraw())
        self.bind("<ButtonPress-1>", lambda e: self._start_drag(e, 1))
        self.bind("<ButtonPress-2>", lambda e: self._start_drag(e, 2))
        self.bind("<ButtonPress-3>", lambda e: self._start_drag(e, 3))
        self.bind("<B1-Motion>", self._drag)
        self.bind("<B2-Motion>", self._drag)
        self.bind("<B3-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._end_drag)
        self.bind("<ButtonRelease-2>", self._end_drag)
        self.bind("<ButtonRelease-3>", self._end_drag)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", lambda _e: self._zoom_steps(1))
        self.bind("<Button-5>", lambda _e: self._zoom_steps(-1))
        self.bind("<KeyPress-o>", lambda _e: self.toggle_door())
        self.bind("<KeyPress-O>", lambda _e: self.toggle_door())

    def load(self, path: Path) -> None:
        self.mesh = load_obj_preview(path)
        self.model_path = path.expanduser().resolve()
        self._door_open_vertices = list(self.mesh.vertices)
        self._door_is_open = True
        self._textures.clear()
        self._tile_cache.clear()
        for name, material in self.mesh.materials.items():
            texture_path = material.texture_path
            if texture_path and texture_path.is_file():
                try:
                    texture = Image.open(texture_path).convert("RGB")
                    texture.thumbnail((96, 96), Image.Resampling.LANCZOS)
                    # OBJ V=0 is the image bottom; Pillow uses top-left origin.
                    self._textures[name] = texture.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                except OSError:
                    pass
        lo, hi = self.mesh.lo, self.mesh.hi
        self.home_target = tuple((lo[i] + hi[i]) * 0.5 for i in range(3))  # type: ignore[assignment]
        diagonal = math.sqrt(sum((hi[i] - lo[i]) ** 2 for i in range(3)))
        self.home_distance = max(6.0, diagonal * 1.8)
        self.reset_camera()

    def clear_model(self) -> None:
        self.mesh = None
        self.model_path = None
        self._door_open_vertices = []
        self._door_is_open = True
        self._textures.clear()
        self._tile_cache.clear()
        self.delete("all")
        self.create_text(
            max(1, self.winfo_width()) / 2,
            max(1, self.winfo_height()) / 2,
            text="Build or load an OBJ to preview it here",
            fill="#9ba3ae",
            font=("TkDefaultFont", 12),
        )

    def reset_camera(self) -> None:
        self.target = self.home_target
        self.distance = self.home_distance
        self.yaw = math.radians(45)
        self.pitch = math.radians(28)
        self.request_redraw()

    def set_wireframe(self, enabled: bool) -> None:
        self.wireframe = bool(enabled)
        self.request_redraw()

    def toggle_door(self) -> bool:
        """Toggle generated hinged doors between their saved open pose and closed pose."""
        if self.mesh is None or not self.mesh.door_animations or not self._door_open_vertices:
            return False
        if self._door_is_open:
            for animation in self.mesh.door_animations:
                angle = -math.radians(animation.open_angle_degrees)
                cos_a, sin_a = math.cos(angle), math.sin(angle)
                hx, hy, _hz = animation.hinge
                for index in animation.vertex_indices:
                    if not 0 <= index < len(self.mesh.vertices):
                        continue
                    x, y, z = self._door_open_vertices[index]
                    dx, dy = x - hx, y - hy
                    self.mesh.vertices[index] = (
                        hx + dx * cos_a - dy * sin_a,
                        hy + dx * sin_a + dy * cos_a,
                        z,
                    )
            self._door_is_open = False
        else:
            for animation in self.mesh.door_animations:
                for index in animation.vertex_indices:
                    if 0 <= index < len(self.mesh.vertices):
                        self.mesh.vertices[index] = self._door_open_vertices[index]
            self._door_is_open = True
        self.request_redraw()
        return True

    def _start_drag(self, event: tk.Event, button: int) -> None:
        self._drag_button = button
        self._last_xy = (event.x, event.y)
        self.focus_set()

    def _end_drag(self, _event: tk.Event) -> None:
        self._drag_button = 0

    def _drag(self, event: tk.Event) -> None:
        dx = event.x - self._last_xy[0]
        dy = event.y - self._last_xy[1]
        self._last_xy = (event.x, event.y)
        if self._drag_button == 1:
            self.yaw -= dx * 0.009
            self.pitch = max(math.radians(-85), min(math.radians(85), self.pitch + dy * 0.009))
        elif self._drag_button in {2, 3}:
            _eye, _forward, right, up = self._camera_basis()
            scale = self.distance * 0.0018
            self.target = _add(self.target, _add(_mul(right, -dx * scale), _mul(up, dy * scale)))
        self.request_redraw()

    def _wheel(self, event: tk.Event) -> None:
        delta = getattr(event, "delta", 0)
        if delta:
            self._zoom_steps(1 if delta > 0 else -1)

    def _zoom_steps(self, steps: int) -> None:
        self.distance = max(0.25, self.distance * (0.86 ** steps))
        self.request_redraw()

    def request_redraw(self) -> None:
        if self._pending_redraw is None:
            self._pending_redraw = self.after_idle(self._redraw)

    def _camera_basis(self) -> tuple[Vec3, Vec3, Vec3, Vec3]:
        cp = math.cos(self.pitch)
        eye = (
            self.target[0] + self.distance * cp * math.cos(self.yaw),
            self.target[1] + self.distance * cp * math.sin(self.yaw),
            self.target[2] + self.distance * math.sin(self.pitch),
        )
        forward = _normalise(_sub(self.target, eye))
        world_up = (0.0, 0.0, 1.0)
        right = _normalise(_cross(forward, world_up))
        if abs(_dot(right, right)) < 1e-8:
            right = (1.0, 0.0, 0.0)
        up = _normalise(_cross(right, forward))
        return eye, forward, right, up

    def _project(self, point: Vec3, basis: tuple[Vec3, Vec3, Vec3, Vec3], focal: float, w: int, h: int):
        eye, forward, right, up = basis
        rel = _sub(point, eye)
        z = _dot(rel, forward)
        if z <= 0.03:
            return None
        x = _dot(rel, right)
        y = _dot(rel, up)
        return (w * 0.5 + focal * x / z, h * 0.5 - focal * y / z, z)

    def _draw_axes(self, basis, focal: float, w: int, h: int) -> None:
        if not self.show_axes:
            return
        length = max(1.0, self.home_distance * 0.12)
        origin = self.target
        axes = [
            ((_add(origin, (length, 0.0, 0.0))), "#df6b65", "X"),
            ((_add(origin, (0.0, length, 0.0))), "#6fcf79", "Y"),
            ((_add(origin, (0.0, 0.0, length))), "#6ca6e8", "Z"),
        ]
        p0 = self._project(origin, basis, focal, w, h)
        if p0 is None:
            return
        for endpoint, colour, label in axes:
            p1 = self._project(endpoint, basis, focal, w, h)
            if p1 is None:
                continue
            self.create_line(p0[0], p0[1], p1[0], p1[1], fill=colour, width=2)
            self.create_text(p1[0] + 7, p1[1], text=label, fill=colour, font=("TkDefaultFont", 9, "bold"))

    def _material_colour(self, material_name: str) -> tuple[int, int, int]:
        if self.mesh is not None and material_name in self.mesh.materials:
            return self.mesh.materials[material_name].colour
        return self.MATERIAL_COLOURS.get(material_name, self.MATERIAL_COLOURS["default"])

    def _tiled_texture(self, material: str, tiles_x: int, tiles_y: int) -> Image.Image | None:
        texture = self._textures.get(material)
        if texture is None:
            return None
        tiles_x = max(1, min(34, tiles_x))
        tiles_y = max(1, min(34, tiles_y))
        key = (material, tiles_x, tiles_y)
        cached = self._tile_cache.get(key)
        if cached is not None:
            return cached
        tw, th = texture.size
        tiled = Image.new("RGB", (tw * tiles_x, th * tiles_y))
        for y in range(tiles_y):
            for x in range(tiles_x):
                tiled.paste(texture, (x * tw, y * th))
        self._tile_cache[key] = tiled
        return tiled

    def _paint_textured_triangle(
        self,
        frame: Image.Image,
        material: str,
        points: tuple[tuple[float, float, float], ...],
        face_uvs: tuple[UV, UV, UV],
        intensity: float,
    ) -> bool:
        # Limit pathological repeat counts in the interactive preview while still
        # preserving the repeated appearance. The exported OBJ UVs remain exact.
        uv_list = [list(uv) for uv in face_uvs]
        for axis in (0, 1):
            low = min(uv[axis] for uv in uv_list)
            high = max(uv[axis] for uv in uv_list)
            span = high - low
            if span > 32.0:
                scale = 32.0 / span
                for uv in uv_list:
                    uv[axis] = low + (uv[axis] - low) * scale

        min_u = math.floor(min(uv[0] for uv in uv_list))
        min_v = math.floor(min(uv[1] for uv in uv_list))
        max_u = math.ceil(max(uv[0] for uv in uv_list))
        max_v = math.ceil(max(uv[1] for uv in uv_list))
        tiled = self._tiled_texture(material, max_u - min_u + 1, max_v - min_v + 1)
        base = self._textures.get(material)
        if tiled is None or base is None:
            return False
        tex_w, tex_h = base.size
        src = tuple(((uv[0] - min_u) * tex_w, (uv[1] - min_v) * tex_h) for uv in uv_list)

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x0 = max(0, math.floor(min(xs)))
        y0 = max(0, math.floor(min(ys)))
        x1 = min(frame.width, math.ceil(max(xs)) + 1)
        y1 = min(frame.height, math.ceil(max(ys)) + 1)
        if x1 <= x0 or y1 <= y0:
            return False

        dst_local = tuple((p[0] - x0, p[1] - y0) for p in points)
        ax = _affine_axis(dst_local, (src[0][0], src[1][0], src[2][0]))
        ay = _affine_axis(dst_local, (src[0][1], src[1][1], src[2][1]))
        if ax is None or ay is None:
            return False

        patch = tiled.transform(
            (x1 - x0, y1 - y0),
            Image.Transform.AFFINE,
            (ax[0], ax[1], ax[2], ay[0], ay[1], ay[2]),
            resample=Image.Resampling.BILINEAR,
        )
        if abs(intensity - 1.0) > 0.01:
            patch = ImageEnhance.Brightness(patch).enhance(intensity)
        mask = Image.new("L", patch.size, 0)
        ImageDraw.Draw(mask).polygon(dst_local, fill=255)
        frame.paste(patch, (x0, y0), mask)
        return True

    def _redraw(self) -> None:
        self._pending_redraw = None
        self.delete("all")
        w, h = max(2, self.winfo_width()), max(2, self.winfo_height())
        if self.mesh is None:
            self.create_text(w / 2, h / 2, text="Build or load an OBJ to preview it here", fill="#9ba3ae")
            return

        basis = self._camera_basis()
        focal = min(w, h) * 0.9
        projected = [self._project(v, basis, focal, w, h) for v in self.mesh.vertices]
        light = _normalise((0.35, -0.55, 0.76))
        draw_faces: list[tuple[float, int, PreviewFace, tuple[tuple[float, float, float], ...]]] = []
        raw_depths: dict[int, float] = {}
        projected_faces: dict[int, tuple[tuple[float, float, float], ...]] = {}
        for face_index, face in enumerate(self.mesh.faces):
            points = tuple(projected[i] for i in face.vertices)
            if any(p is None for p in points):
                continue
            typed = points  # type: ignore[assignment]
            projected_faces[face_index] = typed
            raw_depths[face_index] = sum(p[2] for p in typed) / 3.0

        # Windows and doors are emitted as two triangles per facade quad. A pure
        # triangle-centroid painter sort can place a large wall triangle between
        # those two tiny triangles, making rectangular windows look mysteriously
        # bitten in half. Give each feature pair one shared depth so it paints as
        # a unit. The OpenGL viewer uses a real depth buffer and does not need this.
        feature_depths: dict[int, float] = {}
        for material in ("window", "door"):
            indices = [
                i for i, face in enumerate(self.mesh.faces)
                if face.material == material and i in raw_depths
            ]
            for start in range(0, len(indices), 2):
                pair = indices[start:start + 2]
                if not pair:
                    continue
                shared = sum(raw_depths[i] for i in pair) / len(pair)
                # Small visual bias toward the camera keeps facade panels in front
                # of the coplanar wall in this software preview.
                shared -= max(1e-4, self.distance * 2e-5)
                for i in pair:
                    feature_depths[i] = shared

        for face_index, face in enumerate(self.mesh.faces):
            if face_index not in projected_faces:
                continue
            depth = feature_depths.get(face_index, raw_depths[face_index])
            draw_faces.append((depth, face_index, face, projected_faces[face_index]))
        draw_faces.sort(key=lambda item: item[0], reverse=True)

        frame = Image.new("RGB", (w, h), (23, 25, 29))
        draw = ImageDraw.Draw(frame)
        for _depth, _face_index, face, points in draw_faces:
            xy = tuple((p[0], p[1]) for p in points)
            a, b, c = (self.mesh.vertices[i] for i in face.vertices)
            normal = _normalise(_cross(_sub(b, a), _sub(c, a)))
            intensity = 0.42 + 0.58 * abs(_dot(normal, light))
            if self.wireframe:
                draw.line((*xy, xy[0]), fill=(135, 145, 157), width=1)
                continue

            painted = False
            if face.material in self._textures and all(i is not None for i in face.uvs):
                face_uvs = tuple(self.mesh.uvs[i] for i in face.uvs if i is not None)
                if len(face_uvs) == 3:
                    painted = self._paint_textured_triangle(frame, face.material, points, face_uvs, intensity)  # type: ignore[arg-type]
            if not painted:
                colour = _shade_rgb(self._material_colour(face.material), intensity)
                outline = _shade_rgb(colour, 0.72)
                draw.polygon(xy, fill=colour, outline=outline)

        self._last_frame = frame.copy()
        self._frame_photo = ImageTk.PhotoImage(frame)
        self.create_image(0, 0, anchor="nw", image=self._frame_photo)
        self._draw_axes(basis, focal, w, h)
        textured_count = sum(1 for name in self.mesh.materials if name in self._textures)
        self.create_text(
            10,
            10,
            anchor="nw",
            text=(
                f"{self.model_path.name if self.model_path else 'model'}  •  textures: {textured_count}\n"
                "Left drag: orbit  •  Right drag: pan  •  Wheel: zoom  •  O: door"
            ),
            fill="#c8cdd4",
            font=("TkDefaultFont", 9),
        )


class OSM3DApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("OSM House Modeler")
        self.geometry("1280x820")
        self.minsize(980, 640)
        self.current_model: Path | None = None
        self._busy = False
        self._worker_events: queue.Queue[tuple[str, object, object | None]] = queue.Queue()
        self._wall_image: tk.PhotoImage | None = None
        self._roof_image: tk.PhotoImage | None = None

        self.way_var = tk.StringVar(value=_load_last_way_id())
        self.output_var = tk.StringVar(value=str(Path.cwd() / "osm3d-output"))
        self.style_path_var = tk.StringVar(value=str(discover_style_dir() or (Path.cwd() / "house_styles")))
        self.country_style_path_var = tk.StringVar(value=str(discover_country_style_dir() or (Path.cwd() / "country_styles")))
        self.preset_var = tk.StringVar(value="auto")
        self.country_preset_var = tk.StringVar(value="auto")
        self._country_profiles = ()
        self.building_type_var = tk.StringVar(value="auto")
        self.interior_mode_var = tk.StringVar(value="Exterior only")
        self.context_var = tk.StringVar(value="auto")
        self.timeout_var = tk.StringVar(value="20")
        self.seed_var = tk.StringVar(value="0")
        self.foundation_var = tk.StringVar(value="auto")
        self.windows_var = tk.BooleanVar(value=True)
        self.doors_var = tk.BooleanVar(value=True)
        self.details_var = tk.BooleanVar(value=True)
        self.wireframe_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")
        self.model_var = tk.StringVar(value="No model loaded")

        self._configure_style()
        self._build_ui()
        self.refresh_presets()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(50, self._poll_worker_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        for candidate in ("vista", "clam", "alt"):
            if candidate in style.theme_names():
                try:
                    style.theme_use(candidate)
                except tk.TclError:
                    pass
                break
        style.configure("Title.TLabel", font=("TkDefaultFont", 16, "bold"))
        style.configure("Primary.TButton", padding=(12, 8))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="OSM House Modeler", style="Title.TLabel").pack(side="left")
        ttk.Label(header, textvariable=self.model_var).pack(side="right")

        paned = ttk.Panedwindow(outer, orient="horizontal")
        paned.pack(fill="both", expand=True)

        # The control column can easily become taller than the available window
        # once country/style/interior options are enabled. Keep the preview fixed
        # and put the entire left column inside one vertically scrollable viewport.
        controls_shell = ttk.Frame(paned, width=340)
        paned.add(controls_shell, weight=0)
        content = ttk.Frame(paned)
        paned.add(content, weight=1)

        controls_canvas = tk.Canvas(
            controls_shell, width=330, highlightthickness=0, borderwidth=0,
            background=ttk.Style(self).lookup("TFrame", "background") or self.cget("background"),
        )
        controls_scrollbar = ttk.Scrollbar(controls_shell, orient="vertical", command=controls_canvas.yview)
        controls_canvas.configure(yscrollcommand=controls_scrollbar.set)
        controls_canvas.pack(side="left", fill="both", expand=True)
        controls_scrollbar.pack(side="right", fill="y")

        controls = ttk.Frame(controls_canvas, padding=(0, 0, 8, 0))
        controls_window = controls_canvas.create_window((0, 0), window=controls, anchor="nw")
        self.controls_canvas = controls_canvas
        self.controls_frame = controls
        self._controls_canvas_window = controls_window

        def update_scrollregion(_event: tk.Event | None = None) -> None:
            controls_canvas.configure(scrollregion=controls_canvas.bbox("all"))

        def fit_controls_width(event: tk.Event) -> None:
            controls_canvas.itemconfigure(controls_window, width=max(1, event.width))

        controls.bind("<Configure>", update_scrollregion)
        controls_canvas.bind("<Configure>", fit_controls_width)
        # Bind at the toplevel so the wheel works over labels, entries, checkboxes,
        # and buttons too. The handler ignores events outside the left viewport, so
        # preview zoom keeps its normal wheel behaviour.
        self.bind("<MouseWheel>", self._on_controls_mousewheel, add="+")
        self.bind("<Button-4>", self._on_controls_mousewheel, add="+")
        self.bind("<Button-5>", self._on_controls_mousewheel, add="+")

        build_box = ttk.LabelFrame(controls, text="Build from OpenStreetMap", padding=10)
        build_box.pack(fill="x")
        self._field(build_box, "OSM way ID", self.way_var)
        self._path_field(build_box, "Output folder", self.output_var, self._browse_output)

        ttk.Label(build_box, text="Regional preset").pack(anchor="w", pady=(8, 2))
        self.preset_combo = ttk.Combobox(build_box, textvariable=self.preset_var, state="readonly")
        self.preset_combo.pack(fill="x")
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_region_selected)

        ttk.Label(build_box, text="Country preset").pack(anchor="w", pady=(8, 2))
        self.country_preset_combo = ttk.Combobox(
            build_box, textvariable=self.country_preset_var, state="readonly"
        )
        self.country_preset_combo.pack(fill="x")
        self.country_preset_combo.bind("<<ComboboxSelected>>", self._on_country_selected)

        ttk.Label(build_box, text="Building type override").pack(anchor="w", pady=(8, 2))
        self.building_type_combo = ttk.Combobox(
            build_box,
            textvariable=self.building_type_var,
            values=BUILDING_TYPE_OVERRIDES,
            state="readonly",
        )
        self.building_type_combo.pack(fill="x")

        ttk.Label(build_box, text="Interior mode").pack(anchor="w", pady=(8, 2))
        self.interior_mode_combo = ttk.Combobox(
            build_box,
            textvariable=self.interior_mode_var,
            values=("Exterior only", "Simple interior"),
            state="readonly",
        )
        self.interior_mode_combo.pack(fill="x")

        row = ttk.Frame(build_box)
        row.pack(fill="x", pady=(8, 0))
        left = ttk.Frame(row)
        left.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Label(left, text="Context").pack(anchor="w")
        ttk.Combobox(left, textvariable=self.context_var, values=("auto", "rural", "town_city"), state="readonly").pack(fill="x")
        right = ttk.Frame(row)
        right.pack(side="left", fill="x", expand=True, padx=(5, 0))
        ttk.Label(right, text="Timeout (s)").pack(anchor="w")
        ttk.Entry(right, textvariable=self.timeout_var).pack(fill="x")

        procedural_row = ttk.Frame(build_box)
        procedural_row.pack(fill="x", pady=(8, 0))
        seed_col = ttk.Frame(procedural_row)
        seed_col.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Label(seed_col, text="Procedural seed").pack(anchor="w")
        ttk.Entry(seed_col, textvariable=self.seed_var).pack(fill="x")
        foundation_col = ttk.Frame(procedural_row)
        foundation_col.pack(side="left", fill="x", expand=True, padx=(5, 0))
        ttk.Label(foundation_col, text="Foundation depth (m / auto)").pack(anchor="w")
        ttk.Entry(foundation_col, textvariable=self.foundation_var).pack(fill="x")

        features = ttk.Frame(build_box)
        features.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(features, text="Windows", variable=self.windows_var).pack(side="left")
        ttk.Checkbutton(features, text="Doors", variable=self.doors_var).pack(side="left", padx=(14, 0))
        ttk.Checkbutton(features, text="Exterior details", variable=self.details_var).pack(side="left", padx=(14, 0))

        self.build_button = ttk.Button(build_box, text="Build model", style="Primary.TButton", command=self.build_model)
        self.build_button.pack(fill="x", pady=(12, 0))
        self.regenerate_button = ttk.Button(
            build_box, text="Regenerate with new seed", command=self.regenerate_with_new_seed
        )
        self.regenerate_button.pack(fill="x", pady=(6, 0))

        styles_box = ttk.LabelFrame(controls, text="Local architecture data", padding=10)
        styles_box.pack(fill="x", pady=(10, 0))
        ttk.Label(styles_box, text="24 regional profiles").pack(anchor="w")
        ttk.Label(styles_box, textvariable=self.style_path_var, wraplength=285).pack(anchor="w")
        ttk.Button(styles_box, text="Open house_styles folder", command=self.open_styles_folder).pack(fill="x", pady=(6, 0))
        ttk.Label(styles_box, text="249 country profiles").pack(anchor="w", pady=(8, 0))
        ttk.Label(styles_box, textvariable=self.country_style_path_var, wraplength=285).pack(anchor="w")
        ttk.Button(styles_box, text="Open country_styles folder", command=self.open_country_styles_folder).pack(fill="x", pady=(6, 0))
        ttk.Button(styles_box, text="Reload presets", command=self.refresh_presets).pack(fill="x", pady=(6, 0))

        files_box = ttk.LabelFrame(controls, text="Model", padding=10)
        files_box.pack(fill="x", pady=(10, 0))
        ttk.Button(files_box, text="Load existing OBJ", command=self.load_existing).pack(fill="x")
        ttk.Button(files_box, text="Open output folder", command=self.open_output_folder).pack(fill="x", pady=(6, 0))
        ttk.Button(files_box, text="Open OpenGL viewer", command=self.open_external_viewer).pack(fill="x", pady=(6, 0))

        help_box = ttk.LabelFrame(controls, text="Preview controls", padding=10)
        help_box.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(help_box, text="Wireframe", variable=self.wireframe_var, command=lambda: self.preview.set_wireframe(self.wireframe_var.get())).pack(anchor="w")
        ttk.Button(help_box, text="Reset camera", command=lambda: self.preview.reset_camera()).pack(fill="x", pady=(6, 0))
        ttk.Button(help_box, text="Open / close generated door", command=self.toggle_preview_door).pack(fill="x", pady=(6, 0))

        notebook = ttk.Notebook(content)
        notebook.pack(fill="both", expand=True)

        preview_tab = ttk.Frame(notebook)
        metadata_tab = ttk.Frame(notebook)
        log_tab = ttk.Frame(notebook)
        notebook.add(preview_tab, text="Preview")
        notebook.add(metadata_tab, text="Metadata")
        notebook.add(log_tab, text="Log")

        self.preview = ModelCanvas(preview_tab)
        self.preview.pack(fill="both", expand=True)

        texture_strip = ttk.Frame(preview_tab, padding=(8, 6))
        texture_strip.pack(fill="x")
        ttk.Label(texture_strip, text="Wall texture:").pack(side="left")
        self.wall_texture_label = ttk.Label(texture_strip, text="not generated")
        self.wall_texture_label.pack(side="left", padx=(6, 18))
        ttk.Label(texture_strip, text="Roof texture:").pack(side="left")
        self.roof_texture_label = ttk.Label(texture_strip, text="not generated")
        self.roof_texture_label.pack(side="left", padx=(6, 0))

        meta_frame = ttk.Frame(metadata_tab, padding=8)
        meta_frame.pack(fill="both", expand=True)
        self.metadata_text = tk.Text(meta_frame, wrap="none", font=("TkFixedFont", 10), undo=False)
        meta_y = ttk.Scrollbar(meta_frame, orient="vertical", command=self.metadata_text.yview)
        meta_x = ttk.Scrollbar(meta_frame, orient="horizontal", command=self.metadata_text.xview)
        self.metadata_text.configure(yscrollcommand=meta_y.set, xscrollcommand=meta_x.set)
        self.metadata_text.grid(row=0, column=0, sticky="nsew")
        meta_y.grid(row=0, column=1, sticky="ns")
        meta_x.grid(row=1, column=0, sticky="ew")
        meta_frame.rowconfigure(0, weight=1)
        meta_frame.columnconfigure(0, weight=1)

        log_frame = ttk.Frame(log_tab, padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, wrap="word", state="disabled", font=("TkFixedFont", 10))
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(8, 0))
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=180)
        self.progress.pack(side="left")
        ttk.Label(bottom, textvariable=self.status_var).pack(side="left", padx=(10, 0))

        self.preview.clear_model()

    def _on_controls_mousewheel(self, event: tk.Event) -> str | None:
        """Scroll the left control viewport only when the pointer is over it."""
        canvas = getattr(self, "controls_canvas", None)
        controls = getattr(self, "controls_frame", None)
        if canvas is None or controls is None:
            return None
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, AttributeError):
            return None
        current = widget
        inside = False
        while current is not None:
            if current is canvas or current is controls:
                inside = True
                break
            current = getattr(current, "master", None)
        if not inside:
            return None

        number = getattr(event, "num", None)
        delta = getattr(event, "delta", 0)
        if number == 4:
            units = -3
        elif number == 5:
            units = 3
        elif delta:
            # Windows typically reports +/-120 per notch; trackpads may report
            # smaller deltas, where a single unit keeps scrolling responsive.
            units = -int(delta / 120) * 3 if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        else:
            return None
        canvas.yview_scroll(units, "units")
        return "break"

    def _field(self, parent: ttk.Frame, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).pack(anchor="w", pady=(8, 2))
        ttk.Entry(parent, textvariable=variable).pack(fill="x")

    def _path_field(self, parent: ttk.Frame, label: str, variable: tk.StringVar, browse: Callable[[], None]) -> None:
        ttk.Label(parent, text=label).pack(anchor="w", pady=(8, 2))
        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=browse, width=9).pack(side="left", padx=(6, 0))

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_var.get() or str(Path.cwd()))
        if selected:
            self.output_var.set(selected)

    def _selected_country_profile(self):
        try:
            return find_country_profile(self._country_profiles, self.country_preset_var.get())
        except ValueError:
            return None

    def _on_country_selected(self, _event=None) -> None:
        country = self._selected_country_profile()
        if country is None:
            self.status_var.set("Country preset: auto")
            return
        self.preset_var.set(country.parent_region_identifier)
        self.status_var.set(f"{country.display_name} uses {country.parent_region_identifier}")
        self._log(
            f"Country preset {country.iso_alpha2} / {country.display_name}: "
            f"regional preset set to {country.parent_region_identifier}."
        )

    def _on_region_selected(self, _event=None) -> None:
        country = self._selected_country_profile()
        if country is None:
            return
        if self.preset_var.get() != country.parent_region_identifier:
            attempted = self.preset_var.get()
            self.preset_var.set(country.parent_region_identifier)
            self.status_var.set(f"Country preset requires {country.parent_region_identifier}")
            self._log(
                f"Ignored incompatible regional preset {attempted!r}; "
                f"{country.display_name} belongs to {country.parent_region_identifier}."
            )

    def refresh_presets(self) -> None:
        try:
            profiles = load_profiles()
            clear_country_profile_cache()
            values = ["auto"] + [p.identifier for p in profiles]
            self.preset_combo.configure(values=values)
            if self.preset_var.get() not in values:
                self.preset_var.set("auto")

            self._country_profiles = load_country_profiles()
            country_values = ["auto"] + [
                country_selector_label(profile)
                for profile in sorted(self._country_profiles, key=lambda item: (item.display_name.casefold(), item.iso_alpha2))
            ]
            self.country_preset_combo.configure(values=country_values)
            try:
                selected = find_country_profile(self._country_profiles, self.country_preset_var.get())
            except ValueError:
                selected = None
                self.country_preset_var.set("auto")
            if selected is not None:
                canonical = country_selector_label(selected)
                if canonical in country_values:
                    self.country_preset_var.set(canonical)
                self.preset_var.set(selected.parent_region_identifier)

            self._log(
                f"Loaded {len(profiles)} regional style profile(s) and "
                f"{len(self._country_profiles)} country profile(s)."
            )
            if profiles:
                self.status_var.set(
                    f"Loaded {len(profiles)} regional + {len(self._country_profiles)} country presets"
                )
            else:
                self.status_var.set("No local house_styles JSON found; geographic fallback will be used")
        except Exception as exc:
            self._show_error(exc)

    def build_model(self) -> None:
        if self._busy:
            return
        try:
            way_id = int(self.way_var.get().strip())
            if way_id <= 0:
                raise ValueError("OSM way ID must be a positive integer")
            output = Path(self.output_var.get().strip() or "osm3d-output").expanduser()
            timeout = float(self.timeout_var.get().strip())
            if timeout <= 0:
                raise ValueError("Timeout must be greater than zero")
            preset = self.preset_var.get().strip() or "auto"
            country_preset = self.country_preset_var.get().strip() or "auto"
            selected_country = find_country_profile(self._country_profiles, country_preset)
            if selected_country is not None:
                preset = selected_country.parent_region_identifier
                self.preset_var.set(preset)
            building_type = self.building_type_var.get().strip() or "auto"
            if building_type not in BUILDING_TYPE_OVERRIDES:
                raise ValueError(f"Unknown building type override: {building_type}")
            interior_mode = self.interior_mode_var.get().strip() or "Exterior only"
            if interior_mode not in {"Exterior only", "Simple interior"}:
                raise ValueError(f"Unknown interior mode: {interior_mode}")
            context = self.context_var.get().strip() or "auto"
            seed = self.seed_var.get().strip() or "0"
            foundation_text = self.foundation_var.get().strip().casefold()
            if foundation_text in {"", "auto", "region", "regional"}:
                foundation_depth = None
            else:
                foundation_depth = float(foundation_text)
                if not math.isfinite(foundation_depth) or foundation_depth < 0.15:
                    raise ValueError("Foundation depth must be at least 0.15 m, or use auto")
            add_windows = bool(self.windows_var.get())
            add_doors = bool(self.doors_var.get())
            add_details = bool(self.details_var.get())
        except Exception as exc:
            self._show_error(exc)
            return

        try:
            _save_last_way_id(way_id)
        except OSError as exc:
            self._log(f"Could not save last OSM way ID: {exc}")

        override_note = "OSM classification" if building_type == "auto" else f"forced {building_type}"
        country_note = "automatic country" if country_preset == "auto" else f"country {country_preset}"
        self._log(
            f"Building OSM way {way_id} into {output} with seed {seed} "
            f"({override_note}; {country_note}; region {preset}; {interior_mode.lower()}) …"
        )

        def work() -> Path:
            return build_way(
                way_id,
                output,
                preset=preset,
                country_preset=country_preset,
                context=context,
                timeout=timeout,
                progress=lambda text: self._worker_events.put(("stage", text, None)),
                add_windows=add_windows,
                add_doors=add_doors,
                add_details=add_details,
                seed=seed,
                foundation_depth=foundation_depth,
                building_type=building_type,
                interior_mode=interior_mode,
            )

        self._run_async("Building model…", work, self._build_finished)

    def regenerate_with_new_seed(self) -> None:
        """Rebuild the current way while rerolling procedural style/texture choices."""
        if self._busy:
            return
        self.seed_var.set(str(secrets.randbits(31)))
        self._log(f"New procedural seed: {self.seed_var.get()}")
        self.build_model()

    def _build_finished(self, model: Path) -> None:
        self.current_model = model
        self.model_var.set(model.name)
        self.preview.load(model)
        self.preview.set_wireframe(self.wireframe_var.get())
        self._load_metadata(model.parent / "metadata.json")
        self._load_texture_thumbnails(model.parent)
        self.status_var.set(f"Built {model.name}")
        self._log(f"Finished: {model}")

    def open_styles_folder(self) -> None:
        target = discover_style_dir() or (Path.cwd() / "house_styles")
        try:
            target.mkdir(parents=True, exist_ok=True)
            self.style_path_var.set(str(target.resolve()))
            if sys.platform.startswith("win"):
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:
            self._show_error(exc)

    def open_country_styles_folder(self) -> None:
        target = discover_country_style_dir() or (Path.cwd() / "country_styles")
        try:
            target.mkdir(parents=True, exist_ok=True)
            self.country_style_path_var.set(str(target.resolve()))
            if sys.platform.startswith("win"):
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:
            self._show_error(exc)

    def toggle_preview_door(self) -> None:
        if not self.preview.toggle_door():
            self.status_var.set("Current model has no generated openable door")
            return
        self.status_var.set("Toggled generated door")

    def load_existing(self) -> None:
        selected = filedialog.askopenfilename(title="Open OBJ model", filetypes=[("Wavefront OBJ", "*.obj"), ("All files", "*.*")])
        if not selected:
            return
        try:
            model = Path(selected).resolve()
            self.preview.load(model)
            self.current_model = model
            self.model_var.set(model.name)
            self._load_metadata(model.parent / "metadata.json")
            self._load_texture_thumbnails(model.parent)
            self.status_var.set(f"Loaded {model.name}")
            self._log(f"Loaded existing model: {model}")
        except Exception as exc:
            self._show_error(exc)

    def _load_metadata(self, path: Path) -> None:
        self.metadata_text.delete("1.0", "end")
        if not path.is_file():
            self.metadata_text.insert("1.0", "No metadata.json found beside this model.")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            text = json.dumps(data, indent=2, ensure_ascii=False)
        except Exception:
            text = path.read_text(encoding="utf-8", errors="replace")
        self.metadata_text.insert("1.0", text)

    def _load_texture_thumbnails(self, directory: Path) -> None:
        self._wall_image = self._thumbnail(directory / "wall.png")
        self._roof_image = self._thumbnail(directory / "roof.png")
        if self._wall_image:
            self.wall_texture_label.configure(image=self._wall_image, text="")
        else:
            self.wall_texture_label.configure(image="", text="not available")
        if self._roof_image:
            self.roof_texture_label.configure(image=self._roof_image, text="")
        else:
            self.roof_texture_label.configure(image="", text="not available")

    def _thumbnail(self, path: Path) -> tk.PhotoImage | None:
        if not path.is_file():
            return None
        try:
            image = tk.PhotoImage(file=str(path))
            factor = max(1, math.ceil(max(image.width(), image.height()) / 64))
            return image.subsample(factor, factor)
        except tk.TclError:
            return None

    def open_output_folder(self) -> None:
        target = self.current_model.parent if self.current_model else Path(self.output_var.get().strip() or ".")
        target = target.expanduser().resolve()
        try:
            target.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:
            self._show_error(exc)

    def open_external_viewer(self) -> None:
        if self.current_model is None:
            messagebox.showinfo("No model", "Build or load a model first.", parent=self)
            return
        try:
            # main.py can run the source checkout without installing the package.
            # Propagate the src directory to the child process so the optional
            # OpenGL viewer works in that same direct-run setup.
            env = os.environ.copy()
            src_dir = str(Path(__file__).resolve().parents[1])
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = src_dir + (os.pathsep + existing if existing else "")
            subprocess.Popen(
                [sys.executable, "-m", "osm_house_modeler", "view", str(self.current_model)],
                env=env,
            )
            self._log(f"Opened OpenGL viewer for {self.current_model.name}")
        except Exception as exc:
            self._show_error(exc)

    def _run_async(self, status: str, func: Callable[[], object], success: Callable[[object], None]) -> None:
        if self._busy:
            return
        self._busy = True
        self.build_button.configure(state="disabled")
        self.regenerate_button.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set(status)

        def worker() -> None:
            try:
                result = func()
            except Exception as exc:
                self._worker_events.put(("error", exc, None))
            else:
                self._worker_events.put(("success", success, result))

        threading.Thread(target=worker, name="osm3d-gui-worker", daemon=True).start()

    def _poll_worker_events(self) -> None:
        try:
            while True:
                kind, first, second = self._worker_events.get_nowait()
                if kind == "stage":
                    self._stage(str(first))
                elif kind == "error" and isinstance(first, Exception):
                    self._task_failed(first)
                elif kind == "success" and callable(first):
                    self._task_succeeded(first, second)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(50, self._poll_worker_events)

    def _task_succeeded(self, callback: Callable[[object], None], result: object) -> None:
        self._set_idle()
        try:
            callback(result)
        except Exception as exc:
            self._show_error(exc)

    def _task_failed(self, exc: Exception) -> None:
        self._set_idle()
        self._show_error(exc)

    def _set_idle(self) -> None:
        self._busy = False
        self.build_button.configure(state="normal")
        self.regenerate_button.configure(state="normal")
        self.progress.stop()

    def _stage(self, text: str) -> None:
        self.status_var.set(text)
        self._log(text)

    def _log(self, text: str) -> None:
        if not hasattr(self, "log_text"):
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _show_error(self, exc: Exception) -> None:
        message = str(exc) or exc.__class__.__name__
        self.status_var.set(f"Error: {message}")
        self._log(f"ERROR: {message}")
        messagebox.showerror("OSM House Modeler", message, parent=self)


def main() -> int:
    app = OSM3DApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
