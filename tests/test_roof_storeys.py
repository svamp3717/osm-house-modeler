import json
from pathlib import Path

from osm_house_modeler.geometry import build_mesh
from osm_house_modeler.styles import choose_style, classify_building, discover_style_dir, load_profiles


def test_cottage_is_residential_and_can_default_to_two_levels() -> None:
    classification = classify_building({"building": "cottage"}, 9.0, 7.0)
    assert (classification.family, classification.building_class) == ("residential", "cottage")
    choice = choose_style(
        load_profiles(), 18.06, 59.33, {"building": "cottage"}, 99,
        preset="sweden", width_m=9.0, length_m=7.0, seed="cottage",
    )
    assert choice.default_levels == 2
    assert choice.automatic_max_levels == 2


def test_all_regions_define_roof_storey_probabilities() -> None:
    directory = discover_style_dir()
    assert directory is not None
    for path in sorted(directory.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for context_name, context in document["contexts"].items():
            details = context["architectural_details"]
            roof_storeys = details["roof_storeys"]
            assert roof_storeys["eligible_roof_shapes"] == ["gabled"], (path.name, context_name)
            probs = roof_storeys["probability_by_building_class"]
            assert "cottage" in probs and "apartments" in probs and "cabin" in probs
            assert 0.0 <= probs["cottage"] <= 1.0
            assert 0.0 <= probs["apartments"] <= 1.0
            policy = roof_storeys["window_policy"]
            assert policy["gable_ends_only"] is True
            assert policy["minimum_roof_height_m"] >= 2.0


def test_roof_storeys_are_more_common_for_swedish_cottages_than_caribbean_apartments() -> None:
    profiles = load_profiles()
    sweden = choose_style(
        profiles, 18.06, 59.33, {"building": "cottage"}, 1,
        preset="sweden", width_m=9.0, length_m=7.0, seed="frequency",
    )
    caribbean = choose_style(
        profiles, -66.1, 18.4, {"building": "apartments"}, 1,
        preset="caribbean", requested_context="town_city", width_m=20.0, length_m=12.0, seed="frequency",
    )
    assert sweden.roof_storey_probability > caribbean.roof_storey_probability


def test_explicit_roof_levels_selects_compatible_gabled_roof() -> None:
    choice = choose_style(
        load_profiles(), -66.1, 18.4,
        {"building": "cottage", "roof:levels": "1"}, 7,
        preset="caribbean", width_m=9.0, length_m=7.0, seed="explicit",
    )
    assert choice.roof_storey is True
    assert choice.roof_style == "gabled"


def test_attic_windows_only_appear_on_gable_end_planes() -> None:
    mesh = build_mesh(
        ((0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0)),
        wall_h=3.0,
        roof_h=3.0,
        roof_style="gabled",
        levels=1,
        family="residential",
        building_class="cottage",
        add_windows=True,
        add_doors=False,
        seed="attic",
        window_spec={
            "density_multiplier": 0.8,
            "width_m": 1.1,
            "height_m": 1.2,
            "sill_height_m": 0.9,
            "edge_margin_m": 0.6,
            "target_bay_spacing_m": 3.0,
            "placement_style": "regular_aligned",
        },
        roof_storey=True,
        roof_storey_spec={
            "gable_ends_only": True,
            "minimum_roof_height_m": 2.35,
            "sill_above_eave_m": 0.42,
            "top_clearance_m": 0.34,
            "side_clearance_m": 0.30,
            "window_width_scale": 0.82,
            "window_height_scale": 0.78,
            "windows_per_gable": 1,
        },
    )
    attic_faces = []
    for face in mesh.faces:
        if face.material != "window":
            continue
        points = [mesh.vertices[index - 1] for index in face.vertices]
        if min(point[2] for point in points) > 3.0:
            attic_faces.append(points)
    assert attic_faces
    # For a 10 x 6 rectangle the ridge runs along X, so gable-end windows sit
    # on planes of constant X (near x=-0.19 and x=10.19 after facade offset).
    assert all(max(p[0] for p in points) - min(p[0] for p in points) < 1e-6 for points in attic_faces)
    # They must remain below the 6 m ridge apex.
    assert max(p[2] for points in attic_faces for p in points) < 6.0


def test_simple_interior_attic_gable_keeps_wall_around_window_hole() -> None:
    mesh = build_mesh(
        ((0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0)),
        wall_h=3.0,
        roof_h=3.0,
        roof_style="gabled",
        levels=1,
        family="residential",
        building_class="cottage",
        add_windows=True,
        add_doors=False,
        seed="attic",
        window_spec={
            "density_multiplier": 0.8,
            "width_m": 1.1,
            "height_m": 1.2,
            "sill_height_m": 0.9,
            "edge_margin_m": 0.6,
            "target_bay_spacing_m": 3.0,
            "placement_style": "regular_aligned",
        },
        roof_storey=True,
        roof_storey_spec={
            "gable_ends_only": True,
            "minimum_roof_height_m": 2.35,
            "sill_above_eave_m": 0.42,
            "top_clearance_m": 0.34,
            "side_clearance_m": 0.30,
            "window_width_scale": 0.82,
            "window_height_scale": 0.78,
            "windows_per_gable": 1,
        },
        interior_mode="simple_interior",
        wall_thickness=0.28,
    )

    def projected_yz_area(points):
        (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = points
        return abs((y1 - y0) * (z2 - z0) - (z1 - z0) * (y2 - y0)) * 0.5

    # The x=0 gable is a 6m x 3m triangle (9m²), minus one 0.902m x
    # 0.936m attic aperture. If the clipping winding regresses, almost all of
    # this wall disappears and the interior roof lining becomes visible outside.
    gable_faces = []
    for face in mesh.faces:
        if face.material != "wall":
            continue
        points = [mesh.vertices[index - 1] for index in face.vertices]
        if min(p[2] for p in points) >= 3.0 - 1e-6 and max(abs(p[0]) for p in points) < 1e-6:
            gable_faces.append(points)
    assert gable_faces
    covered = sum(projected_yz_area(points) for points in gable_faces)
    expected = 9.0 - (1.1 * 0.82) * (1.2 * 0.78)
    assert abs(covered - expected) < 0.02


def test_simple_interior_does_not_modify_exterior_roof_faces() -> None:
    kwargs = dict(
        poly_input=((0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0)),
        wall_h=3.0,
        roof_h=3.0,
        roof_style="gabled",
        levels=1,
        family="residential",
        building_class="cottage",
        add_windows=True,
        add_doors=False,
        seed="attic-roof-regression",
        window_spec={
            "density_multiplier": 0.8,
            "width_m": 1.1,
            "height_m": 1.2,
            "sill_height_m": 0.9,
            "edge_margin_m": 0.6,
            "target_bay_spacing_m": 3.0,
            "placement_style": "regular_aligned",
        },
        roof_storey=True,
        roof_storey_spec={
            "gable_ends_only": True,
            "minimum_roof_height_m": 2.35,
            "sill_above_eave_m": 0.42,
            "top_clearance_m": 0.34,
            "side_clearance_m": 0.30,
            "window_width_scale": 0.82,
            "window_height_scale": 0.78,
            "windows_per_gable": 1,
        },
        wall_thickness=0.28,
    )
    exterior = build_mesh(interior_mode="exterior_only", **kwargs)
    interior = build_mesh(interior_mode="simple_interior", **kwargs)

    def roof_triangles(mesh):
        return sorted(
            tuple(sorted(tuple(round(value, 6) for value in mesh.vertices[index - 1]) for index in face.vertices))
            for face in mesh.faces if face.material == "roof"
        )

    assert roof_triangles(interior) == roof_triangles(exterior)


def test_simple_interior_attic_window_has_frame_but_no_filled_panel() -> None:
    mesh = build_mesh(
        ((0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0)),
        wall_h=3.0, roof_h=3.0, roof_style="gabled", levels=1,
        family="residential", building_class="cottage",
        add_windows=True, add_doors=False, seed="attic-no-panel",
        window_spec={
            "density_multiplier": 0.8, "width_m": 1.1, "height_m": 1.2,
            "sill_height_m": 0.9, "edge_margin_m": 0.6,
            "target_bay_spacing_m": 3.0, "placement_style": "regular_aligned",
        },
        roof_storey=True,
        roof_storey_spec={
            "gable_ends_only": True, "minimum_roof_height_m": 2.35,
            "sill_above_eave_m": 0.42, "top_clearance_m": 0.34,
            "side_clearance_m": 0.30, "window_width_scale": 0.82,
            "window_height_scale": 0.78, "windows_per_gable": 1,
        },
        interior_mode="simple_interior", wall_thickness=0.28,
    )
    attic_faces = [
        face for face in mesh.faces
        if face.material == "window_frame"
        and min(mesh.vertices[index - 1][2] for index in face.vertices) >= 3.0 - 1e-6
    ]
    assert attic_faces
    # A frame strip may span the window width OR height, but never both. A filled
    # decorative panel would contain triangles spanning substantial width and height.
    for face in attic_faces:
        points = [mesh.vertices[index - 1] for index in face.vertices]
        horizontal_span = max(max(p[0] for p in points) - min(p[0] for p in points),
                              max(p[1] for p in points) - min(p[1] for p in points))
        vertical_span = max(p[2] for p in points) - min(p[2] for p in points)
        assert horizontal_span < 0.45 or vertical_span < 0.45


def test_simple_interior_attic_frame_sits_outside_gable_plane() -> None:
    mesh = build_mesh(
        ((0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0)),
        wall_h=3.0, roof_h=3.0, roof_style="gabled", levels=1,
        family="residential", building_class="cottage",
        add_windows=True, add_doors=False, seed="attic-exterior-frame",
        window_spec={
            "density_multiplier": 0.8, "width_m": 1.1, "height_m": 1.2,
            "sill_height_m": 0.9, "edge_margin_m": 0.6,
            "target_bay_spacing_m": 3.0, "placement_style": "regular_aligned",
        },
        roof_storey=True,
        roof_storey_spec={
            "gable_ends_only": True, "minimum_roof_height_m": 2.35,
            "sill_above_eave_m": 0.42, "top_clearance_m": 0.34,
            "side_clearance_m": 0.30, "window_width_scale": 0.82,
            "window_height_scale": 0.78, "windows_per_gable": 1,
        },
        interior_mode="simple_interior", wall_thickness=0.28,
    )
    attic_faces = [
        face for face in mesh.faces
        if face.material == "window_frame"
        and min(mesh.vertices[index - 1][2] for index in face.vertices) >= 3.0 - 1e-6
    ]
    assert attic_faces
    # Gable ends are x=0 and x=10. Visible frames should sit slightly outside,
    # never recessed between those planes.
    for face in attic_faces:
        xs = [mesh.vertices[index - 1][0] for index in face.vertices]
        assert max(xs) > 10.005 or min(xs) < -0.005
