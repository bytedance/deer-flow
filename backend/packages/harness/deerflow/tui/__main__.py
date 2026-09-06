"""Allow ``python -m deerflow.tui`` to launch the workbench."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
