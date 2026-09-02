from __future__ import annotations

import math

from osm_house_modeler.exporter import write_obj
from osm_house_modeler.geometry import Mesh, _add_windows_and_door, build_mesh
from osm_house_modeler.gui import load_obj_preview


POLY = ((0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0))
WINDOW_SPEC = {
    "density_multiplier": 1.0,
    "width_m": 1.2,
    "height_m": 1.2,
    "sill_height_m": 0.9,
    "edge_margin_m": 0.65,
    "target_bay_spacing_m": 3.2,
    "placement_style": "regular_aligned",
    "minimum_windows_per_primary_facade": 1,
    "maximum_windows_per_wall": 4,
}
DOOR_SPEC = {
    "primary_width_m": 1.0,
    "primary_height_m": 2.1,
    "corner_clearance_m": 0.75,
    "keep_clear_of_windows_m": 0.4,
}


def _point_in_triangle(point, triangle) -> bool:
    px, py = point
    (ax, ay), (bx, by), (cx, cy) = triangle
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(den) < 1e-10:
        return False
    u = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / den
    v = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / den
    w = 1.0 - u - v
    eps = 1e-7
    return u >= -eps and v >= -eps and w >= -eps


def _wall_face_covers_opening_centre(mesh, opening) -> bool:
    a = POLY[opening.edge]
    b = POLY[(opening.edge + 1) % len(POLY)]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    tx, ty = dx / length, dy / length
    target = (opening.center_t * length, (opening.z0 + opening.z1) * 0.5)
    for face in mesh.faces:
        if face.material != "wall":
            continue
        local = []
        on_edge = True
        for index in face.vertices:
            x, y, z = mesh.vertices[index - 1]
            # Signed lateral distance from the source wall line.
            lateral = (x - a[0]) * (-ty) + (y - a[1]) * tx
            if abs(lateral) > 1e-6:
                on_edge = False
                break
            along = (x - a[0]) * tx + (y - a[1]) * ty
            local.append((along, z))
        if on_edge and len(local) == 3 and _point_in_triangle(target, tuple(local)):
            return True
    return False


def _build(mode: str):
    return build_mesh(
        POLY,
        3.0,
        1.8,
        "gabled",
        levels=1,
        add_windows=True,
        add_doors=True,
        family="residential",
        building_class="house",
        foundation_depth=0.7,
        seed="interior-test",
        window_spec=WINDOW_SPEC,
        door_spec=DOOR_SPEC,
        add_details=False,
        interior_mode=mode,
        wall_thickness=0.28,
    )


def test_simple_interior_adds_real_shell_and_hinged_door() -> None:
    exterior = _build("exterior_only")
    interior = _build("simple_interior")

    exterior_materials = {face.material for face in exterior.faces}
    interior_materials = {face.material for face in interior.faces}
    assert "interior_wall" not in exterior_materials
    assert "door" in exterior_materials

    assert {"interior_wall", "interior_floor", "interior_ceiling", "door_openable"} <= interior_materials
    assert "door" not in interior_materials
    assert interior.detail_counts["window_holes"] > 0
    assert interior.detail_counts["door_holes"] == 1
    assert interior.detail_counts["openable_doors"] == 1
    assert interior.detail_counts["interior_partitions"] == 0
    assert len(interior.door_animations) == 1
    assert interior.door_animations[0].open_angle_degrees > 0.0


def test_simple_interior_wall_faces_do_not_cover_door_or_window_centres() -> None:
    layout = _add_windows_and_door(
        Mesh(), list(POLY), 3.0, 1, True, True,
        family="residential", building_class="house", seed="interior-test",
        window_spec=WINDOW_SPEC, door_spec=DOOR_SPEC, emit_panels=False,
    )
    mesh = _build("simple_interior")
    door = next(opening for opening in layout.openings if opening.kind == "door")
    window = next(opening for opening in layout.openings if opening.kind == "window")
    assert not _wall_face_covers_opening_centre(mesh, door)
    assert not _wall_face_covers_opening_centre(mesh, window)


def test_obj_preserves_openable_door_animation_metadata(tmp_path) -> None:
    mesh = _build("simple_interior")
    obj = write_obj(mesh, tmp_path, "interior_house")
    text = obj.read_text(encoding="utf-8")
    assert "# osm3d_door_animation " in text
    assert "newmtl door_openable" in (tmp_path / "interior_house.mtl").read_text(encoding="utf-8")

    preview = load_obj_preview(obj)
    assert len(preview.door_animations) == 1
    assert preview.door_animations[0].open_angle_degrees > 0.0


def test_simple_interior_window_frames_are_on_exterior_side() -> None:
    mesh = _build("simple_interior")
    window_faces = [face for face in mesh.faces if face.material == "window_frame"]
    assert window_faces
    # The footprint is [0,10] x [0,8]. Every visible frame face should have
    # been biased slightly outside one of those wall planes rather than recessed
    # into the room.
    for face in window_faces:
        points = [mesh.vertices[index - 1] for index in face.vertices]
        assert any(
            x < -0.005 or x > 10.005 or y < -0.005 or y > 8.005
            for x, y, _z in points
        )


def test_simple_interior_exterior_wall_cells_do_not_overlap() -> None:
    layout = _add_windows_and_door(
        Mesh(), list(POLY), 3.0, 1, True, True,
        family="residential", building_class="house", seed="interior-test",
        window_spec=WINDOW_SPEC, door_spec=DOOR_SPEC, emit_panels=False,
    )
    mesh = _build("simple_interior")
    # First edge is y=0, length 10. Sum the exterior wall triangle area in the
    # local X/Z plane. Coplanar cell expansion would make this exceed the exact
    # wall-minus-openings area and causes OpenGL z-fighting seams.
    area = 0.0
    for face in mesh.faces:
        if face.material != "wall":
            continue
        pts = [mesh.vertices[index - 1] for index in face.vertices]
        if not all(abs(y) < 1e-8 for _x, y, _z in pts):
            continue
        (x0, _y0, z0), (x1, _y1, z1), (x2, _y2, z2) = pts
        area += abs((x1-x0)*(z2-z0) - (z1-z0)*(x2-x0)) * 0.5
    holes = sum(
        opening.width * (opening.z1 - opening.z0)
        for opening in layout.openings if opening.edge == 0
    )
    expected = 10.0 * 3.0 - holes
    assert abs(area - expected) < 1e-6
