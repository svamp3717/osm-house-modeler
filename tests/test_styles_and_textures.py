from pathlib import Path

from osm_house_modeler.exporter import write_obj
from osm_house_modeler.geometry import build_mesh
from osm_house_modeler.gui import load_obj_preview
from osm_house_modeler.styles import discover_style_dir, load_profiles
from osm_house_modeler.textures import make_textures


def test_local_house_styles_catalogue_has_24_profiles() -> None:
    directory = discover_style_dir()
    assert directory is not None
    assert directory.name == "house_styles"
    profiles = load_profiles()
    assert len(profiles) == 24
    assert profiles[-1].identifier == "sweden"


def test_exporter_splits_wall_and_roof_objects_and_preview_loads_textures(tmp_path: Path) -> None:
    mesh = build_mesh(((0, 0), (10, 0), (10, 6), (0, 6)), 5.0, 2.0, "gabled")
    make_textures(tmp_path, "sweden", "swedish_wood", "tile", "test")
    obj = write_obj(mesh, tmp_path, "house")

    text = obj.read_text(encoding="utf-8")
    assert "o house_wall" in text
    assert "usemtl wall" in text
    assert "o house_roof" in text
    assert "usemtl roof" in text

    preview = load_obj_preview(obj)
    assert preview.uvs
    assert all(face.uvs[0] is not None for face in preview.faces)
    assert preview.materials["wall"].texture_path == (tmp_path / "wall.png").resolve()
    assert preview.materials["roof"].texture_path == (tmp_path / "roof.png").resolve()


def test_exporter_includes_window_and_door_materials(tmp_path: Path) -> None:
    mesh = build_mesh(((0, 0), (12, 0), (12, 7), (0, 7)), 6.0, 2.0, "gabled", levels=2)
    make_textures(tmp_path, "sweden", "swedish_wood", "tile", "features")
    obj = write_obj(mesh, tmp_path, "features")
    mtl = (tmp_path / "features.mtl").read_text(encoding="utf-8")
    text = obj.read_text(encoding="utf-8")
    assert "o features_window" in text
    assert "o features_door" in text
    assert "newmtl window" in mtl
    assert "newmtl door" in mtl
    preview = load_obj_preview(obj)
    assert any(face.material == "window" for face in preview.faces)
    assert any(face.material == "door" for face in preview.faces)


def test_detailed_sweden_profile_drives_opening_and_material_specs() -> None:
    from osm_house_modeler.styles import choose_style

    choice = choose_style(
        load_profiles(), 18.06, 59.33, {"building": "house"}, 123,
        preset="sweden", width_m=12.0, length_m=8.0, seed="detail-test",
    )
    assert choice.detail_level
    assert choice.window_spec["type"]
    assert choice.window_spec["frame_material"]
    assert choice.door_spec["type"]
    assert choice.foundation_type
    assert choice.roof_material
    assert choice.colour_palette


def test_every_region_has_procedural_window_placement_data() -> None:
    import json

    directory = discover_style_dir()
    assert directory is not None
    files = sorted(directory.glob("*.json"))
    assert len(files) == 24
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        for context_name, context in document["contexts"].items():
            details = context["architectural_details"]
            procedural = details["windows"]["procedural_placement"]
            assert sum(item["weight"] for item in procedural["style_distribution"]) == 100, (path.name, context_name)
            assert "cabin" in procedural["building_class_overrides"]
            assert details["building_class_profiles"]["cabin"]["default_levels"] == 1
            for family, override in procedural["family_overrides"].items():
                assert sum(item["weight"] for item in override["style_distribution"]) == 100, (path.name, context_name, family)


def test_seed_selects_regional_window_placement_style() -> None:
    from osm_house_modeler.styles import choose_style

    profiles = load_profiles()
    styles = {
        choose_style(
            profiles, 18.06, 59.33, {"building": "cabin"}, 321,
            preset="sweden", width_m=8.0, length_m=6.0, seed=str(seed),
        ).window_spec["placement_style"]
        for seed in range(24)
    }
    assert styles.issubset({"irregular_cottage", "sparse_asymmetric", "symmetric_bays", "regular_aligned"})
    assert len(styles) >= 2


def test_country_catalogue_has_full_iso_set() -> None:
    from osm_house_modeler.styles import load_country_profiles
    countries = load_country_profiles()
    assert len(countries) == 249
    assert {country.iso_alpha2 for country in countries} >= {"SE", "DE", "JP", "US", "GB"}


def test_country_geometry_refines_region_profile() -> None:
    from osm_house_modeler.styles import choose_country, load_country_profiles
    country = choose_country(load_country_profiles(), 13.405, 52.52, {})
    assert country is not None
    assert country.iso_alpha2 == "DE"
    assert country.parent_region_identifier == "western_europe"


