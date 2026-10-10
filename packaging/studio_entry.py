"""Entry point of the Studio desktop bundles (PyInstaller): the same as python -m MaestroLibrary.studio."""
import sys

from MaestroLibrary.studio import main

if __name__ == "__main__":
    sys.exit(main())
