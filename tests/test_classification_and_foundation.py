from __future__ import annotations

from pathlib import Path

from osm_house_modeler.exporter import write_obj
from osm_house_modeler.geometry import build_mesh
from osm_house_modeler.styles import classify_building


def test_cwr_utility_building_classification_rules() -> None:
    garage = classify_building({"building": "garage"}, 2.0, 3.5)
    shed = classify_building({"building": "shed"}, 6.0, 8.0)
    inferred = classify_building({"building": "yes"}, 6.0, 8.0)
    house = classify_building({"building": "house"}, 6.0, 8.0)
    barn = classify_building({"building": "yes"}, 12.0, 42.0, settlement="rural")
    warehouse = classify_building({"building": "warehouse"}, 24.0, 60.0)

    assert (garage.family, garage.building_class, garage.outbuilding_kind) == (
        "outbuilding", "garage", "garage"
    )
    assert (shed.family, shed.building_class, shed.outbuilding_kind) == (
        "outbuilding", "shed", "shed"
    )
    assert (inferred.family, inferred.outbuilding_kind) == ("outbuilding", "garage")
    assert house.family == "residential"
    assert (barn.family, barn.building_class) == ("agricultural", "barn")
    assert (warehouse.family, warehouse.building_class) == ("industrial", "warehouse")


def test_all_generated_buildings_have_below_grade_foundation() -> None:
    mesh = build_mesh(
        ((0, 0), (10, 0), (10, 6), (0, 6)),
        5.0,
        2.0,
        "gabled",
        add_windows=False,
        add_doors=False,
        foundation_depth=1.25,
    )
    foundation_faces = [face for face in mesh.faces if face.material == "foundation"]
    assert foundation_faces
    foundation_vertices = [
        mesh.vertices[index - 1]
        for face in foundation_faces
        for index in face.vertices
    ]
    assert min(vertex[2] for vertex in foundation_vertices) == -1.25
    assert max(vertex[2] for vertex in foundation_vertices) == 0.0


def test_utility_buildings_get_large_door_but_not_domestic_window_rows() -> None:
    mesh = build_mesh(
        ((0, 0), (12, 0), (12, 8), (0, 8)),
        4.0,
        2.0,
        "gabled",
        family="outbuilding",
        building_class="garage",
        outbuilding_kind="garage",
        add_windows=True,
        add_doors=True,
    )
    assert not any(face.material == "window" for face in mesh.faces)
    assert sum(face.material == "door" for face in mesh.faces) == 2


def test_foundation_material_is_exported(tmp_path: Path) -> None:
    mesh = build_mesh(((0, 0), (5, 0), (5, 4), (0, 4)), 3.0, 1.0, "gabled")
    obj = write_obj(mesh, tmp_path, "foundation_test")
    text = obj.read_text(encoding="utf-8")
    mtl = (tmp_path / "foundation_test.mtl").read_text(encoding="utf-8")
    assert "o foundation_test_foundation" in text
    assert "newmtl foundation" in mtl


def _door_centroid(mesh):
    points = [
        mesh.vertices[index - 1]
        for face in mesh.faces if face.material == "door"
        for index in face.vertices
    ]
    return (
        round(sum(point[0] for point in points) / len(points), 4),
        round(sum(point[1] for point in points) / len(points), 4),
    )


def test_seed_can_reroll_entrance_facade_deterministically() -> None:
    kwargs = dict(
        poly_input=((0, 0), (12, 0), (12, 8), (0, 8)),
        wall_h=6.0,
        roof_h=2.0,
        roof_style="gabled",
        family="residential",
        add_windows=False,
        add_doors=True,
    )
    first = _door_centroid(build_mesh(**kwargs, seed="same"))
    repeated = _door_centroid(build_mesh(**kwargs, seed="same"))
    rerolls = {_door_centroid(build_mesh(**kwargs, seed=str(seed))) for seed in range(12)}
    assert first == repeated
    assert len(rerolls) >= 2


def test_cabin_is_residential_but_defaults_to_one_storey() -> None:
    from osm_house_modeler.builder import _height, _levels
    from osm_house_modeler.styles import choose_style, load_profiles

    classification = classify_building({"building": "cabin"}, 8.0, 6.0)
    assert (classification.family, classification.building_class) == ("residential", "cabin")

    choice = choose_style(
        load_profiles(), 18.06, 59.33, {"building": "cabin"}, 100,
        preset="sweden", width_m=8.0, length_m=6.0, seed="cabin",
    )
    assert choice.default_levels == 1
    assert choice.automatic_max_levels == 1
    wall_h = _height({}, choice.family, choice.building_class, choice.storey_height_m, choice.default_levels)
    assert _levels(
        {}, wall_h, choice.storey_height_m, choice.family, choice.building_class,
        choice.default_levels, choice.automatic_max_levels,
    ) == 1
    # Explicit OSM levels remain authoritative.
    assert _levels(
        {"building:levels": "2"}, wall_h * 2, choice.storey_height_m,
        choice.family, choice.building_class, choice.default_levels, choice.automatic_max_levels,
    ) == 2


def _window_signature(mesh) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        sorted({
            tuple(round(value, 3) for value in mesh.vertices[index - 1])
            for face in mesh.faces if face.material == "window"
            for index in face.vertices
        })
    )


