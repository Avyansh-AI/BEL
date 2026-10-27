"""Behavioral regressions for the October 2026 dependency security repairs."""
from io import BytesIO
from pathlib import Path
import subprocess
import ssl
import sys

import httpx
from PIL import Image


def test_httpx_trust_store_excludes_compromised_emsign_root():
    # GHSA-6q48-6c7w-9gw2: provider TLS must not trust this compromised chain.
    context = httpx.create_ssl_context(trust_env=False)
    names = {
        value
        for certificate in context.get_ca_certs()
        for rdn in certificate["subject"]
        for name, value in rdn
        if name == "commonName"
    }
    assert len(names) > 50, "An empty trust store is not a security repair"
    assert "emSign ECC Root CA - G3" not in names


def test_installer_trust_store_excludes_compromised_emsign_root():
    # pip vendors its own CA bundle; updating top-level Certifi does not fix it.
    from pip._vendor import certifi

    context = ssl.create_default_context(cafile=certifi.where())
    names = {value for certificate in context.get_ca_certs()
             for rdn in certificate["subject"] for name, value in rdn if name == "commonName"}
    assert len(names) > 50
    assert "emSign ECC Root CA - G3" not in names


def test_malformed_xbm_is_rejected_without_cpu_stall(tmp_path):
    # GHSA-xgh8-jp6q-p5x8: overlapping header whitespace stalled Image.open.
    # A child-process deadline bounds the regression even with the old wheel.
    header = b"".join(b"#define" + b" " * 60 + suffix + b" 1\r"
                      for suffix in (b"_width", b"_height", b"_x_hot", b"_y_hot"))
    sample = (header + b"\r" * 59 + b"_bits").ljust(512, b"A")
    path = tmp_path / "malformed.xbm"
    path.write_bytes(sample)
    child = """
import sys
from PIL import Image, UnidentifiedImageError
try:
    Image.open(sys.argv[1])
except UnidentifiedImageError:
    raise SystemExit(0)
raise SystemExit('Malformed image was accepted')
"""
    result = subprocess.run([sys.executable, "-B", "-c", child, str(path)],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    # Keep the valid format functional, not merely disabled by the upgrade.
    output = BytesIO()
    Image.new("1", (8, 8), 1).save(output, format="XBM")
    output.seek(0)
    with Image.open(output) as reopened:
        assert reopened.size == (8, 8)
        assert reopened.getpixel((0, 0)) == 255
