from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) == 1:
        from .gui import main as gui_main
        return gui_main()
    from .cli import main as cli_main
    return cli_main()


raise SystemExit(main())
