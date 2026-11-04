"""Fixed application resources and worker commands in source and frozen builds."""
from pathlib import Path
import sys


WORKERS = {"capability": ("capability_worker.py", False),
           "skill": ("skill_worker.py", True), "needle": ("needle_worker.py", True)}


def resource_root():
    return Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


def worker_command(kind: str, *arguments: str) -> list[str]:
    """Only bundled, fixed workers are executable; never accept a module/path."""
    if kind not in WORKERS:
        raise ValueError("Unknown BEL worker")
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).with_name("BEL-worker.exe")
        if not executable.is_file():
            raise RuntimeError("BEL worker is missing; restore the complete verified application folder")
        return [str(executable), "--worker", kind, *arguments]
    name, isolated = WORKERS[kind]
    return [sys.executable, "-I", *(["-S"] if isolated else []),
            str(Path(__file__).with_name(name)), *arguments]


def dispatch_worker(argv):
    """Console worker entry only. Arguments are never interpreted as Python code."""
    import json
    if len(argv) < 2 or argv[0] != "--worker" or argv[1] not in WORKERS:
        return 2
    kind = argv[1]
    if kind == "needle":
        from .needle_worker import main
        return main(argv[2:])
    if len(argv) != 2:
        return 2
    if kind == "capability":
        from .capability_worker import main, failure_payload
        try:
            main()
            return 0
        except Exception as exc:
            print(json.dumps(failure_payload(exc)))
            return 1
    from .skill_worker import transform
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError("Payload limit")
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"text", "operations"}:
            raise ValueError("Invalid request")
        print(json.dumps({"ok": True, "result": transform(value["text"], value["operations"])}, ensure_ascii=True))
        return 0
    except (ValueError, TypeError, KeyError):
        print(json.dumps({"ok": False, "error": "Rejected declarative operation or resource limit"}))
        return 1
