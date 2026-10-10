"""Forge Desktop launcher — standalone entry point for forge-gui."""

import sys


def main() -> None:
    """Launch the Forge Desktop application."""
    try:
        from forge.desktop import launch
    except ImportError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    launch()


if __name__ == "__main__":
    main()
