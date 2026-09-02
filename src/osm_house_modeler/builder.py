from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json
import math
from typing import Callable

from .exporter import write_obj
from .geometry import build_mesh, bounds, principal_axes
from .osm import fetch_way, lon_lat_to_local_m, parse_length_m
from .styles import discover_country_style_dir, discover_style_dir, load_profiles, choose_style
from .textures import make_textures


INTERIOR_MODES = ("exterior_only", "simple_interior")


def normalise_interior_mode(value: str = "exterior_only") -> str:
    text = str(value or "exterior_only").strip().casefold().replace(" ", "_").replace("-", "_")
    aliases = {"exterior": "exterior_only", "none": "exterior_only", "simple": "simple_interior", "interior": "simple_interior"}
    text = aliases.get(text, text)
    if text not in INTERIOR_MODES:
        raise ValueError(f"Unknown interior mode {value!r}. Choose one of: {', '.join(INTERIOR_MODES)}")
    return text


BUILDING_TYPE_OVERRIDES = (
    "auto",
    "house",
    "cottage",
    "cabin",
    "apartments",
    "townhouse",
    "shed",
    "garage",
    "barn",
    "warehouse",
    "industrial",
    "hangar",
    "shop",
    "school",
    "office",
    "commercial",
)


def apply_building_type_override(tags: dict[str, str], building_type: str = "auto") -> dict[str, str]:
    """Return effective OSM tags for a GUI/CLI building-type override.

    The override changes semantic classification while keeping the mapped
    footprint and dimensional tags intact. This means users can reinterpret a
    way as a barn, garage, warehouse, cottage, etc. without editing OSM data.
    Conflicting semantic tags such as amenity/shop/man_made are cleared so the
    explicit override remains authoritative.
    """
    requested = str(building_type or "auto").strip().casefold().replace(" ", "_")
    aliases = {
        "auto_(osm)": "auto",
        "auto_osm": "auto",
        "residential": "house",
        "apartment": "apartments",
        "flat": "apartments",
        "garages": "garage",
        "farm": "barn",
        "farm_auxiliary": "barn",
        "retail": "shop",
    }
    requested = aliases.get(requested, requested)
    if requested not in BUILDING_TYPE_OVERRIDES:
        raise ValueError(
            f"Unknown building type override {building_type!r}. "
            f"Choose one of: {', '.join(BUILDING_TYPE_OVERRIDES)}"
        )
    effective = dict(tags)
    if requested == "auto":
        return effective

    # Semantic overrides should beat stale/mismatched OSM use tags from the
    # original feature. Geometry/height/material tags are intentionally kept.
    for key in ("amenity", "shop", "man_made"):
        effective.pop(key, None)

    building_value = {
        "house": "house",
        "cottage": "cottage",
        "cabin": "cabin",
        "apartments": "apartments",
        "townhouse": "townhouse",
        "shed": "shed",
        "garage": "garage",
        "barn": "barn",
        "warehouse": "warehouse",
        "industrial": "industrial",
        "hangar": "hangar",
        "shop": "shop",
        "school": "school",
        "office": "office",
        "commercial": "commercial",
    }[requested]
    effective["building"] = building_value
    if requested == "school":
        effective["amenity"] = "school"
    elif requested == "shop":
        effective["shop"] = "yes"
    return effective


def _height(
    tags: dict[str, str],
    family: str,
    building_class: str,
    storey_height_m: float,
    default_levels: int = 0,
) -> float:
    explicit = parse_length_m(tags.get("height"))
    if explicit and explicit > 1:
        return explicit
    levels = parse_length_m(tags.get("building:levels"))
    if levels:
        return max(2.4, levels * max(2.4, storey_height_m))
    if default_levels > 0:
        return max(2.4, default_levels * max(2.4, storey_height_m))
    default_levels_by_family = {
        "residential": 2,
        "townhouse": 2,
        "urban": 3,
        "agricultural": 1,
        "outbuilding": 1,
        "industrial": 1,
        "school": 1,
        "shop": 1,
    }
    # Cabins stay residential for materials/openings, but default to one storey.
    if building_class == "cabin":
        return max(2.4, storey_height_m)
    return max(2.4, default_levels_by_family.get(family, 2) * max(2.4, storey_height_m))


def _levels(
    tags: dict[str, str],
    wall_h: float,
    storey_height_m: float,
    family: str,
    building_class: str,
    default_levels: int = 0,
    automatic_max_levels: int = 0,
) -> int:
    explicit = parse_length_m(tags.get("building:levels"))
    if explicit is not None and explicit > 0:
        return max(1, min(30, int(round(explicit))))
    # Explicit height is stronger evidence than regional automatic defaults.
    if parse_length_m(tags.get("height")) is not None:
        return max(1, min(30, int(round(wall_h / max(2.4, storey_height_m)))))
    if default_levels > 0:
        inferred = default_levels
    elif family in {"agricultural", "outbuilding", "industrial", "school", "shop"}:
        inferred = 1
    elif building_class == "cabin":
        inferred = 1
    else:
        inferred = max(1, int(round(wall_h / max(2.4, storey_height_m))))
    if automatic_max_levels > 0:
        inferred = min(inferred, automatic_max_levels)
    return max(1, min(30, inferred))


