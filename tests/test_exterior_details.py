from __future__ import annotations

import json
from pathlib import Path

from osm_house_modeler.geometry import build_mesh
from osm_house_modeler.styles import choose_style, load_profiles
from osm_house_modeler.textures import make_textures
from osm_house_modeler.exporter import write_obj


def _forced_detail_spec() -> dict[str, object]:
    return {
        "stairs": {
            "enabled": True,
            "type": "stone_stoop",
            "material": "stone",
            "width_m": 1.8,
            "step_rise_m": 0.16,
            "step_depth_m": 0.30,
            "max_steps": 3,
        },
        "porches": {
            "enabled": True,
            "type": "timber_entry_porch",
            "material": "timber",
            "width_m": 2.6,
            "depth_m": 1.2,
        },
        "chimneys": {
            "enabled": True,
            "type": "brick_rectangular",
            "material": "brick",
            "width_m": 0.5,
            "depth_m": 0.4,
            "height_m": 1.1,
            "count": 1,
        },
        "balconies": {
            "enabled": True,
            "type": "painted_metal_railing",
            "material": "painted/galvanised steel",
            "width_m": 2.8,
            "depth_m": 1.0,
            "railing_height_m": 0.95,
            "post_spacing_m": 1.2,
            "count": 1,
        },
        "rainwater": {
            "enabled": True,
            "material": "painted/galvanised steel",
            "gutter_width_m": 0.1,
            "downspout_width_m": 0.08,
            "downspouts": 2,
        },
    }


def test_all_region_and_country_contexts_have_exterior_details() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in root.joinpath("house_styles").glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for context in doc["contexts"].values():
            exterior = context["architectural_details"]["exterior_details"]
            assert {"stairs", "porches", "chimneys", "balconies", "rainwater"} <= set(exterior)
    country_count = 0
    for path in root.joinpath("country_styles").glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not doc.get("iso_alpha2"):
            continue
        country_count += 1
        for context in doc["contexts"].values():
            assert "exterior_details" in context["architectural_details"]
    assert country_count == 249


def test_style_choice_resolves_seeded_exterior_detail_spec() -> None:
    choice = choose_style(
        load_profiles(),
        18.07,
        59.33,
        {"building": "cottage", "addr:country": "SE"},
        1234,
        preset="sweden",
        width_m=9.0,
        length_m=13.0,
        seed="details-test",
    )
    spec = choice.exterior_detail_spec
    assert choice.country_code == "SE"
    assert {"stairs", "porches", "chimneys", "balconies", "rainwater"} <= set(spec)
    assert 0.0 <= spec["chimneys"]["probability"] <= 1.0
    assert spec["stairs"]["type"]
    assert spec["balconies"]["material"]


def test_detail_geometry_generates_secondary_architecture(tmp_path: Path) -> None:
    mesh = build_mesh(
        ((0.0, 0.0), (12.0, 0.0), (12.0, 8.0), (0.0, 8.0)),
        6.0,
        2.8,
        "gabled",
        levels=2,
        family="residential",
        building_class="cottage",
        foundation_depth=0.8,
        add_windows=True,
        add_doors=True,
        seed="forced-details",
        window_spec={
            "density_multiplier": 1.0,
            "width_m": 1.1,
            "height_m": 1.2,
            "sill_height_m": 0.9,
            "edge_margin_m": 0.6,
            "target_bay_spacing_m": 3.0,
        },
        door_spec={
            "primary_width_m": 0.95,
            "primary_height_m": 2.1,
            "corner_clearance_m": 0.7,
            "keep_clear_of_windows_m": 0.35,
        },
        exterior_detail_spec=_forced_detail_spec(),
        add_details=True,
    )
    assert mesh.detail_counts["stairs"] >= 1
    assert mesh.detail_counts["porches"] == 1
    assert mesh.detail_counts["chimneys"] == 1
    assert mesh.detail_counts["balconies"] == 1
    assert mesh.detail_counts["gutters"] >= 1
    assert mesh.detail_counts["downspouts"] >= 1
    materials = {face.material for face in mesh.faces}
    assert {"detail_masonry", "detail_wood", "detail_metal"} <= materials

    make_textures(tmp_path, "sweden", "swedish_wood", "tile", "features")
    obj = write_obj(mesh, tmp_path, "details")
    mtl = obj.with_suffix(".mtl").read_text(encoding="utf-8")
    for name in ("detail_masonry.png", "detail_wood.png", "detail_metal.png"):
        assert (tmp_path / name).is_file()
        assert name in mtl


