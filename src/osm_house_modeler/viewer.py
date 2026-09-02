from __future__ import annotations

from pathlib import Path
import math
import shlex


def _bbox_obj(path: Path) -> tuple[tuple[float,float,float], tuple[float,float,float]]:
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("v "):
                _, xs, ys, zs, *_ = line.split()
                p = (float(xs), float(ys), float(zs))
                for i in range(3):
                    mins[i] = min(mins[i], p[i]); maxs[i] = max(maxs[i], p[i])
    if not math.isfinite(mins[0]):
        raise ValueError(f"No vertices found in {path}")
    return tuple(mins), tuple(maxs)


def _obj_texture_dependencies(path: Path) -> list[tuple[str, Path]]:
    """Return texture names from OBJ material libraries and resolved file paths.

    The generated MTL files use simple ``map_Kd wall.png`` lines, but using
    ``shlex`` here also copes with quoted filenames.  The final token is the
    texture filename after any common MTL options.
    """
    path = path.expanduser().resolve()
    mtllibs: list[Path] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                parts = shlex.split(line, posix=False)
            except ValueError:
                parts = line.split()
            if parts and parts[0].casefold() == "mtllib" and len(parts) >= 2:
                # Wavefront permits more than one library on a line.
                mtllibs.extend(path.parent / token.strip('"') for token in parts[1:])

    textures: list[tuple[str, Path]] = []
    for mtl in mtllibs:
        if not mtl.is_file():
            continue
        with mtl.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    parts = shlex.split(line, posix=False)
                except ValueError:
                    parts = line.split()
                if parts and parts[0].casefold() == "map_kd" and len(parts) >= 2:
                    name = parts[-1].strip('"')
                    textures.append((name, (mtl.parent / name).resolve()))
    return textures


def _resource_roots(path: Path) -> list[str]:
    """Absolute roots for pyglet's global resource loader.

    Pyglet resolves relative resource search paths against the application's
    *script home*, not the process working directory.  Supplying an absolute
    path is therefore required when opening generated OBJ files elsewhere.
    """
    return [str(path.expanduser().resolve().parent)]


def view_model(path: Path) -> None:
    import pyglet
    from pyglet.gl import (
        GL_CULL_FACE, GL_DEPTH_TEST, GL_FILL, GL_FRONT_AND_BACK, GL_LINE, GL_REPEAT,
        GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, glBindTexture, glDisable, glEnable,
        glPolygonMode, glTexParameteri,
    )
    from pyglet.math import Mat4, Vec3
    from pyglet.window import key, mouse

    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    # pyglet's OBJ decoder loads map_Kd through its global resource loader.
    # A relative resource path such as "." is resolved against pyglet's script
    # home, *not* the current working directory.  Register the model directory
    # as an absolute resource root so wall.png / roof.png are found on Windows
    # and on Unix regardless of where main.py was launched.
    missing = [(name, resolved) for name, resolved in _obj_texture_dependencies(path) if not resolved.is_file()]
    if missing:
        details = ", ".join(f"{name} -> {resolved}" for name, resolved in missing)
        raise FileNotFoundError(f"OBJ texture file(s) missing: {details}")

    pyglet.resource.path = _resource_roots(path)
    pyglet.resource.reindex()
    model_filename = str(path)

    class ModelWindow(pyglet.window.Window):
        def __init__(self) -> None:
            super().__init__(1000, 760, caption=f"OSM3D Viewer - {path.name}", resizable=True)
            self.batch = pyglet.graphics.Batch()
            self.scene = pyglet.model.load(model_filename)
            self.models = self.scene.create_models(batch=self.batch)
            # Generated UVs intentionally repeat beyond 0..1. Pyglet textures
            # commonly default to edge clamping, so explicitly enable wrapping.
            for model in self.models:
                for group in getattr(model, "groups", ()):
                    texture = getattr(group, "texture", None)
                    if texture is None:
                        continue
                    glBindTexture(texture.target, texture.id)
                    glTexParameteri(texture.target, GL_TEXTURE_WRAP_S, GL_REPEAT)
                    glTexParameteri(texture.target, GL_TEXTURE_WRAP_T, GL_REPEAT)
            lo, hi = _bbox_obj(path)
            self.home_target = Vec3(*(0.5*(lo[i]+hi[i]) for i in range(3)))
            diagonal = math.sqrt(sum((hi[i]-lo[i])**2 for i in range(3)))
            self.home_distance = max(8.0, diagonal * 1.8)
            self.target = self.home_target
            self.distance = self.home_distance
            self.yaw = math.radians(45)
            self.pitch = math.radians(28)
            self.wireframe = False
            glEnable(GL_DEPTH_TEST)
            glDisable(GL_CULL_FACE)
            self.set_minimum_size(480, 320)
            self._projection()

        def _projection(self) -> None:
            aspect = max(0.01, self.width / max(1, self.height))
            self.projection = Mat4.perspective_projection(aspect, z_near=0.05, z_far=max(5000.0, self.home_distance*100))

        def _eye(self) -> Vec3:
            cp = math.cos(self.pitch)
            return Vec3(
                self.target.x + self.distance * cp * math.cos(self.yaw),
                self.target.y + self.distance * cp * math.sin(self.yaw),
                self.target.z + self.distance * math.sin(self.pitch),
            )

        def on_draw(self) -> None:
            self.clear()
            self.view = Mat4.look_at(self._eye(), self.target, Vec3(0,0,1))
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE if self.wireframe else GL_FILL)
            self.batch.draw()
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)

        def on_resize(self, width: int, height: int):
            result = super().on_resize(width, height)
            self._projection()
            return result

        def on_mouse_scroll(self, x: int, y: int, scroll_x: int, scroll_y: int) -> None:
            self.distance = max(0.5, self.distance * (0.86 ** scroll_y))

        def on_mouse_drag(self, x: int, y: int, dx: int, dy: int, buttons: int, modifiers: int) -> None:
            if buttons & mouse.LEFT:
                self.yaw -= dx * 0.008
                self.pitch = max(math.radians(-85), min(math.radians(85), self.pitch + dy * 0.008))
            elif buttons & (mouse.RIGHT | mouse.MIDDLE):
                eye = self._eye()
                forward = (self.target - eye).normalize()
                right = forward.cross(Vec3(0,0,1)).normalize()
                up = right.cross(forward).normalize()
                scale = self.distance * 0.0018
                self.target += right * (-dx * scale) + up * (-dy * scale)

        def on_key_press(self, symbol: int, modifiers: int) -> None:
            if symbol == key.W:
                self.wireframe = not self.wireframe
            elif symbol in {key.R, key.HOME}:
                self.target = self.home_target
                self.distance = self.home_distance
                self.yaw = math.radians(45); self.pitch = math.radians(28)
            elif symbol == key.ESCAPE:
                self.close()

    ModelWindow()
    pyglet.app.run()
