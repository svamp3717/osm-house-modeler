# OSM House Modeler

Generate textured procedural 3D building models from **OpenStreetMap building ways**.

OSM House Modeler downloads a building footprint and tags from OpenStreetMap, classifies the building, applies regional and country-specific architectural rules, and generates a textured Wavefront **OBJ/MTL** model. It includes both a desktop GUI and command-line tools, plus an OpenGL model viewer.

> Current version: **0.13.6**  
> Requires **Python 3.14+**

## Features

- Generate 3D buildings directly from an **OpenStreetMap way ID**
- Export textured **OBJ + MTL + PNG** assets
- Desktop GUI with an embedded model preview
- Separate OpenGL viewer powered by **pyglet**
- Procedural regional architecture using `house_styles/`
- Country-specific architecture using `country_styles/`
- **249 ISO country/territory profiles**
- Country and region presets work together automatically
- Rural and town/city architectural contexts
- Seeded procedural variation for repeatable results
- Building-class detection and manual override
- Gabled and other procedural roof forms
- Procedural windows and entrance doors
- Roof-storey / attic generation for suitable residential buildings
- Optional simple interior mode
- Procedural exterior details:
  - entrance stairs / stoops
  - porches and canopies
  - balconies with access doors
  - chimneys where appropriate
  - gutters and downspouts
- Foundation generation
- Scrollable GUI controls for smaller displays
- Offline country lookup for architecture selection

## Building types

The generator understands or can be manually forced to use several building classes, including:

- House
- Cottage
- Cabin
- Apartments
- Townhouse
- Shed
- Garage
- Barn
- Warehouse
- Industrial
- Hangar
- Shop
- School
- Office
- Commercial

Building-specific rules are applied where appropriate. For example:

- sheds and garages do not receive windows or chimneys
- barns do not receive ordinary windows
- apartments do not receive chimneys
- warehouse windows are uncommon and sparse

## Simple interior mode

The optional **Simple interior** mode creates a hollow, enterable-style shell rather than only an exterior facade.

It currently provides:

- real wall openings for windows and doors
- exterior window frames
- one open interior space per floor
- floor slabs for multi-storey buildings
- attic / roof-storey interior space where applicable
- an openable main entrance door in the viewer
- fixed balcony doors
- no window glass in interior mode

It is intentionally a lightweight procedural interior rather than a full architectural floor-plan generator.

## Requirements

