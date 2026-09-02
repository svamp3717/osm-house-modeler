# Country Styles Catalogue

`country_styles/` contains one expanded JSON profile for every ISO 3166-1 entry. The catalogue currently contains **249 country/territory profiles**, plus `index.json`.

Country profiles refine the 24 files in `house_styles/`. The regional profile remains the fallback and supplies the broad architectural family. When the generator can determine a country from an OSM country tag or the bundled low-resolution country geometry, the matching country context becomes the effective procedural style source.

## Matching

Each country JSON includes:

- `iso_alpha2`, `iso_alpha3`, and `iso_numeric`
- `parent_region_identifier`
- `match.country_aliases`
- `match.geometry` where bundled boundary geometry is available
- `match.envelopes_lon_lat` as a coarse fallback, especially for very small territories

The GUI and CLI can explicitly select a country profile. A forced country is authoritative for geographic style selection and automatically selects its `parent_region_identifier`. With the country selector set to `auto`, explicit OSM country tags are checked first. Recognised keys include `addr:country`, `country`, `country_code`, `is_in:country_code`, `ISO3166-1:alpha2`, and `ISO3166-1:alpha3`.

## Effective detail

The `contexts.rural` and `contexts.town_city` sections are fully expanded, not lightweight references. They contain the same detailed architecture structure used by the regional catalogue, including:

- facade family selection and materials
- roof shape/material/pitch defaults
- foundations and terrain strategy
- window types, dimensions, frame/glazing/trim information
- procedural window-placement distributions
- door types and utility entrance sizes
- building-family profiles
- cabin/cottage/apartment building-class profiles
- roof-integrated upper-storey probabilities and gable-window policy

Files marked `detail_level: country-expanded-curated` contain additional national tuning. Files marked `country-expanded-regional-baseline` intentionally start from the full parent-region baseline and can be refined directly without changing Python code.

## Precedence

1. Explicit OSM building attributes such as `building:material`, `roof:shape`, `roof:material`, `building:levels`, `height`, `roof:levels`, and mapped entrances.
2. Explicit GUI/CLI country preset, when selected. Its declared parent region is used automatically even if a conflicting regional preset was also supplied.
3. When Country is `auto`, explicit OSM country tags, then geographic country matching.
4. Country profile detail layered on its parent 24-region baseline.
5. Manual regional preset when Country is `auto`; auto-detected country detail is retained only when it belongs to that region.
6. Built-in coarse geographic fallback.

## Data note

These profiles are procedural defaults, not claims that every building in a country shares one architecture. Large countries can have enormous sub-national variation. The files are deliberately local and editable so future province/state/climate-zone refinements can be added without network access.


## Exterior-detail policy

Every country context contains the same `architectural_details.exterior_details` structure documented in `HOUSE_STYLES_DETAIL_SCHEMA.md`. Country data is authoritative when a country can be resolved; otherwise the parent regional profile supplies the rule set. This includes seeded probabilities and style/material choices for entrance stairs, porches/verandas, chimneys/flues, balconies, gutters, and downspouts.
