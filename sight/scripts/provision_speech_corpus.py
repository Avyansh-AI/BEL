"""Opt-in, byte-budgeted provisioning of licensed recorded speech for evaluation.

Only downloads when --download is explicitly present. Files belong in a private
cache, never in a release. Install requirements-speech-eval.lock into --eval-deps
separately; this script never installs packages or executes remote dataset code.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import wave

DATASET = 'openslr/librispeech_asr'
REVISION = '71cacbfb7e2354c4226d01e70d77d5fca3d04ba1'
ROOT = Path(__file__).resolve().parents[2]
LIMIT = 50_000_000


def fetch(url, maximum, *, attempts=5):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'huggingface.co', 'datasets-server.huggingface.co'}:
        raise ValueError('Unexpected corpus host')
    for attempt in range(attempts):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'BEL-offline-speech-evaluation/1'}), timeout=40) as response:
                result = response.read(maximum + 1)
                if len(result) > maximum:
                    raise ValueError('Corpus download byte limit exceeded')
                return result
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise
            delay = exc.headers.get('Retry-After', '')
            time.sleep(min(30, max(5, int(delay))) if delay.isdigit() else min(30, 5 * 2 ** attempt))
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(1 + attempt)


def metadata(config, offset=0, count=100, cache=None):
    target = cache / f'{config}-{offset}-{count}.json' if cache else None
    if target and target.exists():
        return json.loads(target.read_text(encoding='utf-8'))
    url = 'https://datasets-server.huggingface.co/rows?' + urlencode({
        'dataset': DATASET, 'config': config, 'split': 'test', 'offset': offset, 'length': count})
    result = json.loads(fetch(url, 2_000_000))
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result), encoding='utf-8')
        time.sleep(.8)
    return result


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


class AudioBudget:
    """Persist a reservation before network I/O; failed/uncertain transfers count.

    Successful downloads release unused reserved bytes. A crash retains the full
    reservation, so resumption can never silently reset the approved byte cap.
    """
    def __init__(self, destination):
        self.destination = destination
        self.path = destination / 'download-ledger.json'
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
        else:
            # Adopt the four pre-ledger files from the interrupted v1 run. The
            # retained log records 838251 bytes, exactly their aggregate size.
            previous = sorted(destination.glob('*.flac'))
            self.data = {'format': 1, 'limit_bytes': LIMIT, 'charged_bytes': sum(p.stat().st_size for p in previous),
                         'files': {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                                           'provenance': 'Retained pre-ledger download; source labels revalidated'} for p in previous},
                         'reservations': [], 'failed_transfer_reserved_bytes': 0}
            write_json(self.path, self.data)
        if self.data.get('format') != 1 or self.data.get('limit_bytes') != LIMIT:
            raise ValueError('Unsupported download ledger')
        if not 0 <= self.data['charged_bytes'] <= LIMIT:
            raise ValueError('Invalid download budget')

    def read_or_fetch(self, name, url):
        target = self.destination / name
        if target.exists():
            raw = target.read_bytes()
            known = self.data['files'].get(name)
            if not known or len(raw) != known['bytes'] or hashlib.sha256(raw).hexdigest() != known['sha256']:
                raise ValueError('Retained corpus download changed')
            return raw
        maximum = min(2_000_000, LIMIT - self.data['charged_bytes'])
        if maximum < 1:
            raise ValueError('Approved corpus budget exhausted')
        self.data['charged_bytes'] += maximum
        self.data['reservations'].append({'file': name, 'bytes': maximum})
        write_json(self.path, self.data)
        try:
            # Retry only metadata. Uncertain/partial audio transfers retain their
            # full reservation and require a deliberate resume, never a reset.
            raw = fetch(url, maximum, attempts=1)
        except BaseException:
            self.data['failed_transfer_reserved_bytes'] += maximum
            write_json(self.path, self.data)
            raise
        temporary = target.with_suffix('.flac.part')
        temporary.write_bytes(raw)
        self.data['files'][name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        self.data['charged_bytes'] -= maximum - len(raw)
        self.data['reservations'].pop()
        # Persist before rename: a crash here conservatively charges a retry.
        write_json(self.path, self.data)
        temporary.replace(target)
        return raw


def selection_key(row):
    return hashlib.sha256(('BEL-preview2-corpus-v1/' + row['id']).encode()).hexdigest()


def wav_bytes(samples, rate):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setparams((1, 2, rate, len(samples), 'NONE', 'not compressed'))
        audio.writeframes(samples.astype('<i2', copy=False).tobytes())
    return buffer.getvalue()


def provision(destination, eval_deps, count):
    if (destination / 'manifest.json').exists():
        raise ValueError('Completed corpus manifests are immutable; no downloads performed')
    if not 1 <= count <= 50:
        raise ValueError('Choose 1..50 examples per split')
    sys.path.insert(0, str(eval_deps.resolve(strict=True)))
    import soundfile
    destination.mkdir(parents=True, exist_ok=True)
    budget = AudioBudget(destination)
    cache = destination / 'metadata'
    manifest = {'format': 1, 'corpus': 'BEL-Preview2-LibriSpeech-v1', 'kind': 'Recorded human read speech',
                'dataset': DATASET, 'revision': REVISION, 'license': 'CC-BY-4.0',
                'source': 'https://www.openslr.org/12/',
                'attribution': 'Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev Khudanpur; LibriSpeech ASR corpus, ICASSP 2015.',
                'selection': 'No model outputs used. For each test split, round-robin speakers sorted by SHA-256 of BEL-preview2-corpus-v1/speaker; utterances sorted by SHA-256 of BEL-preview2-corpus-v1/id. Reference word count 24..55, actual duration 0.1..20s. Skip only duration/format failures.',
                'audio_download_budget_bytes': LIMIT, 'audio_downloaded_bytes': 0,
                'started_utc': datetime.now(timezone.utc).isoformat(), 'clips': [], 'excluded': [],
                'limitations': ['Read audiobooks, not spontaneous conversation or owner microphone acceptance.',
                                'No Hindi or code-switched recordings in this corpus.',
                                'Number/punctuation accuracy requires a separately labeled corpus; LibriSpeech references are uppercase and unpunctuated.']}
    for config in ('clean', 'other'):
        selection = destination / (config + '-selection.json')
        if selection.exists():
            frozen_bytes = selection.read_bytes()
            candidates = json.loads(frozen_bytes)
        else:
            first = metadata(config, cache=cache)
            all_rows = list(first['rows'])
            total = first['num_rows_total']
            for offset in range(100, total, 100):
                all_rows.extend(metadata(config, offset, cache=cache)['rows'])
                print(json.dumps({'metadata_split': config, 'rows': len(all_rows)}), flush=True)
            speakers = {}
            for item in all_rows:
                row = dict(item['row'])
                if not re.fullmatch(r'\d+-\d+-\d+', row['id']):
                    raise ValueError('Unexpected corpus ID')
                if not 24 <= len(row['text'].split()) <= 55:
                    continue
                row['row_idx'] = item['row_idx']
                speakers.setdefault(str(row['speaker_id']), []).append(row)
            for choices in speakers.values():
                choices.sort(key=selection_key)
            order = sorted(speakers, key=lambda value: hashlib.sha256(('BEL-preview2-corpus-v1/' + value).encode()).hexdigest())
            candidates = [speakers[speaker][n] for n in range(max(map(len, speakers.values())))
                          for speaker in order if n < len(speakers[speaker])]
            candidates = [{key: row[key] for key in ('id', 'speaker_id', 'row_idx', 'text')} for row in candidates]
            frozen_bytes = json.dumps(candidates, ensure_ascii=False, sort_keys=True).encode('utf-8')
            with selection.open('xb') as stream: stream.write(frozen_bytes)
        manifest[config + '_selection_sha256'] = hashlib.sha256(frozen_bytes).hexdigest()
        accepted = 0
        for row in candidates:
            if accepted >= count:
                break
            if not re.fullmatch(r'\d+-\d+-\d+', row['id']) or type(row['row_idx']) is not int or row['row_idx'] < 0:
                raise ValueError('Invalid frozen corpus selection')
            # Refresh signed per-row access URLs after potentially long metadata discovery.
            fresh = metadata(config, row['row_idx'], 1, cache=cache)['rows'][0]['row']
            if (fresh['id'], fresh['text']) != (row['id'], row['text']):
                raise ValueError('Corpus labels changed during provisioning')
            url = fresh['audio'][0]['src']
            if f'/{REVISION}/' not in url:
                raise ValueError('Dataset viewer revision changed; review the new corpus first')
            raw = budget.read_or_fetch(config + '-' + row['id'] + '.flac', url)
            samples, rate = soundfile.read(io.BytesIO(raw), dtype='int16', always_2d=True)
            duration = len(samples) / rate
            if rate != 16000 or samples.shape[1] != 1 or not .1 <= duration <= 20:
                manifest['excluded'].append({'id': row['id'], 'split': config, 'reason': 'duration or format',
                                             'seconds': duration, 'audio_bytes': len(raw)})
                continue
            wav = wav_bytes(samples[:, 0], rate)
            name = config + '-' + row['id'] + '.wav'
            wav_path = destination / name
            if wav_path.exists() and wav_path.read_bytes() != wav:
                raise ValueError('Retained decoded corpus WAV changed')
            if not wav_path.exists(): wav_path.write_bytes(wav)
            manifest['clips'].append({'id': row['id'], 'speaker_id': row['speaker_id'], 'split': config,
                                      'locale': 'en-US', 'reference': row['text'], 'row_idx': row['row_idx'],
                                      'path': name, 'seconds': round(duration, 4),
                                      'source_audio_sha256': hashlib.sha256(raw).hexdigest(),
                                      'wav_sha256': hashlib.sha256(wav).hexdigest(), 'downloaded_bytes': len(raw),
                                      'source_url': url.split('?', 1)[0]})
            accepted += 1
            print(json.dumps({'split': config, 'accepted': accepted, 'audio_bytes': budget.data['charged_bytes']}), flush=True)
        if accepted != count:
            raise ValueError('Insufficient qualifying corpus rows')
    manifest['audio_downloaded_bytes'] = sum(row['bytes'] for row in budget.data['files'].values())
    manifest['audio_budget_charged_bytes'] = budget.data['charged_bytes']
    manifest['download_ledger_sha256'] = hashlib.sha256(budget.path.read_bytes()).hexdigest()
    manifest['completed_utc'] = datetime.now(timezone.utc).isoformat()
    manifest['reference_words'] = sum(len(row['reference'].split()) for row in manifest['clips'])
    manifest['seconds'] = round(sum(row['seconds'] for row in manifest['clips']), 4)
    manifest['speakers'] = len(set(row['speaker_id'] for row in manifest['clips']))
    manifest['split_counts'] = dict(Counter(row['split'] for row in manifest['clips']))
    with (destination / 'manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true', help='Explicitly authorize up to 50 MB of licensed evaluation audio')
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--eval-deps', type=Path, default=ROOT / '.cache/preview2/eval-deps')
    parser.add_argument('--per-split', type=int, default=40)
    args = parser.parse_args()
    if not args.download:
        parser.error('No network access without explicit --download consent')
    result = provision(args.destination.resolve(), args.eval_deps, args.per_split)
    print(json.dumps({key: result[key] for key in ('speakers', 'reference_words', 'seconds', 'audio_downloaded_bytes', 'split_counts')}))


if __name__ == '__main__':
    main()
