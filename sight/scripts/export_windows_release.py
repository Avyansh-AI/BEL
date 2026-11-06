"""Export an independently checked BEL one-folder build without changing the installed files."""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import marshal
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile
import zipfile

from PyInstaller.archive.readers import CArchiveReader
from verify_frozen_source import verify

ROOT = Path(__file__).resolve().parents[2]
FOLDER = "BEL-0.4.2-preview1-Windows-x64"
NOTICE_PREFIXES = ("license", "licence", "copying", "copyright", "notice", "thirdpartynotice")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def relative(raw):
    parts = raw.replace("\\", "/").split("/")
    if any(part in ("", ".", "..") or ":" in part for part in parts):
        raise ValueError("Unsafe archive or manifest path")
    return PurePosixPath(*parts).as_posix()


def verified_build(directory):
    root = directory / "BEL"
    manifest_path = directory / "BEL-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if (manifest["format"], manifest["product"], manifest["platform"]) != (1, "BEL", "Windows x64"):
        raise ValueError("Unexpected build manifest format")
    for row in manifest["sources"]:
        if digest(ROOT / relative(row["path"])) != row["sha256"]:
            raise ValueError("Current source differs from the build manifest: " + row["path"])
    files = {}
    for row in manifest["files"]:
        name = relative(row["path"])
        if name in files or name.casefold() in (entry.casefold() for entry in files):
            raise ValueError("Duplicate manifest name")
        path = root / name
        if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
            raise ValueError("Build file hash or size mismatch: " + name)
        parts = {part.casefold() for part in PurePosixPath(name).parts}
        if parts & {"owner-data", "test-data", ".env", ".git", "browser-token", "service.lock"} or path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".log"}:
            raise ValueError("Private runtime path in build")
        files[name] = path
    members = list(root.rglob("*"))
    if any(p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT for p in [root, *members]):
        raise ValueError("Links or reparse points in build")
    if set(files) != {p.relative_to(root).as_posix() for p in members if p.is_file()}:
        raise ValueError("Build and manifest contain different files")
    modules = {}
    packages = set()
    for executable, entry in (("BEL.exe", "bel_desktop"), ("BEL-worker.exe", "bel_worker")):
        modules[executable] = verify(files[executable], ROOT / "sight")
        archive = CArchiveReader(str(files[executable]))
        actual = marshal.loads(archive.extract(entry))
        expected = compile((ROOT / "sight/scripts" / (entry + ".py")).read_bytes(), actual.co_filename, "exec", dont_inherit=True, optimize=0)
        if actual != expected:
            raise ValueError("Packaged entry point differs: " + entry)
        packages.update(key.split(".")[0] for key in archive.open_embedded_archive("PYZ.pyz").toc)
    return files, packages, {"source_files": len(manifest["sources"]), "payload_files": len(files),
                             "payload_bytes": sum(row["bytes"] for row in manifest["files"]),
                             "matched_modules": modules, "matched_entry_points": 2,
                             "build_manifest_sha256": digest(manifest_path)}


def notices(packages):
    files = {"licenses/BEL-LICENSE.txt": ROOT / "LICENSE",
             "licenses/CPython-LICENSE.txt": Path(sys.base_prefix) / "LICENSE.txt"}
    inventory = {}
    distributions = {name for pkg, names in metadata.packages_distributions().items() if pkg in packages for name in names}
    distributions.update(("PyInstaller", "pystray"))
    for name in sorted(distributions):
        dist = metadata.distribution(name)
        found = []
        for entry in dist.files or ():
            parts = entry.parts
            if ".." in parts or not entry.name.casefold().startswith(NOTICE_PREFIXES):
                continue
            path = Path(dist.locate_file(entry))
            if path.is_file():
                dest = "licenses/python/" + dist.metadata["Name"] + "/" + relative(str(entry))
                files[dest] = path
                found.append(dest)
        license_name = dist.metadata.get("License-Expression") or dist.metadata.get("License")
        inventory[name] = {"version": dist.version, "license_metadata": license_name,
                           "homepage": dist.metadata.get("Home-page"), "notices": sorted(found)}

    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    for relative_path, info in lock["packages"].items():
        if not relative_path or info.get("dev"):
            continue
        path = ROOT / "frontend" / relative(relative_path)
        pkg = json.loads((path / "package.json").read_text(encoding="utf-8"))
        if pkg["version"] != info["version"]:
            raise ValueError("Installed frontend package differs from lock: " + pkg["name"])
        found = []
        for entry in sorted(path.iterdir()):
            if entry.is_file() and entry.name.casefold().startswith(NOTICE_PREFIXES):
                dest = "licenses/npm/" + relative(relative_path) + "/" + entry.name
                files[dest] = entry
                found.append(dest)
        inventory["npm:" + pkg["name"]] = {"version": pkg["version"], "license_metadata": pkg.get("license"), "notices": found}
    return files, inventory