- Python **3.14 or newer**
- [Pillow](https://pypi.org/project/Pillow/)
- [pyglet](https://pyglet.org/)

The Python dependencies are listed in `requirements.txt` and `pyproject.toml`.

## Installation

Clone the repository:

```bash
git clone https://github.com/svamp3717/osm-house-modeler.git
cd osm-house-modeler
```

Create a virtual environment:

### Windows PowerShell

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Linux / macOS

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

You can also install the project itself in editable mode:

```bash
pip install -e .
```

This adds the `osm3d` and `osm3d-gui` commands.

## Running the GUI

From the repository root:

```bash
python main.py
```

Or, after installing the package:

```bash
osm3d gui
```

You can also launch the GUI directly with:

```bash
osm3d-gui
```

### Basic GUI workflow

1. Find a building in OpenStreetMap.
2. Get its **way ID**.
3. Enter the way ID in OSM House Modeler.
4. Leave Region and Country on `auto`, or choose presets manually.
5. Choose a building-type override if needed.
6. Choose **Exterior only** or **Simple interior**.
7. Change the procedural seed if you want another architectural variation.
8. Generate the model.
9. Open the result in the OpenGL viewer or use the exported OBJ in another 3D application.

## Command-line usage

Build a building from an OSM way:

```bash
osm3d build 123456789
```

Choose an output directory:

```bash
osm3d build 123456789 -o my-building
```

Generate and immediately open the model viewer:

```bash
osm3d build 123456789 --view
```

Use Simple interior mode:

```bash
osm3d build 123456789 --interior-mode simple_interior
```

Choose a procedural seed:

```bash
osm3d build 123456789 --seed 42
```

Force a building type:

```bash
osm3d build 123456789 --building-type townhouse
```

Disable secondary exterior details:

```bash
osm3d build 123456789 --no-details
```

Disable procedural windows or the entrance door:

```bash
osm3d build 123456789 --no-windows
osm3d build 123456789 --no-doors
```

Open an existing OBJ:

```bash
osm3d view path/to/building.obj
```

## Country and region presets

OSM House Modeler uses a layered architecture system:

1. a **regional profile** provides the broad architectural baseline
2. a **country profile** refines that baseline

With both selectors set to `auto`, the generator determines the country from OSM tags and/or the building location, then applies its associated regional architecture.

You can force a country:

```bash
osm3d build 123456789 --country SE
```

Country values can be supplied as an ISO code, country name, or compatible country-profile identifier.

A forced country automatically selects its correct parent region. For example, selecting Japan uses the East Asia regional baseline even if an incompatible region was also supplied.

You can force only a regional preset:

```bash
osm3d build 123456789 --preset sweden
```

If `--country auto` is used, the selected regional preset remains authoritative.

## Rural and urban contexts

Architecture can differ between rural and town/city environments.

Choose explicitly with:

```bash
osm3d build 123456789 --context rural
```

or:

```bash
osm3d build 123456789 --context town_city
```

The default is:

```text
auto
```

## Output

A generated model directory contains assets such as:

```text
building.obj
building.mtl
metadata.json
wall.png
roof.png
foundation.png
window.png
window_frame.png
door.png
balcony.png
detail_masonry.png
detail_wood.png
detail_metal.png
```

The exact set may vary as the generator evolves.

`metadata.json` records information about the generated model, including resolved architectural style information and procedural settings.

## Style data

### Regional profiles

Regional architectural data is stored in:

```text
house_styles/
```

There are currently **24 regional profiles**.

See:

- `HOUSE_STYLES_DETAIL_SCHEMA.md`

### Country profiles

Country-specific architecture is stored in:

```text
country_styles/
```

The catalogue contains **249 ISO 3166-1 countries and territories**.

Country profiles inherit/refine their proper parent region and contain editable rural and town/city contexts.

See:

- `COUNTRY_STYLES_SCHEMA.md`

The style JSON files are intended to be editable, so architecture can be refined without rewriting the geometry generator.

## Testing

Install the development dependencies and run:

```bash
python -m pytest -q
```

## OpenStreetMap data

Building geometry and tags are fetched from **OpenStreetMap** at runtime.

OpenStreetMap data is © OpenStreetMap contributors and is available under the Open Data Commons Open Database License (ODbL).

See:

- https://www.openstreetmap.org/copyright
- `ATTRIBUTION.md`

## Project scope

OSM House Modeler is a **procedural visualization/model-generation tool**. It is not intended to reproduce a building exactly from its footprint alone.

OpenStreetMap commonly provides the footprint and some building tags, but not enough information to know every real-world facade detail. Windows, doors, roof details, balconies, materials, and other architectural features may therefore be inferred procedurally from:

- OSM tags
- building class
- footprint dimensions
- country
- region
- rural/urban context
- procedural seed

The goal is plausible regional architecture rather than survey-grade reconstruction.

## Repository layout

```text
osm-house-modeler/
├── country_styles/          # Country architecture profiles
├── house_styles/            # Regional architecture profiles
├── src/
│   └── osm_house_modeler/   # Main Python package
├── tests/                   # Test suite
├── ATTRIBUTION.md
├── COUNTRY_STYLES_SCHEMA.md
├── HOUSE_STYLES_DETAIL_SCHEMA.md
├── main.py                  # Convenient GUI entry point
├── pyproject.toml
└── requirements.txt
```

## Contributing

Contributions that improve geometry generation, architectural profiles, OpenStreetMap tag interpretation, texturing, or viewer compatibility are welcome.

When changing procedural style behavior, please keep results deterministic for a given seed where practical and add or update tests for geometry regressions.

## License

The project metadata declares the project under the **MIT License**.

Third-party data and referenced datasets retain their own licenses and attribution requirements. See `ATTRIBUTION.md` for additional information.