def _footprint_dimensions(poly: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    points = list(poly)
    if len(points) < 3:
        return (1.0, 1.0)
    center, u, v = principal_axes(points)
    pu = [(x - center[0]) * u[0] + (y - center[1]) * u[1] for x, y in points]
    pv = [(x - center[0]) * v[0] + (y - center[1]) * v[1] for x, y in points]
    dims = sorted((max(pu) - min(pu), max(pv) - min(pv)))
    return max(0.1, dims[0]), max(0.1, dims[1])


def _is_entrance(tags: dict[str, str]) -> bool:
    entrance = tags.get("entrance", "").strip().casefold()
    door = tags.get("door", "").strip().casefold()
    return (bool(entrance) and entrance not in {"no", "none"}) or (bool(door) and door not in {"no", "none"})


def build_way(
    way_id: int,
    output: Path,
    *,
    preset: str = "auto",
    country_preset: str = "auto",
    context: str = "auto",
    timeout: float = 20.0,
    progress: Callable[[str], None] | None = None,
    add_windows: bool = True,
    add_doors: bool = True,
    add_details: bool = True,
    seed: int | str = 0,
    foundation_depth: float | None = None,
    building_type: str = "auto",
    interior_mode: str = "exterior_only",
) -> Path:
    notify = progress or (lambda _message: None)
    interior_mode = normalise_interior_mode(interior_mode)
    notify("Fetching OpenStreetMap way…")
    way = fetch_way(way_id, timeout=timeout)
    effective_tags = apply_building_type_override(way.tags, building_type)
    notify("Converting footprint to local metre coordinates…")
    local = lon_lat_to_local_m(way.lon_lat)
    width_m, length_m = _footprint_dimensions(local)
    lon, lat = way.center

    notify("Selecting detailed country / regional architecture and building class…")
    profiles = load_profiles()
    choice = choose_style(
        profiles, lon, lat, effective_tags, way_id, context, preset,
        country_preset=country_preset,
        width_m=width_m, length_m=length_m, seed=seed,
    )
    wall_h = _height(
        effective_tags, choice.family, choice.building_class, choice.storey_height_m, choice.default_levels
    )
    levels = _levels(
        effective_tags, wall_h, choice.storey_height_m, choice.family, choice.building_class,
        choice.default_levels, choice.automatic_max_levels,
    )
    minimum_roof_storey_levels = max(2, int(choice.roof_storey_spec.get("minimum_total_levels", 2) or 2))
    tagged_roof_levels_raw = parse_length_m(effective_tags.get("roof:levels"))
    tagged_roof_levels = 1 if tagged_roof_levels_raw is not None and tagged_roof_levels_raw > 0 else 0
    prospective_total_levels = levels + tagged_roof_levels if tagged_roof_levels else levels
    roof_storey_active = bool(
        choice.roof_storey
        and choice.roof_style == "gabled"
        and prospective_total_levels >= minimum_roof_storey_levels
        and choice.family in {"residential", "townhouse", "urban"}
    )
    if roof_storey_active and tagged_roof_levels:
        # OSM roof:levels is separate from building:levels. Keep all regular wall
        # levels and add one supported roof-integrated level above them.
        wall_levels = levels
        total_levels = levels + 1
    else:
        # Procedural mode converts the inferred uppermost regular level into the
        # attic, preserving the overall level count instead of adding a new one.
        wall_levels = max(1, levels - 1) if roof_storey_active else levels
        total_levels = levels

    if foundation_depth is None:
        actual_foundation_depth = max(0.15, float(choice.foundation_depth_m))
    else:
        try:
            actual_foundation_depth = float(foundation_depth)
        except (TypeError, ValueError) as exc:
            raise ValueError("Foundation depth must be a number or auto") from exc
        if not math.isfinite(actual_foundation_depth) or actual_foundation_depth < 0.15:
            raise ValueError("Foundation depth must be at least 0.15 m")
    actual_foundation_depth = min(5.0, actual_foundation_depth)

    minx, miny, maxx, maxy = bounds(list(local))
    span = max(1.0, min(maxx - minx, maxy - miny))
    roof_h = parse_length_m(effective_tags.get("roof:height"))
    if roof_h is None:
        if choice.roof_style == "flat":
            roof_h = 0.0
        elif choice.roof_style in {"dome", "onion"}:
            roof_h = min(7.0, max(1.2, span * 0.35))
        else:
            pitch = math.radians(max(5.0, min(70.0, choice.roof_pitch_degrees)))
            roof_h = min(8.0, max(0.8, math.tan(pitch) * span * 0.5))

    if roof_storey_active:
        minimum_attic_height = max(
            2.1,
            float(choice.roof_storey_spec.get("minimum_roof_height_m", 2.35) or 2.35),
            float(choice.roof_storey_spec.get("sill_above_eave_m", 0.42) or 0.42)
            + float(choice.window_spec.get("height_m", 1.2) or 1.2)
            * float(choice.roof_storey_spec.get("window_height_scale", 0.78) or 0.78)
            + float(choice.roof_storey_spec.get("top_clearance_m", 0.34) or 0.34),
        )
        roof_h = max(roof_h, minimum_attic_height)
        explicit_height = parse_length_m(effective_tags.get("height"))
        if explicit_height is not None and explicit_height > roof_h + 2.1:
            # OSM ``height`` is normally total exterior height. Preserve it by
            # moving the eave down rather than stacking an attic above it.
            wall_h = max(2.1 * wall_levels, explicit_height - roof_h)
        else:
            wall_h = max(2.4, wall_levels * max(2.4, choice.storey_height_m))

    # ``node_tags`` was added to OSMWay after the first fetcher implementation.
    # Be tolerant of older/custom OSMWay objects too: mapped entrance tags are
    # an enhancement, never a requirement for generating the building.
    node_tags = getattr(way, "node_tags", ())
    entrance_points = tuple(
        point for point, tags in zip(local, node_tags) if _is_entrance(tags)
    )
    notify(
        f"Generating {choice.building_class} / {choice.family}: {choice.roof_style} roof, "
        f"{choice.window_spec.get('type', 'regional')} windows / {choice.window_spec.get('placement_style', 'regular_aligned')} layout, "
        f"{choice.door_spec.get('type', 'regional')} door"
        + (" / roof-integrated top storey" if roof_storey_active else "")
        + (" / simple enterable interior with cut openings" if interior_mode == "simple_interior" else " / exterior only")
        + (" / procedural exterior details…" if add_details else "…")
    )
    mesh = build_mesh(
        local,
        wall_h,
        roof_h,
        choice.roof_style,
        levels=wall_levels,
        add_windows=add_windows,
        add_doors=add_doors,
        family=choice.family,
        building_class=choice.building_class,
        outbuilding_kind=choice.outbuilding_kind,
        foundation_depth=actual_foundation_depth,
        seed=seed,
        entrance_points=entrance_points,
        window_spec=dict(choice.window_spec),
        door_spec=dict(choice.door_spec),
        roof_storey=roof_storey_active,
        roof_storey_spec=dict(choice.roof_storey_spec),
        add_details=add_details,
        exterior_detail_spec=dict(choice.exterior_detail_spec),
        interior_mode=interior_mode,
        wall_thickness=choice.wall_thickness_m,
    )

    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    notify("Generating detailed regional materials and opening textures…")
    make_textures(
        output,
        choice,
        seed_text=f"{way_id}:{seed}:{choice.family}:{choice.building_class}",
        no_glass=(interior_mode == "simple_interior"),
    )
    notify("Exporting OBJ, MTL and metadata…")
    obj = write_obj(mesh, output, f"way_{way_id}")
    metadata = {
        "osm_way_id": way_id,
        "center_lon_lat": [lon, lat],
        "osm_tags": way.tags,
        "effective_tags": effective_tags,
        "building_type_override": str(building_type or "auto"),
        "regional_preset_requested": str(preset or "auto"),
        "country_preset_requested": str(country_preset or "auto"),
        "interior_mode": interior_mode,
        "style": asdict(choice),
        "wall_height_m": wall_h,
        "building_levels": total_levels,
        "wall_levels": wall_levels,
        "roof_levels": 1 if roof_storey_active else 0,
        "roof_storey_active": roof_storey_active,
        "footprint_dimensions_m": [width_m, length_m],
        "roof_height_m": roof_h,
        "foundation_depth_m": actual_foundation_depth,
        "foundation_type": choice.foundation_type,
        "seed": str(seed),
        "procedural_features": {
            "windows_enabled": add_windows,
            "doors_enabled": add_doors,
            "exterior_details_enabled": add_details,
            "simple_interior_enabled": interior_mode == "simple_interior",
            "interior_wall_thickness_m": choice.wall_thickness_m if interior_mode == "simple_interior" else 0.0,
            "window_count": mesh.detail_counts.get("window_holes", sum(1 for face in mesh.faces if face.material == "window") // 2),
            "door_count": (
                mesh.detail_counts.get("door_holes", 0) + mesh.detail_counts.get("balcony_doors", 0)
                if interior_mode == "simple_interior"
                else sum(1 for face in mesh.faces if face.material in {"door", "door_openable"}) // 2
            ),
            "balcony_door_count": mesh.detail_counts.get("balcony_doors", 0),
            "openable_door_count": mesh.detail_counts.get("openable_doors", 0),
            "door_default_open_angle_degrees": 38.0 if interior_mode == "simple_interior" and mesh.detail_counts.get("openable_doors", 0) else 0.0,
            "foundation_faces": sum(1 for face in mesh.faces if face.material == "foundation"),
            "mapped_entrances_used": len(entrance_points),
            "exterior_detail_counts": dict(mesh.detail_counts),
            "exterior_detail_spec": choice.exterior_detail_spec,
        },
        "source_style_profiles": str(discover_style_dir()) if profiles else "built-in geographic fallback",
        "source_country_profiles": str(discover_country_style_dir() or ""),
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    notify("Model generation complete.")
    return obj
