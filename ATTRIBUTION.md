# Data-source attribution

OpenStreetMap building geometry and tags are fetched at runtime from OpenStreetMap.

The project's local `house_styles/` catalogue uses a JSON structure compatible with the regional house-style format from:

- CWR-Worldgen `src/cwr_worldgen/house_styles`
- https://github.com/svamp3717/CWR-Worldgen/tree/main/src/cwr_worldgen/house_styles

OSM House Modeler now keeps its own editable regional JSON catalogue locally. It does not download or synchronize style files at runtime.

The utility-building classification behavior (shed/garage outbuildings, barn/agricultural fallbacks, warehouse/industrial classification, and garage-size heuristics) was designed with reference to CWR-Worldgen's `procedural_buildings.py` and its milestone tests. The implementation in this project is independent Python code adapted to this OBJ generator.

The bundled `country_styles/` matching geometry was generated from the country data available through the `countryinfo` Python package (MIT License, https://github.com/porimol/countryinfo). The low-resolution geometry is used only to choose an offline country architecture profile; it is not intended for surveying, legal boundaries, or navigation.

Country architecture JSON files are procedural style defaults. Forty-six profiles currently contain additional hand-authored national tuning; the remaining ISO entries carry a fully expanded copy of their detailed parent-region context so they are immediately editable at country level.

