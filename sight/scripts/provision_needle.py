"""Explicitly provision pinned Apache-2.0 Needle assets; never installs packages."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import os
import sys
import tempfile
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sight_core import needle


def download(relative, expected_size, digest):
    request = urllib.request.Request(needle.ASSET_BASE + relative, headers={"User-Agent": "BEL-asset-provisioner/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        if not response.geturl().startswith("https://"):
            raise ValueError("Asset download must remain HTTPS")
        data = response.read(expected_size + 1)
    if len(data) != expected_size or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Official asset digest mismatch; nothing loaded")
    return data


def provision(destination):
    destination = Path(destination).absolute()
    needle._plain_path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if (destination / "manifest.json").exists():
        return needle.verify_assets(destination)
    wanted = [*needle.ASSETS, "manifest.json"]
    if any((destination / name).exists() for name in wanted):
        raise ValueError("Partial assets exist; select a new empty destination for a clean verified provision")
    with tempfile.TemporaryDirectory(prefix=".needle-provision-", dir=destination) as staging:
        stage = Path(staging)
        for name in ("needle3.cact", "LICENSE"):
            (stage / name).write_bytes(download(name, *needle.ASSETS[name]))
        wheel = download(needle.ENGINE_WHEEL, needle.ENGINE_WHEEL_SIZE, needle.ENGINE_WHEEL_SHA256)
        with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
            member = archive.getinfo("needle/libneedle3.dll")
            if member.file_size != needle.ASSETS["libneedle3.dll"][0]:
                raise ValueError("Unexpected engine library size")
            (stage / "libneedle3.dll").write_bytes(archive.read(member))
        manifest = needle.expected_manifest()
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        needle.verify_assets(stage)
        # Commit manifest last: interrupted provisioning can never appear valid.
        for name in wanted:
            os.replace(stage / name, destination / name)
    return needle.verify_assets(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=needle.default_asset_dir())
    args = parser.parse_args()
    manifest = provision(args.destination)
    print(json.dumps({"status": "verified", "destination": str(args.destination.absolute()), **manifest}, indent=2))


if __name__ == "__main__":
    main()
