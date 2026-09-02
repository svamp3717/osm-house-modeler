from __future__ import annotations

from pathlib import Path
import math
from .geometry import Mesh


def _face_normal(mesh: Mesh, vertices: tuple[int, int, int]) -> tuple[float, float, float]:
    a, b, c = (mesh.vertices[i - 1] for i in vertices)
    ab = (b[0]-a[0], b[1]-a[1], b[2]-a[2])
    ac = (c[0]-a[0], c[1]-a[1], c[2]-a[2])
    nx = ab[1]*ac[2] - ab[2]*ac[1]
    ny = ab[2]*ac[0] - ab[0]*ac[2]
    nz = ab[0]*ac[1] - ab[1]*ac[0]
    length = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
    return nx/length, ny/length, nz/length


def write_obj(mesh: Mesh, out_dir: Path, name: str = "building") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    obj = out_dir / f"{name}.obj"
    mtl = out_dir / f"{name}.mtl"
    lines = [f"mtllib {mtl.name}", f"o {name}"]
    for animation in mesh.door_animations:
        vertex_text = ",".join(str(index) for index in animation.vertex_indices)
        lines.append(
            "# osm3d_door_animation "
            f"hinge={animation.hinge[0]:.6f},{animation.hinge[1]:.6f},{animation.hinge[2]:.6f} "
            f"open_angle={animation.open_angle_degrees:.6f} vertices={vertex_text}"
        )
    lines.extend(f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in mesh.vertices)
    lines.extend(f"vt {u:.6f} {v:.6f}" for u, v in mesh.uvs)
    normals = [_face_normal(mesh, face.vertices) for face in mesh.faces]
    lines.extend(f"vn {x:.6f} {y:.6f} {z:.6f}" for x, y, z in normals)
    # Keep each material in its own OBJ object. Some OBJ viewers, including
    # pyglet 2.1's built-in decoder, attach one material to an entire object and
    # otherwise let the final ``usemtl`` win. Grouping here preserves wall and
    # roof textures in those viewers while remaining valid Wavefront OBJ.
    material_order: list[str] = []
    grouped: dict[str, list[tuple[int, object]]] = {}
    for normal_index, face in enumerate(mesh.faces, start=1):
        if face.material not in grouped:
            material_order.append(face.material)
            grouped[face.material] = []
        grouped[face.material].append((normal_index, face))

    for material in material_order:
        lines.append(f"o {name}_{material}")
        lines.append(f"usemtl {material}")
        for normal_index, face in grouped[material]:
            refs = [f"{vi}/{ti}/{normal_index}" for vi, ti in zip(face.vertices, face.uvs)]
            lines.append("f " + " ".join(refs))
    obj.write_text("\n".join(lines) + "\n", encoding="utf-8")
    mtl.write_text(
        "newmtl foundation\nKd 1 1 1\nKa 0.12 0.12 0.12\nKs 0.04 0.04 0.04\nNs 6\nmap_Kd foundation.png\n\n"
        "newmtl wall\nKd 1 1 1\nKa 0.15 0.15 0.15\nKs 0.05 0.05 0.05\nNs 8\nmap_Kd wall.png\n\n"
        "newmtl roof\nKd 1 1 1\nKa 0.12 0.12 0.12\nKs 0.08 0.08 0.08\nNs 12\nmap_Kd roof.png\n\n"
        "newmtl window\nKd 1 1 1\nKa 0.10 0.10 0.10\nKs 0.70 0.70 0.70\nNs 96\nmap_Kd window.png\n\n"
        "newmtl window_frame\nKd 1 1 1\nKa 0.13 0.13 0.13\nKs 0.22 0.22 0.22\nNs 28\nmap_Kd window_frame.png\n\n"
        "newmtl door\nKd 1 1 1\nKa 0.14 0.14 0.14\nKs 0.12 0.12 0.12\nNs 18\nmap_Kd door.png\n\n"
        "newmtl door_openable\nKd 1 1 1\nKa 0.14 0.14 0.14\nKs 0.12 0.12 0.12\nNs 18\nmap_Kd door.png\n\n"
        "newmtl interior_wall\nKd 0.84 0.82 0.77\nKa 0.18 0.18 0.18\nKs 0.02 0.02 0.02\nNs 4\n\n"
        "newmtl interior_floor\nKd 0.58 0.48 0.36\nKa 0.16 0.16 0.16\nKs 0.04 0.04 0.04\nNs 8\n\n"
        "newmtl interior_ceiling\nKd 0.90 0.89 0.86\nKa 0.18 0.18 0.18\nKs 0.01 0.01 0.01\nNs 2\n\n"
        "newmtl balcony\nKd 1 1 1\nKa 0.14 0.14 0.14\nKs 0.12 0.12 0.12\nNs 18\nmap_Kd balcony.png\n\n"
        "newmtl detail_masonry\nKd 1 1 1\nKa 0.14 0.14 0.14\nKs 0.05 0.05 0.05\nNs 8\nmap_Kd detail_masonry.png\n\n"
        "newmtl detail_wood\nKd 1 1 1\nKa 0.14 0.14 0.14\nKs 0.06 0.06 0.06\nNs 10\nmap_Kd detail_wood.png\n\n"
        "newmtl detail_metal\nKd 1 1 1\nKa 0.12 0.12 0.12\nKs 0.32 0.32 0.32\nNs 42\nmap_Kd detail_metal.png\n",
        encoding="utf-8",
    )
    return obj