def test_detail_toggle_can_disable_all_secondary_geometry() -> None:
    mesh = build_mesh(
        ((0.0, 0.0), (10.0, 0.0), (10.0, 7.0), (0.0, 7.0)),
        6.0,
        2.5,
        "gabled",
        levels=2,
        family="residential",
        building_class="house",
        foundation_depth=0.8,
        exterior_detail_spec=_forced_detail_spec(),
        add_details=False,
    )
    assert mesh.detail_counts == {}
    assert not any(face.material.startswith("detail_") for face in mesh.faces)


def test_stairs_use_primary_textured_material_for_opengl() -> None:
    spec = _forced_detail_spec()
    mesh = build_mesh(
        ((0.0, 0.0), (10.0, 0.0), (10.0, 7.0), (0.0, 7.0)),
        3.0, 2.0, "gabled", levels=1, family="residential",
        building_class="house", foundation_depth=0.8,
        add_windows=False, add_doors=True, seed="stair-texture",
        door_spec={
            "primary_width_m": 0.95, "primary_height_m": 2.1,
            "corner_clearance_m": 0.7, "keep_clear_of_windows_m": 0.35,
        },
        exterior_detail_spec=spec, add_details=True,
    )
    assert mesh.detail_counts.get("stairs", 0) > 0
    # Stone/concrete stairs are deliberately mapped to the always-present
    # foundation material, avoiding optional detail-material texture failures.
    assert any(face.material == "foundation" for face in mesh.faces)


def test_stair_run_uses_clean_textured_treads() -> None:
    spec = {
        "stairs": {
            "enabled": True, "type": "stone_stoop", "material": "stone",
            "width_m": 1.8, "step_rise_m": 0.16, "step_depth_m": 0.30,
            "max_steps": 4,
        }
    }
    base = build_mesh(
        ((0.0, 0.0), (10.0, 0.0), (10.0, 7.0), (0.0, 7.0)),
        3.0, 2.0, "gabled", levels=1, family="residential",
        building_class="house", foundation_depth=0.8,
        add_windows=False, add_doors=True, seed="clean-stairs",
        door_spec={
            "primary_width_m": 0.95, "primary_height_m": 2.1,
            "corner_clearance_m": 0.7, "keep_clear_of_windows_m": 0.35,
        },
        add_details=False,
    )
    detailed = build_mesh(
        ((0.0, 0.0), (10.0, 0.0), (10.0, 7.0), (0.0, 7.0)),
        3.0, 2.0, "gabled", levels=1, family="residential",
        building_class="house", foundation_depth=0.8,
        add_windows=False, add_doors=True, seed="clean-stairs",
        door_spec={
            "primary_width_m": 0.95, "primary_height_m": 2.1,
            "corner_clearance_m": 0.7, "keep_clear_of_windows_m": 0.35,
        },
        exterior_detail_spec=spec, add_details=True,
    )
    stair_faces = detailed.faces[len(base.faces):]
    assert detailed.detail_counts.get("stairs") == 4
    assert stair_faces
    assert {face.material for face in stair_faces} == {"foundation"}
    # The new stair skin must have horizontal tread triangles rather than only
    # thin vertical box fragments.
    upward = 0
    for face in stair_faces:
        a, b, c = (detailed.vertices[index - 1] for index in face.vertices)
        ab = (b[0]-a[0], b[1]-a[1], b[2]-a[2])
        ac = (c[0]-a[0], c[1]-a[1], c[2]-a[2])
        nz = ab[0]*ac[1] - ab[1]*ac[0]
        upward += int(nz > 1e-8)
    assert upward >= detailed.detail_counts["stairs"] * 2


def test_balconies_use_dedicated_textured_material_for_opengl(tmp_path: Path) -> None:
    mesh = build_mesh(
        ((0.0, 0.0), (12.0, 0.0), (12.0, 8.0), (0.0, 8.0)),
        6.0, 2.8, "gabled", levels=3, family="urban",
        building_class="apartments", foundation_depth=0.8,
        add_windows=True, add_doors=True, seed="balcony-opengl",
        window_spec={
            "density_multiplier": 1.0, "width_m": 1.2, "height_m": 1.25,
            "sill_height_m": 0.9, "edge_margin_m": 0.5, "target_bay_spacing_m": 2.7,
        },
        door_spec={
            "primary_width_m": 0.95, "primary_height_m": 2.1,
            "corner_clearance_m": 0.7, "keep_clear_of_windows_m": 0.35,
        },
        exterior_detail_spec=_forced_detail_spec(), add_details=True,
    )
    assert mesh.detail_counts.get("balconies", 0) > 0
    assert any(face.material == "balcony" for face in mesh.faces)
    make_textures(tmp_path, "sweden", "swedish_wood", "tile", "balcony")
    obj = write_obj(mesh, tmp_path, "balcony")
    assert (tmp_path / "balcony.png").is_file()
    mtl = obj.with_suffix(".mtl").read_text(encoding="utf-8")
    assert "newmtl balcony" in mtl
    assert "map_Kd balcony.png" in mtl
    from osm_house_modeler.viewer import _obj_texture_dependencies
    dependencies = dict(_obj_texture_dependencies(obj))
    assert dependencies["balcony.png"] == (tmp_path / "balcony.png").resolve()


