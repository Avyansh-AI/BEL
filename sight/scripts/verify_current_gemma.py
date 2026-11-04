"""Read-only full blob verification of the approved official Gemma manifest."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sight_core.models import OFFICIAL_GEMMA, OFFICIAL_GEMMA_DIGEST
from sight_core.security import safe_file


def verify(directory):
    started = time.monotonic()
    # Ollama 0.40 uses manifests-v2. Preserve the older registry cache; it may
    # refer to a different digest and is not evidence about the active model.
    manifest_path = directory / 'manifests-v2/ollama.com/library/gemma4/e4b-it-qat'
    if not manifest_path.exists():
        manifest_path = directory / 'manifests/registry.ollama.ai/library/gemma4/e4b-it-qat'
    manifest = safe_file(manifest_path).read_bytes()
    if hashlib.sha256(manifest).hexdigest() != OFFICIAL_GEMMA_DIGEST:
        raise ValueError('Active manifest differs from the owner-approved model')
    content = json.loads(manifest)
    rows = []
    for layer in [content['config'], *content['layers']]:
        digest = layer['digest']
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
            raise ValueError('Invalid blob digest')
        blob = safe_file(directory / 'blobs' / digest.replace(':', '-'))
        with blob.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        rows.append({'sha256': actual, 'bytes': blob.stat().st_size,
                     'passed': actual == digest[7:] and blob.stat().st_size == layer['size']})
    return {'model': OFFICIAL_GEMMA, 'manifest_sha256': OFFICIAL_GEMMA_DIGEST, 'files': rows,
            'manifest_layout': manifest_path.relative_to(directory).as_posix(),
            'passed': all(row['passed'] for row in rows), 'seconds': round(time.monotonic() - started, 3),
            'completed_utc': datetime.now(timezone.utc).isoformat()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models-directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Preserve prior evidence; choose a new output')
    result = verify(args.models_directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'files': len(result['files']), 'seconds': result['seconds']}))
    raise SystemExit(0 if result['passed'] else 1)
