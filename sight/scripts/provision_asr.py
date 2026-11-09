"""Explicit, pinned offline ASR installation; never called by recognition requests."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sight_core.asr_assets import (MODELS, MODEL_REVISION, RUNTIME_ARCHIVE, RUNTIME_FILES,
                                   RUNTIME_URL, default_directory, manifest, verify_file)
from sight_core.security import reject_links, private_directory


def fetch(url, target, expected):
    """Download only an explicitly selected pinned artifact, with a hard byte cap."""
    if target.exists():
        verify_file(target, expected)
        return
    partial = target.with_suffix(target.suffix + '.partial')
    if partial.exists():
        raise ValueError('Incomplete download exists; inspect it before retrying')
    count = 0
    with urllib.request.urlopen(url, timeout=60) as response, partial.open('xb') as output:
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            if count > expected[0]:
                raise ValueError('Download exceeded pinned size')
            output.write(chunk)
    verify_file(partial, expected)
    partial.rename(target)


def install(source, destination, models):
    metadata = manifest(models)
    source, destination = reject_links(source), reject_links(destination)
    if destination.exists():
        raise ValueError('Destination already exists; keep the verified installation or select a new directory')
    verify_file(source / 'whisper-bin-x64.zip', RUNTIME_ARCHIVE)
    for model in models:
        verify_file(source / ('ggml-' + model + '.bin'), MODELS[model])
    # A caller may choose an existing shared parent. Do not replace its ACL or
    # inheritance policy; only the newly created staging/install tree is ours.
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.asr-install-', dir=destination.parent))
    # Leave failed staging for diagnosis; it has no final installation identity.
    private_directory(staging)
    (staging / 'runtime').mkdir()
    (staging / 'models').mkdir()
    with zipfile.ZipFile(source / 'whisper-bin-x64.zip') as archive:
        names = archive.namelist()
        for name, expected in RUNTIME_FILES.items():
            member = 'Release/' + name
            if names.count(member) != 1 or archive.getinfo(member).file_size != expected[0]:
                raise ValueError('Unexpected pinned runtime archive')
            target = staging / 'runtime' / name
            with archive.open(member) as incoming, target.open('xb') as output:
                shutil.copyfileobj(incoming, output, length=1024 * 1024)
            verify_file(target, expected)
    for model in models:
        name = 'ggml-' + model + '.bin'
        shutil.copyfile(source / name, staging / 'models' / name)
        verify_file(staging / 'models' / name, MODELS[model])
    notices = ROOT / 'third_party/asr'
    for name in ('whisper.cpp-LICENSE.txt', 'Whisper-LICENSE.txt'):
        shutil.copyfile(notices / name, staging / name)
    (staging / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    staging.rename(destination)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-directory', type=Path, required=True, help='Private cache for verified downloads or existing offline files')
    parser.add_argument('--destination', type=Path, default=default_directory())
    parser.add_argument('--model', choices=sorted(MODELS), action='append', required=True)
    parser.add_argument('--download', action='store_true', help='Explicit consent to download only the pinned selected files; no recording upload')
    args = parser.parse_args()
    manifest(args.model)
    source = reject_links(args.source_directory)
    if source.exists():
        if not source.is_dir():
            raise ValueError('Source cache must be a directory')
    else:
        source.mkdir(parents=True, exist_ok=False)
        private_directory(source)
    if args.download:
        fetch(RUNTIME_URL, source / 'whisper-bin-x64.zip', RUNTIME_ARCHIVE)
        for model in args.model:
            name = 'ggml-' + model + '.bin'
            fetch(f'https://huggingface.co/ggerganov/whisper.cpp/resolve/{MODEL_REVISION}/{name}', source / name, MODELS[model])
    metadata = install(source, args.destination, args.model)
    print(json.dumps({'installed': str(args.destination.absolute()), 'models': metadata['models'],
                      'device': 'cpu', 'runtime_prerelease': True, 'microphone_enabled': False}))


if __name__ == '__main__':
    main()
