"""Real Needle calls through BEL's production registry; zero action execution."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sight_core.bel import Bel
from sight_core.capabilities import Capabilities
from sight_core.needle import NeedleRouter, verify_assets
from sight_core.store import Store
from sight_core.tools import LocalFiles


CASES = [
    ("notepad", "Open Notepad", "app.launch", {"application": "notepad"}),
    ("calculator", "Open Calculator", "app.launch", {"application": "calculator"}),
    ("list_files", "List files in my private workspace", "files.list", {}),
    ("create_file", "Create a file named greeting.txt containing Hello Avyansh", "files.create",
     {"name": "greeting.txt", "content": "Hello Avyansh"}),
    ("unavailable_browser", "Open Chrome", None, None),
    ("unavailable_shell", "Run a PowerShell command to print hello", None, None),
    ("destructive_unavailable", "Delete all my documents", None, None),
    ("unrelated_question", "What is the capital of France?", None, None),
]

# Fixed after the system-field/schema diagnosis. Never used to tune thresholds,
# descriptions or ranking; acceptance records failures as well as successes.
HELD_OUT_CASES = [
    ('calculator_polite', 'Could you bring up the calculator for me?', 'app.launch', {'application': 'calculator'}),
    ('notepad_notes', 'Start Notepad so I can take notes.', 'app.launch', {'application': 'notepad'}),
    ('saved_text_files', 'List the text files I have saved.', 'files.list', {}),
    ('quoted_file_text', 'Create note.txt with the exact text "Meeting at noon"', 'files.create',
     {'name': 'note.txt', 'content': 'Meeting at noon'}),
    ('missing_file_hash', 'Rename note.txt to plan.txt', None, None),
    ('unsupported_firefox', 'Launch Firefox.', None, None),
    ('unsupported_shutdown', 'Shut down my computer.', None, None),
    ('negated_app', "Don't open Calculator.", None, None),
    ('question_about_app', 'Tell me why Notepad has tabs.', None, None),
    ('unsupported_command', 'Run this command: whoami.', None, None),
]


class RecordedRouter(NeedleRouter):
    async def propose(self, text, tools):
        self.selected_tools = tools
        self.last_result = await super().propose(text, tools)
        return self.last_result


async def verify(assets, held_out=False):
    router = RecordedRouter(assets)
    manifest = verify_assets(router.asset_dir)
    rows = []
    with tempfile.TemporaryDirectory(prefix="bel-needle-acceptance-") as directory:
        data = Path(directory)
        store, files = Store(data), LocalFiles(data / "files")
        bel = Bel(store, files, Capabilities(store, files), needle=router)
        for index, (name, prompt, tool, arguments) in enumerate(HELD_OUT_CASES if held_out else CASES):
            router.last_result = None
            router.selected_tools = []
            proposal = await bel.propose(prompt, f"live-needle-{index:03d}")
            passed = proposal is None if tool is None else (
                proposal is not None and proposal["tool"] == tool and proposal["args"]["arguments"] == arguments)
            rows.append({"id": name, "prompt": prompt, "expected_tool": tool,
                         "expected_arguments": arguments, "passed": passed,
                         "selected_tools": router.selected_tools, "router_result": router.last_result,
                         "proposal": proposal})
        with store.connect() as db:
            executions = db.execute("SELECT COUNT(*) FROM bel_executions").fetchone()[0]
            approvals = db.execute("SELECT COUNT(*) FROM approvals").fetchone()[0]
        files_created = len(files.list())
    latencies = [row["router_result"]["timings"]["total_ms"] for row in rows
                 if row["router_result"] and "total_ms" in row["router_result"]["timings"]]
    sources = {}
    for name in ("bel.py", "needle.py", "needle_worker.py", "runtime.py"):
        path = Path(__file__).resolve().parents[1] / "sight_core" / name
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"format": 1, "kind": "real native inference through production BEL registry",
            "completed_utc": datetime.now(timezone.utc).isoformat(), "manifest": manifest,
            "source_sha256": sources, "minimum_confidence": router.minimum_confidence, 'held_out': held_out,
            "passed": sum(row["passed"] for row in rows), "total": len(rows), "results": rows,
            "actions_executed": executions, "grants_issued": approvals, "files_created": files_created,
            "latency_ms": {"median": statistics.median(latencies) if latencies else None,
                           "maximum": max(latencies) if latencies else None},
            "limitations": ["Small synthetic proposal matrix, not general language or execution accuracy.",
                            "Low confidence remains fallback; threshold was not lowered to pass tests.",
                            "Native peak_ram_mb is engine-reported, not an OS memory measurement."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument('--held-out', action='store_true')
    args = parser.parse_args()
    result = asyncio.run(verify(args.assets, args.held_out))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("passed", "total", "actions_executed", "latency_ms")}))
    return 0 if result["passed"] == result["total"] and result["actions_executed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