README = """BEL 0.4.2 development preview 1 for Windows x64

Extract this entire directory to a writable location and open BEL.exe. Keep
BEL-worker.exe and _internal alongside it. The system tray restores the
interface or exits the app. Auto-start requires an explicit opt-in.

This partial build supports reviewed local tools, guarded private-file undo,
the supplied orb UI and Windows speech-to-WAV. Routine Needle proposals can
fall below the confidence floor. Settings > Tools and undo offers manual review.
Optional local Windows dictation is disabled by default. Launch with
--local-dictation, then enable Microphone consent in Settings and hold to talk.
The operating system/browser must also grant microphone access. Recognized text
is placed in an editable draft for review; it never sends or runs tools itself.
Synthetic recordings passed the local integration checks, but speech accuracy
is limited. Physical microphone quality and native permission prompts remain
unverified. Only installed recognition languages appear. A trained BEL wake
model remains unavailable. Closing or hiding the window stops dictation capture.
This preview has not passed a fresh hour-long stability test; the earlier
0.4.1 soak does not qualify these changes. Production readiness remains PARTIAL.

Requires Microsoft Edge WebView2. Gemma inference uses a separately installed
local Ollama service and the owner's selected gemma4:e4b-it-qat model. The
offline browser tool requires the matching Playwright Chromium cache. The ZIP
contains the pinned Needle model and engine. Desktop memory and settings
use the current user's data directory, outside this folder. For previous
checkout data, pass --data-directory with that existing directory.

BEL-manifest.json records SHA-256 for the original application payload.
Archive-files.json records SHA-256 for the payload and added handoff files.
THIRD-PARTY.json inventories Python and frontend distributions identified
in the build, their installed license metadata and accompanying notice texts.
Additional notices ship with the components under _internal. The project
license is licenses/BEL-LICENSE.txt. Binary/code signing and clean-account
installation remain unqualified. See the source repository's BEL setup and
implementation reports for migration, rollback and qualification details.
"""


def export(directory, output):
    files, packages, checks = verified_build(directory)
    extra_files, inventory = notices(packages)
    files.update(extra_files)
    files["BEL-manifest.json"] = directory / "BEL-manifest.json"
    output.mkdir(parents=True, exist_ok=True)
    destination = output / (FOLDER + ".zip")
    checksum = destination.with_suffix(".zip.sha256")
    if destination.exists() or checksum.exists():
        raise ValueError("Export already exists. Choose a new directory.")
    content = {"READ-ME.txt": README.encode(), "THIRD-PARTY.json": json.dumps(inventory, indent=2).encode()}
    hashes = {name: digest(path) for name, path in files.items()}
    hashes.update({name: hashlib.sha256(value).hexdigest() for name, value in content.items()})
    content["Archive-files.json"] = json.dumps({"format": 1, "files": hashes}, indent=2, sort_keys=True).encode()
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        candidate = Path(tmp) / destination.name
        with zipfile.ZipFile(candidate, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, path in sorted(files.items()):
                archive.write(path, FOLDER + "/" + name)
            for name, value in sorted(content.items()):
                archive.writestr(FOLDER + "/" + name, value)
        with zipfile.ZipFile(candidate) as archive:
            if len(archive.namelist()) != len(hashes) + 1:
                raise ValueError("Unexpected ZIP membership")
            packed_manifest = archive.read(FOLDER + "/BEL-manifest.json")
            if hashlib.sha256(packed_manifest).hexdigest() != checks["build_manifest_sha256"]:
                raise ValueError("Build manifest changed during export")
            for row in json.loads(packed_manifest.decode("utf-8-sig"))["files"]:
                if hashes[relative(row["path"])] != row["sha256"]:
                    raise ValueError("Payload changed during export: " + row["path"])
            for name, expected in hashes.items():
                with archive.open(FOLDER + "/" + name) as member:
                    if hashlib.file_digest(member, "sha256").hexdigest() != expected:
                        raise ValueError("ZIP member mismatch: " + name)
            if archive.read(FOLDER + "/Archive-files.json") != content["Archive-files.json"]:
                raise ValueError("Unexpected inventory")
        archive_hash = digest(candidate)
        candidate.rename(destination)  # Windows rename refuses to replace an existing destination.
    with checksum.open("x", encoding="ascii") as stream:
        stream.write(archive_hash + "  " + destination.name + "\n")
    checks.update(zip_files=len(hashes) + 1, zip_bytes=destination.stat().st_size, zip_sha256=archive_hash,
                  distribution_notices=len(inventory), zip=str(destination))
    return checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.build.resolve(strict=True), args.output_directory.resolve()), indent=2))
