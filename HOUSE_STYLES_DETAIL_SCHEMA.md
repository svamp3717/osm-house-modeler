# Expanded house-style data

All 24 region JSON files retain `schema_version: 2` for compatibility. The detailed fields are additive, and explicit OpenStreetMap tags remain authoritative over procedural defaults.

## Top-level detail metadata

- `detail_revision`
- `detail_level`
- `regional_overview`

## Per-context `architectural_details`

Each `rural` and `town_city` context can contain:

- `materials`
- `geometry_defaults`
- `windows`
- `doors`
- `building_family_profiles`
- `building_class_profiles`

The `industrial` family is included in every context so warehouses and similar utility buildings have regional material, roof, opening, and foundation policy.

## Windows

`windows.type_distribution` describes region-appropriate window constructions. `windows.special_sets` provides dimensions/types for utility, industrial, school/large-regular, and storefront openings.

### Procedural placement

`windows.procedural_placement` controls how windows are arranged on the generated facade. The generator selects one weighted `style_distribution` entry using the current procedural seed, then applies the configured jitter, omissions, wall-role density, and floor behavior.

Supported placement styles:

- `regular_aligned`: regular bays vertically aligned between storeys.
- `symmetric_bays`: balanced/even facade rhythm with no random horizontal drift.
- `staggered_floors`: upper floors receive a controlled alternating horizontal phase shift.
- `irregular_cottage`: seed-driven horizontal/vertical variation with occasional omitted bays.
- `paired_groups`: openings are arranged in pairs around repeated group centres.
- `sparse_asymmetric`: low-density, seed-varied openings for cabins, barns, sheds, and less formal stock.
- `clerestory_band`: high-sill strip/clerestory treatment for industrial buildings.
- `storefront_rhythm`: front-biased commercial glazing with lower side/rear density.

Common fields:

- `style_distribution`
- `horizontal_jitter_fraction`
- `vertical_jitter_m`
- `omit_bay_probability`
- `floor_phase_shift_fraction`
- `front_density_multiplier`
- `side_density_multiplier`
- `rear_density_multiplier`
- `minimum_windows_per_primary_facade`
- `maximum_windows_per_wall`
- `paired_group_gap_fraction`
- `family_overrides`
- `building_class_overrides`

`family_overrides` supplies special procedural rules for townhouse, urban, school, shop, industrial, agricultural, and outbuilding families. `building_class_overrides` can additionally provide `window_probability` and `density_multiplier`, letting a specific semantic class override the broader family. Cabins keep their irregular/sparse residential placement mix; sheds, garages, and barns are explicitly windowless; warehouses use a low seeded window probability and, when selected, sparse utility/clerestory glazing with at most a couple of openings per wall.

## Building-class profiles

`architectural_details.building_class_profiles` can refine a specific OSM building class without inventing a new material family. Every region now contains a `cabin` profile:

```json
"cabin": {
  "family": "residential",
  "default_levels": 1,
  "automatic_max_levels": 1,
  "storey_height_m": 3.0,
  "window_placement_profile": "cabin"
}
```

This means `building=cabin` uses residential regional materials/windows/doors but defaults to one storey when OSM does not specify `building:levels` or `height`. Explicit OSM height/level tags still override the automatic default.

## Doors

`doors.type_distribution` and the dedicated `garage`, `barn`, `warehouse`, `shop`, and `school` entries define regional door types and dimensions. Door placement also provides corner and window-clearance values used by facade generation.

## Geometry and foundations

`geometry_defaults` provides regional storey heights, wall-thickness bands, foundation/plinth guidance, roof shape probabilities, pitch/eave ranges, and roof materials. These values feed actual mesh generation rather than serving only as descriptive metadata. In **Simple interior** mode, `wall_thickness_m.lightweight`, `.masonry`, and `.heavy_or_insulated` now control the depth between the exterior facade and the generated interior wall face/reveals.

## Roof-integrated top storeys

`architectural_details.roof_storeys` controls whether the uppermost level is placed inside a compatible roof volume rather than on another full rectangular wall storey.

