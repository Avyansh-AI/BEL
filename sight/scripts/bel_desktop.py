"""Windowed packaged entry point; fixed workers use BEL-worker.exe instead."""
import os
from pathlib import Path
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# pythonw/PyInstaller windowed has no stdio. Libraries may still write diagnostics.
for name, mode in (("stdin", "r"), ("stdout", "w"), ("stderr", "w")):
    if getattr(sys, name) is None:
        setattr(sys, name, open(os.devnull, mode, encoding="utf-8"))

from sight_core.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