def test_apartments_never_get_chimneys_even_when_forced() -> None:
    detail_spec = {
        "chimneys": {
            "enabled": True, "count": 2, "width_m": 0.5, "depth_m": 0.4,
            "height_m": 1.2, "material": "brick", "type": "brick_rectangular",
        }
    }
    mesh = build_mesh(
        ((0.0, 0.0), (14.0, 0.0), (14.0, 9.0), (0.0, 9.0)),
        9.0, 2.2, "gabled", levels=3, family="urban", building_class="apartments",
        add_windows=True, add_doors=True, exterior_detail_spec=detail_spec,
        add_details=True, seed="no-apartment-chimneys",
    )
    assert mesh.detail_counts.get("chimneys", 0) == 0


def test_all_style_contexts_disable_apartment_chimneys() -> None:
    root = Path(__file__).resolve().parents[1]
    checked = 0
    for folder in ("house_styles", "country_styles"):
        for path in root.joinpath(folder).glob("*.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc.get("contexts"), dict):
                continue
            for context in doc["contexts"].values():
                probs = context["architectural_details"]["exterior_details"]["chimneys"]["probability_by_building_class"]
                assert float(probs.get("apartments", 0.0)) == 0.0, path.name
                checked += 1
    assert checked == 546


def test_oriented_box_normals_face_outward_for_right_handed_and_left_handed_axes() -> None:
    from osm_house_modeler.geometry import Mesh, _add_oriented_box

    for depth_axis in ((0.0, 1.0), (0.0, -1.0)):
        mesh = Mesh()
        assert _add_oriented_box(
            mesh, (0.0, 0.0), (1.0, 0.0), depth_axis,
            4.0, 2.0, 1.0, 2.0, "balcony",
        )
        # Top triangles must face upward. The four side quads must face away from
        # the box centre. Reversed normals render nearly black in pyglet lighting,
        # which was mistaken for missing balcony texture.
        for face in mesh.faces:
            pts = [mesh.vertices[index - 1] for index in face.vertices]
            a, b, c = pts
            ab = (b[0]-a[0], b[1]-a[1], b[2]-a[2])
            ac = (c[0]-a[0], c[1]-a[1], c[2]-a[2])
            normal = (
                ab[1]*ac[2] - ab[2]*ac[1],
                ab[2]*ac[0] - ab[0]*ac[2],
                ab[0]*ac[1] - ab[1]*ac[0],
            )
            centroid = tuple(sum(p[i] for p in pts) / 3.0 for i in range(3))
            if abs(centroid[2] - 2.0) < 1e-6:
                assert normal[2] > 0.0
            elif abs(centroid[2] - 1.0) < 1e-6:
                assert normal[2] < 0.0
            else:
                radial = (centroid[0], centroid[1])
                assert normal[0] * radial[0] + normal[1] * radial[1] > 0.0


def test_balconies_get_fixed_access_doors_without_extra_animation() -> None:
    spec = {
        "balconies": {
            "enabled": True,
            "type": "painted_metal_railing",
            "material": "painted/galvanised steel",
            "width_m": 3.0,
            "depth_m": 1.1,
            "railing_height_m": 0.95,
            "post_spacing_m": 1.2,
            "count": 2,
        }
    }
    mesh = build_mesh(
        ((0.0, 0.0), (14.0, 0.0), (14.0, 9.0), (0.0, 9.0)),
        9.0, 2.4, "gabled", levels=3, family="urban",
        building_class="apartments", foundation_depth=0.8,
        add_windows=False, add_doors=True, seed="balcony-fixed-doors",
        door_spec={
            "primary_width_m": 0.95, "primary_height_m": 2.1,
            "corner_clearance_m": 0.7, "keep_clear_of_windows_m": 0.35,
        },
        exterior_detail_spec=spec, add_details=True,
        interior_mode="simple_interior", wall_thickness=0.22,
    )
    assert mesh.detail_counts.get("balconies") == 2
    assert mesh.detail_counts.get("balcony_doors") == 2
    # Only the primary entrance is animated. Balcony doors are deliberately fixed.
    assert mesh.detail_counts.get("openable_doors") == 1
    assert len(mesh.door_animations) == 1
    upper_door_faces = []
    for face in mesh.faces:
        if face.material != "door":
            continue
        zs = [mesh.vertices[index - 1][2] for index in face.vertices]
        if min(zs) > 2.5:
            upper_door_faces.append(face)
    assert upper_door_faces
