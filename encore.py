#!/usr/bin/env python3
"""
Launcher for Encore — Karaoke Studio.

``karaoke_app.main`` uses relative imports, which only resolve when it is run as
part of its package. ``python -m karaoke_app.main`` does that; a frozen build
does not, because PyInstaller executes the entry script as ``__main__`` with no
package context. This file is that entry point: it imports the package the
normal way and calls into it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from karaoke_app.main import main

if __name__ == "__main__":
    sys.exit(main())
