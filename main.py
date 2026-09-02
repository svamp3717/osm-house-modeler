"""Launch the OSM House Modeler desktop GUI.

Usage:
    python main.py

The project uses a src/ layout.  Adding it to sys.path here keeps the source
checkout directly runnable without requiring an editable package install first.
"""
from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from osm_house_modeler.gui import main as gui_main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(gui_main())
