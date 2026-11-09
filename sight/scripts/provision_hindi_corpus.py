"""Explicit bounded Hindi evaluation subset; original human labels, not LLM targets."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import time

import provision_speech_corpus as shared

DATASET = 'adalat-ai/fleurs-ro'
REVISION = 'b952d79e607b5b1bf4d32e3b0ab394b838345439'


def provision(destination, english_corpus, eval_deps):
    if (destination / 'manifest.json').exists():
        raise ValueError('Completed corpus is immutable')
    # Share the owner's 50 MB limit with the already completed English corpus.
    english = json.loads((english_corpus / 'manifest.json').read_text(encoding='utf-8'))
    charged = json.loads((english_corpus / 'download-ledger.json').read_text(encoding='utf-8'))['charged_bytes']
    if charged != english['audio_budget_charged_bytes'] or not 0 < charged < 50_000_000:
        raise ValueError('English download accounting must be complete and consistent')
    shared.LIMIT = 50_000_000 - charged
    shared.DATASET = DATASET
    sys.path.insert(0, str(eval_deps.resolve(strict=True)))
    import soundfile
    destination.mkdir(parents=True, exist_ok=True)
    budget = shared.AudioBudget(destination)
    selection = destination / 'selection.json'
    if selection.exists():
        rows = json.loads(selection.read_text(encoding='utf-8'))
    else:
        candidates = []
        for offset in range(0, 418, 100):
            page = shared.metadata('hi', offset, min(100, 418 - offset), cache=destination / 'metadata')
            for item in page['rows']:
                row = item['row']
                if 5 <= row['duration'] <= 20 and 10 <= len(row['source_transcription'].split()) <= 60:
                    candidates.append({'row_idx': item['row_idx'], 'reference': row['source_transcription'],
                                       'duration': row['duration']})
        rows = sorted(candidates, key=lambda row: hashlib.sha256(f"BEL-preview2-Hindi-v1/{row['row_idx']}".encode()).hexdigest())[:24]
        if len(rows) != 24:
            raise ValueError('Insufficient bounded Hindi samples')
        shared.write_json(selection, rows)
    manifest = {'format': 1, 'corpus': 'BEL-Preview2-FLEURS-Hindi-v1', 'kind': 'Recorded human read speech',
                'dataset': DATASET, 'revision': REVISION, 'license': 'CC-BY-4.0',
                'source': f'https://huggingface.co/datasets/{DATASET}/tree/{REVISION}',
                'attribution': 'Conneau et al., FLEURS, SLT 2022; adalat-ai FLEURS-RO mirror.',
                'reference_field': 'source_transcription (upstream normalized human FLEURS label); LLM-curated transcription unused',
                'selection': '24 SHA-256 ordered row indices from 418 test rows, duration 5..20s and 10..60 source words, before any inference.',
                'speakers': None, 'limitations': ['Speaker identities are not supplied by this mirror.',
                    'Small read-speech subset does not qualify owner accents, microphone quality or code-switching.',
                    'Normalized source labels cannot qualify punctuation or numeral formatting.'], 'clips': []}
    for row in rows:
        item = shared.metadata('hi', row['row_idx'], 1, cache=destination / 'metadata')['rows'][0]['row']
        if item['source_transcription'] != row['reference']:
            raise ValueError('Frozen Hindi label changed')
        url = item['audio'][0]['src']
        if f'/{REVISION}/' not in url:
            raise ValueError('Hindi corpus revision changed')
        identifier = 'hi-' + str(row['row_idx'])
        raw = budget.read_or_fetch(identifier + '.flac', url)
        samples, rate = soundfile.read(io.BytesIO(raw), dtype='int16', always_2d=True)
        if rate != 16000 or samples.shape[1] != 1 or not .1 <= len(samples) / rate <= 20:
            raise ValueError('Unexpected Hindi waveform; selection must be reviewed')
        wav = shared.wav_bytes(samples[:, 0], rate)
        path = destination / (identifier + '.wav')
        if path.exists() and path.read_bytes() != wav:
            raise ValueError('Retained Hindi WAV changed')
        if not path.exists():
            path.write_bytes(wav)
        manifest['clips'].append({'id': identifier, 'split': 'hi_in', 'locale': 'hi-IN',
            'reference': row['reference'], 'path': path.name, 'seconds': len(samples) / rate,
            'source_audio_sha256': hashlib.sha256(raw).hexdigest(), 'wav_sha256': hashlib.sha256(wav).hexdigest(),
            'source_url': url.split('?', 1)[0]})
        print(json.dumps({'clips': len(manifest['clips']), 'total_approved_audio_bytes_charged': charged + budget.data['charged_bytes']}), flush=True)
        time.sleep(.8)
    manifest.update(reference_words=sum(len(r['reference'].split()) for r in rows),
                    seconds=sum(r['seconds'] for r in manifest['clips']),
                    audio_budget_charged_bytes=budget.data['charged_bytes'],
                    combined_audio_budget_charged_bytes=charged + budget.data['charged_bytes'],
                    completed_utc=datetime.now(timezone.utc).isoformat())
    with (destination / 'manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--english-corpus', required=True, type=Path)
    parser.add_argument('--eval-deps', required=True, type=Path)
    args = parser.parse_args()
    if not args.download:
        parser.error('Explicit --download consent is required')
    provision(args.destination.resolve(), args.english_corpus.resolve(), args.eval_deps)
