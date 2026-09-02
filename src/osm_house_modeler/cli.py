from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .builder import BUILDING_TYPE_OVERRIDES, INTERIOR_MODES, build_way


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="osm3d", description="Procedural 3D buildings from OpenStreetMap ways")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("gui", help="Open the desktop GUI")

    build = sub.add_parser("build", help="Generate a textured OBJ from an OSM way")
    build.add_argument("way_id", type=int)
    build.add_argument("-o", "--output", type=Path, default=Path("osm3d-output"))
    build.add_argument("--preset", default="auto", help="Local house_styles region identifier, or auto")
    build.add_argument(
        "--country", default="auto",
        help="Country preset as ISO code/name/profile identifier, or auto; a forced country automatically uses its parent region",
    )
    build.add_argument("--context", choices=["auto", "rural", "town_city"], default="auto")
    build.add_argument(
        "--building-type",
        choices=BUILDING_TYPE_OVERRIDES,
        default="auto",
        help="Force the way to render as a specific building class instead of using its OSM building tag",
    )
    build.add_argument(
        "--interior-mode",
        choices=INTERIOR_MODES,
        default="exterior_only",
        help="Exterior-only shell (default) or a simple hollow interior with cut window/door openings",
    )
    build.add_argument("--timeout", type=float, default=20.0)
    build.add_argument("--seed", default="0", help="Procedural seed for regional style/texture variation")
    build.add_argument("--foundation-depth", type=float, default=None, help="Below-grade foundation depth in metres; omit to use the regional house_styles default")
    build.add_argument("--no-windows", action="store_true", help="Do not add procedural windows")
    build.add_argument("--no-doors", action="store_true", help="Do not add a procedural entrance door")
    build.add_argument("--no-details", action="store_true", help="Do not add stairs, porches, chimneys, balconies, gutters or downspouts")
    build.add_argument("--view", action="store_true", help="Open the generated model in the Python viewer")

    view = sub.add_parser("view", help="Open an OBJ in the Python model viewer")
    view.add_argument("model", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "gui":
            from .gui import main as gui_main
            return gui_main()
        if args.command == "build":
            obj = build_way(
                args.way_id, args.output, preset=args.preset, country_preset=args.country, context=args.context, timeout=args.timeout,
                add_windows=not args.no_windows, add_doors=not args.no_doors,
                add_details=not args.no_details,
                seed=args.seed, foundation_depth=args.foundation_depth,
                building_type=args.building_type,
                interior_mode=args.interior_mode,
            )
            print(obj)
            if args.view:
                from .viewer import view_model
                view_model(obj)
        elif args.command == "view":
            from .viewer import view_model
            view_model(args.model)
    except (RuntimeError, ValueError, FileNotFoundError, OSError) as exc:
        print(f"osm3d: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
