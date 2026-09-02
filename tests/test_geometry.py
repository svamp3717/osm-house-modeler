from osm_house_modeler.geometry import build_mesh, triangulate


def test_square_triangulates():
    poly = [(0,0), (10,0), (10,6), (0,6)]
    assert len(triangulate(poly)) == 2


def test_build_gabled_mesh():
    mesh = build_mesh(((0,0), (10,0), (10,6), (0,6)), 6.0, 2.0, "gabled")
    assert mesh.faces
    assert any(face.material == "roof" for face in mesh.faces)
    assert any(face.material == "wall" for face in mesh.faces)


def _triangle_xy_area(mesh, face):
    a, b, c = (mesh.vertices[i - 1] for i in face.vertices)
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) * 0.5


def test_concave_u_roof_does_not_bridge_notch():
    # 10x8 rectangle with a 4x5 notch removed from the top middle: area 60 m².
    poly = ((0, 0), (10, 0), (10, 8), (7, 8), (7, 3), (3, 3), (3, 8), (0, 8))
    mesh = build_mesh(poly, 6.0, 2.5, "gabled", levels=2, add_windows=False, add_doors=False)
    roof_area_xy = sum(_triangle_xy_area(mesh, face) for face in mesh.faces if face.material == "roof")
    assert abs(roof_area_xy - 60.0) < 1e-6


def test_windows_and_door_are_generated_as_separate_materials():
    mesh = build_mesh(((0, 0), (12, 0), (12, 8), (0, 8)), 6.0, 2.0, "gabled", levels=2)
    assert sum(face.material == "window" for face in mesh.faces) >= 8
    assert sum(face.material == "door" for face in mesh.faces) == 2


def test_concave_hipped_roof_preserves_footprint_area():
    poly = ((0, 0), (10, 0), (10, 8), (7, 8), (7, 3), (3, 3), (3, 8), (0, 8))
    mesh = build_mesh(poly, 6.0, 2.5, "hipped", levels=2, add_windows=False, add_doors=False)
    roof_area_xy = sum(_triangle_xy_area(mesh, face) for face in mesh.faces if face.material == "roof")
    assert abs(roof_area_xy - 60.0) < 1e-6


def test_rectangular_gable_end_is_closed_to_ridge() -> None:
    mesh = build_mesh(
        ((0, 0), (12, 0), (12, 8), (0, 8)),
        6.0,
        3.0,
        "gabled",
        add_windows=False,
        add_doors=False,
    )
    # The short end x=12 crosses the ridge at y=4.  A real gable closure must
    # contain that raised wall vertex; endpoint-only closures leave the black
    # triangular hole visible in the GUI screenshot.
    wall_vertices = [
        mesh.vertices[index - 1]
        for face in mesh.faces if face.material == "wall"
        for index in face.vertices
    ]
    assert any(abs(x - 12.0) < 1e-6 and abs(y - 4.0) < 1e-6 and z > 6.1 for x, y, z in wall_vertices)


def test_facade_panels_are_offset_and_corner_safe() -> None:
    mesh = build_mesh(
        ((0, 0), (12, 0), (12, 8), (0, 8)),
        6.0,
        2.0,
        "gabled",
        levels=2,
        family="residential",
        window_spec={
            "density_multiplier": 1.0,
            "width_m": 1.2,
            "height_m": 1.2,
            "sill_height_m": 0.9,
            "edge_margin_m": 0.7,
            "target_bay_spacing_m": 3.0,
        },
        door_spec={
            "primary_width_m": 1.0,
            "primary_height_m": 2.1,
            "corner_clearance_m": 0.7,
            "keep_clear_of_windows_m": 0.35,
        },
    )
    feature_vertices = [
        mesh.vertices[index - 1]
        for face in mesh.faces if face.material in {"window", "door"}
        for index in face.vertices
    ]
    assert feature_vertices
    # Overlay geometry should not be coplanar with all four wall planes.
    assert any(x < -0.12 or x > 12.12 or y < -0.12 or y > 8.12 for x, y, _z in feature_vertices)