Common fields:

- `eligible_roof_shapes`: currently `gabled` for the side-window-only implementation.
- `minimum_total_levels`: minimum total occupied levels required before procedural roof-storey selection can activate.
- `force_compatible_roof_when_selected`: when true, an untagged procedural roof may switch to a compatible gable. Explicit OSM `roof:shape` is never overridden.
- `probability_by_building_class`: seeded probability for classes such as `cottage`, `cabin`, `residential`, `apartments`, `townhouse`, `hotel`, and `office`.
- `probability_by_family`: fallback probabilities for residential/townhouse/urban families and zero defaults for utility families.
- `window_policy.gable_ends_only`: currently true. Roof-storey windows appear only in vertical gable-end walls.
- `window_policy.minimum_roof_height_m`: ensures enough vertical roof volume for a usable attic window.
- `window_policy.sill_above_eave_m`: window sill elevation above the eave/wall top.
- `window_policy.top_clearance_m`: clearance between window head and sloping roof envelope.
- `window_policy.side_clearance_m`: clearance from the sloping gable edges.
- `window_policy.window_width_scale` / `window_height_scale`: scale the context's normal window dimensions for attic use.
- `window_policy.windows_per_gable_distribution`: weighted choice of one or two windows per usable gable.

The generator solves the actual roof-slope intersections at the attic window head height and constrains the complete rectangular window panel inside the resulting gable interval. This prevents a procedural attic window from crossing through either roof plane.

Every region also contains `building_class_profiles.cottage` and `building_class_profiles.apartments`. Cottages default to two automatic levels so the regional attic probability can choose between a normal upper wall storey and a roof-integrated second level. Apartment roof-storey probabilities are independent and generally lower. Cabins retain their one-storey automatic default.


## Procedural exterior details

`architectural_details.exterior_details` controls secondary building geometry. These rules are present in every rural/town context in all 24 regional profiles and are also expanded into the country profiles. The procedural seed resolves probabilities, weighted styles/materials, dimensions, and counts before geometry is generated.

Supported blocks:

- `stairs`: entrance steps/stoops. Uses the below-grade foundation depth so treads descend from the door datum instead of floating above the building. Vehicle-scale garage/barn/warehouse doors do not receive domestic stairs.
- `porches`: entrance slab, canopy and support posts. Country/region data can favour timber porches, masonry porticos, tiled canopies, verandas, or lightweight metal awnings.
- `chimneys`: one or two roof stacks with regional brick/render/stone/metal selection. Chimneys are omitted from dome/onion roofs and are seeded by building class. Sheds and garages have a hard zero-chimney policy even if a broad regional profile would otherwise select one.
- `balconies`: upper-storey projecting slabs with either masonry parapets or open timber/metal rails and posts. They require at least two regular wall levels and therefore are not attached to an attic-only level.
- `rainwater`: gutters on eligible eave/perimeter edges and a configurable number of downspouts. Gabled roofs omit gutters on gable ends; dome/onion roofs omit the simple rainwater geometry.
- `feature_budget`: descriptive minimum/maximum detail budget for future extension. Current generation uses the individual feature probabilities directly.

Each feature supports `probability_by_building_class`, allowing cottages, cabins, apartments, shops, warehouses, etc. to receive different detail frequencies even inside the same country. Most blocks also provide weighted `styles`, weighted `materials`, and dimensional ranges such as `width_m`, `depth_m`, `height_m`, `step_rise_m`, `step_depth_m`, `railing_height_m`, and `count_distribution`.

The generated OBJ uses three shared secondary material atlases:

- `detail_masonry.png` for stone/concrete/brick secondary geometry.
- `detail_wood.png` for timber porches/rails/details.
- `detail_metal.png` for gutters, downspouts, metal rails, flues, and canopies.

Explicit OSM hints such as `balcony=yes`, `porch=yes`, and `entrance:steps=yes` force their corresponding feature on when the building geometry is compatible. `chimney=yes` is still ignored for classes with a hard no-chimney rule such as sheds and garages.