def test_procedural_window_placement_is_seeded_and_rerollable() -> None:
    window_spec = {
        "density_multiplier": 1.0,
        "width_m": 1.1,
        "height_m": 1.2,
        "sill_height_m": 0.9,
        "edge_margin_m": 0.6,
        "target_bay_spacing_m": 3.0,
        "placement_style": "irregular_cottage",
        "horizontal_jitter_fraction": 0.18,
        "vertical_jitter_m": 0.10,
        "omit_bay_probability": 0.15,
        "floor_phase_shift_fraction": 0.20,
        "front_density_multiplier": 1.2,
        "side_density_multiplier": 0.9,
        "rear_density_multiplier": 0.7,
        "minimum_windows_per_primary_facade": 1,
        "maximum_windows_per_wall": 8,
        "paired_group_gap_fraction": 0.34,
    }
    kwargs = dict(
        poly_input=((0, 0), (12, 0), (12, 8), (0, 8)),
        wall_h=6.0,
        roof_h=2.0,
        roof_style="gabled",
        levels=2,
        add_doors=False,
        window_spec=window_spec,
    )
    first = _window_signature(build_mesh(**kwargs, seed="same"))
    repeated = _window_signature(build_mesh(**kwargs, seed="same"))
    variants = {_window_signature(build_mesh(**kwargs, seed=str(seed))) for seed in range(8)}
    assert first == repeated
    assert len(variants) >= 3


def test_building_type_override_forces_semantic_classification() -> None:
    from osm_house_modeler.builder import apply_building_type_override

    original = {
        "building": "apartments",
        "building:levels": "4",
        "amenity": "school",
        "shop": "supermarket",
        "height": "13",
    }
    garage_tags = apply_building_type_override(original, "garage")
    garage = classify_building(garage_tags, 8.0, 6.0)
    assert (garage.family, garage.building_class, garage.outbuilding_kind) == (
        "outbuilding", "garage", "garage"
    )
    # Dimensional tags are deliberately retained while conflicting semantic tags
    # are cleared, so the override changes the procedural class without editing OSM.
    assert garage_tags["building:levels"] == "4"
    assert garage_tags["height"] == "13"
    assert "amenity" not in garage_tags
    assert "shop" not in garage_tags

    warehouse = classify_building(
        apply_building_type_override({"building": "house"}, "warehouse"),
        20.0,
        40.0,
    )
    assert (warehouse.family, warehouse.building_class) == ("industrial", "warehouse")


def test_auto_building_type_override_preserves_tags() -> None:
    from osm_house_modeler.builder import apply_building_type_override

    tags = {"building": "barn", "roof:shape": "gabled"}
    assert apply_building_type_override(tags, "auto") == tags
    assert apply_building_type_override(tags, "auto") is not tags


def test_shed_garage_and_barn_are_hard_windowless() -> None:
    common = dict(
        poly_input=((0.0, 0.0), (10.0, 0.0), (10.0, 7.0), (0.0, 7.0)),
        wall_h=3.5, roof_h=1.8, roof_style="gabled", levels=1,
        add_windows=True, add_doors=True, seed="utility-window-policy",
        window_spec={
            "density_multiplier": 1.5, "width_m": 1.1, "height_m": 1.0,
            "sill_height_m": 0.9, "edge_margin_m": 0.5,
            "target_bay_spacing_m": 2.0, "minimum_windows_per_primary_facade": 2,
            "maximum_windows_per_wall": 8,
        },
        door_spec={"primary_width_m": 1.0, "primary_height_m": 2.1},
        add_details=False,
    )
    cases = [
        ("outbuilding", "shed", "shed"),
        ("outbuilding", "garage", "garage"),
        ("agricultural", "barn", ""),
    ]
    for family, building_class, outbuilding_kind in cases:
        mesh = build_mesh(
            **common, family=family, building_class=building_class,
            outbuilding_kind=outbuilding_kind,
        )
        assert not any(face.material in {"window", "window_frame"} for face in mesh.faces), building_class


def test_shed_and_garage_never_get_chimneys() -> None:
    detail_spec = {
        "chimneys": {
            "enabled": True, "count": 1, "width_m": 0.5, "depth_m": 0.4,
            "height_m": 1.1, "material": "brick", "type": "brick_rectangular",
        }
    }
    for family, building_class, outbuilding_kind in [
        ("outbuilding", "shed", "shed"),
        ("outbuilding", "garage", "garage"),
    ]:
        mesh = build_mesh(
            ((0.0, 0.0), (8.0, 0.0), (8.0, 6.0), (0.0, 6.0)),
            3.2, 1.7, "gabled", levels=1, family=family,
            building_class=building_class, outbuilding_kind=outbuilding_kind,
            add_windows=False, add_doors=True, exterior_detail_spec=detail_spec,
            add_details=True, seed="no-chimney",
        )
        assert mesh.detail_counts.get("chimneys", 0) == 0


def test_warehouse_windows_are_seeded_and_uncommon() -> None:
    from osm_house_modeler.styles import choose_style, load_profiles
    profiles = load_profiles()
    present = 0
    total = 80
    for seed in range(total):
        choice = choose_style(
            profiles, 18.06, 59.33, {"building": "warehouse"}, seed,
            preset="sweden", width_m=20.0, length_m=45.0, seed=str(seed),
        )
        present += int(float(choice.window_spec.get("density_multiplier", 0.0)) > 0.01)
        assert int(choice.window_spec.get("maximum_windows_per_wall", 99)) <= 2
    assert 3 <= present <= 28
