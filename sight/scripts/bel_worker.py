"""Console-subsystem worker, always spawned with CREATE_NO_WINDOW by BEL."""
from pathlib import Path
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sight_core.runtime import dispatch_worker

if __name__ == "__main__":
    raise SystemExit(dispatch_worker(sys.argv[1:]))