def test_explicit_country_tag_works_without_country_polygon() -> None:
    from osm_house_modeler.styles import choose_country, load_country_profiles
    country = choose_country(load_country_profiles(), -0.1276, 51.5072, {"addr:country": "GB"})
    assert country is not None
    assert country.iso_alpha2 == "GB"


def test_choose_style_applies_country_specific_context() -> None:
    from osm_house_modeler.styles import choose_style
    profiles = load_profiles()
    choice = choose_style(
        profiles, 13.405, 52.52, {"building": "house"}, 1234,
        width_m=10.0, length_m=8.0, seed=99,
    )
    assert choice.region_identifier == "western_europe"
    assert choice.country_code == "DE"
    assert choice.country_name == "Germany"
    assert choice.country_profile_identifier.startswith("de_")
    assert choice.window_spec["type"] in {"tilt_turn", "casement", "fixed_plus_operable"}


def test_no_glass_window_texture_has_clean_opening_without_mullions(tmp_path: Path) -> None:
    from PIL import Image

    make_textures(tmp_path, "sweden", "swedish_wood", "tile", "noglass", no_glass=True)
    img = Image.open(tmp_path / "window.png").convert("RGB")
    # Interior-mode frame rings sample from the outer border of window.png; if the
    # no-glass texture still contains internal mullion bars, wide apartment-window
    # frames appear visibly broken. Sample the centerline and verify it stays close
    # to a consistent fill rather than containing strong dark mullion spikes.
    y = img.height // 2
    samples = [img.getpixel((x, y)) for x in range(48, img.width - 48)]
    luminance = [sum(pixel) / 3.0 for pixel in samples]
    assert max(luminance) - min(luminance) < 30.0


def test_simple_interior_exports_dedicated_window_frame_texture(tmp_path: Path) -> None:
    mesh = build_mesh(
        ((0.0, 0.0), (8.0, 0.0), (8.0, 6.0), (0.0, 6.0)),
        3.0, 2.0, "gabled", levels=1, family="townhouse",
        building_class="townhouse", interior_mode="simple_interior",
        add_windows=True, add_doors=False,
        window_spec={
            "density_multiplier": 1.0, "width_m": 1.5, "height_m": 1.3,
            "sill_height_m": 0.85, "edge_margin_m": 0.5,
            "target_bay_spacing_m": 2.5, "placement_style": "regular_aligned",
        },
    )
    make_textures(tmp_path, "sweden", "swedish_wood", "tile", "frame-atlas", no_glass=True)
    obj = write_obj(mesh, tmp_path, "townhouse_frame")
    assert (tmp_path / "window_frame.png").is_file()
    mtl = obj.with_suffix(".mtl").read_text(encoding="utf-8")
    assert "newmtl window_frame" in mtl
    assert "map_Kd window_frame.png" in mtl
    assert any(face.material == "window_frame" for face in mesh.faces)


def test_all_style_catalogues_encode_utility_window_and_chimney_constraints() -> None:
    import json
    root = Path(__file__).resolve().parents[1]
    checked = 0
    for directory in (root / "house_styles", root / "country_styles"):
        for path in directory.glob("*.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc.get("contexts"), dict):
                continue
            for context in doc["contexts"].values():
                details = context["architectural_details"]
                overrides = details["windows"]["procedural_placement"]["building_class_overrides"]
                for klass in ("shed", "garage", "barn"):
                    assert overrides[klass]["window_probability"] == 0.0
                    assert overrides[klass]["density_multiplier"] == 0.0
                assert 0.0 < overrides["warehouse"]["window_probability"] <= 0.25
                assert overrides["warehouse"]["maximum_windows_per_wall"] <= 2
                chimney_probs = details["exterior_details"]["chimneys"]["probability_by_building_class"]
                assert chimney_probs["shed"] == 0.0
                assert chimney_probs["garage"] == 0.0
                checked += 1
    assert checked == 546


def test_forced_country_uses_its_parent_region_even_if_region_preset_conflicts() -> None:
    from osm_house_modeler.styles import choose_style

    profiles = load_profiles()
    choice = choose_style(
        profiles, 18.06, 59.33, {"building": "house"}, 777,
        preset="sweden", country_preset="JP",
        width_m=10.0, length_m=8.0, seed="forced-japan",
    )
    assert choice.country_code == "JP"
    assert choice.country_name == "Japan"
    assert choice.region_identifier == "east_asia"


def test_country_selector_accepts_gui_label_and_iso_codes() -> None:
    from osm_house_modeler.styles import country_selector_label, find_country_profile, load_country_profiles

    countries = load_country_profiles()
    sweden = find_country_profile(countries, "SE")
    assert sweden is not None
    assert sweden.parent_region_identifier == "sweden"
    assert find_country_profile(countries, country_selector_label(sweden)) == sweden
    assert find_country_profile(countries, "SWE") == sweden
    assert find_country_profile(countries, "auto") is None
