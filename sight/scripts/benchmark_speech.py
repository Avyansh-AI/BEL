"""Reproducible offline ASR comparison on an immutable licensed corpus manifest.

No model/corpus downloads, microphone access, playback, chat or tool execution.
Raw references/hypotheses remain beside the private corpus. Public output carries
per-example edit counts, latency and sampled resource consumption, not audio.
"""
from __future__ import annotations

import argparse
from array import array
import asyncio
from collections import defaultdict
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
import platform
from pathlib import Path
import random
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import unicodedata
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def normalize(text):
    # Preserve Hindi combining marks and digits; never transliterate or replace
    # spoken numbers with digits. Report this normalization with every result.
    text = unicodedata.normalize('NFKC', text).casefold()
    return ' '.join(''.join(c if unicodedata.category(c)[0] in {'L', 'M', 'N'} else ' ' for c in text).split())


def edit_distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, left in enumerate(reference, 1):
        row = [i]
        for j, right in enumerate(hypothesis, 1):
            row.append(min(row[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = row
    return previous[-1]


def score(reference, hypothesis):
    expected, actual = normalize(reference), normalize(hypothesis)
    return {'word_edits': edit_distance(expected.split(), actual.split()), 'reference_words': len(expected.split()),
            'character_edits': edit_distance(expected.replace(' ', ''), actual.replace(' ', '')),
            'reference_characters': len(expected.replace(' ', '')), 'exact_normalized': expected == actual}


def pcm(raw):
    with wave.open(io.BytesIO(raw), 'rb') as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError('Expected bounded 16k mono PCM corpus')
        values = array('h', audio.readframes(audio.getnframes()))
        if sys.byteorder != 'little':
            values.byteswap()
        return values


def wav(values):
    output = io.BytesIO()
    values = array('h', values)
    if sys.byteorder != 'little':
        values.byteswap()
    with wave.open(output, 'wb') as target:
        target.setparams((1, 2, 16000, len(values), 'NONE', 'not compressed'))
        target.writeframes(values.tobytes())
    return output.getvalue()


def noisy(raw, seed, snr=10):
    values = pcm(raw)
    if not values:
        raise ValueError('Empty audio')
    rms = math.sqrt(sum(value * value for value in values) / len(values))
    rng = random.Random(seed)
    sigma = rms / (10 ** (snr / 20))
    return wav(max(-32768, min(32767, round(value + rng.gauss(0, sigma)))) for value in values)


class ResourceMonitor:
    """Sample only this benchmark and its descendants; never owner process data."""
    def __init__(self):
        self.stop = threading.Event()
        self.rows = []
        self.gpu = []
        self.owned_gpu = []
        self.gpu_attribution_available = False
        self.thread = None
        self.gpu_thread = None
        self.owned = {os.getpid()}
        self.nvidia = shutil.which('nvidia-smi')
        if os.name != 'nt':
            raise RuntimeError('This resource monitor requires Windows')
        class Entry(ctypes.Structure):
            _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                        ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                        ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG), ('dwFlags', wintypes.DWORD),
                        ('szExeFile', wintypes.WCHAR * 260)]
        class Memory(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in
                ('PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage',
                 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]
        class SystemMemory(ctypes.Structure):
            _fields_ = [('dwLength', wintypes.DWORD), ('dwMemoryLoad', wintypes.DWORD)] + [(name, ctypes.c_ulonglong) for name in
                ('ullTotalPhys', 'ullAvailPhys', 'ullTotalPageFile', 'ullAvailPageFile', 'ullTotalVirtual', 'ullAvailVirtual', 'ullAvailExtendedVirtual')]
        self.Entry, self.Memory, self.SystemMemory = Entry, Memory, SystemMemory
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        self.kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.memory_info = ctypes.WinDLL('psapi').GetProcessMemoryInfo
        self.memory_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]

    def sample(self):
        snapshot = self.kernel.CreateToolhelp32Snapshot(2, 0)
        parents = {}
        if snapshot == ctypes.c_void_p(-1).value:
            raise OSError('Process sampling unavailable')
        try:
            row = self.Entry(); row.dwSize = ctypes.sizeof(row)
            if self.kernel.Process32FirstW(snapshot, ctypes.byref(row)):
                while True:
                    parents[row.th32ProcessID] = row.th32ParentProcessID
                    if not self.kernel.Process32NextW(snapshot, ctypes.byref(row)):
                        break
        finally:
            self.kernel.CloseHandle(snapshot)
        owned = {os.getpid()}
        while True:
            expanded = owned | {pid for pid, parent in parents.items() if parent in owned}
            if expanded == owned: break
            owned = expanded
        self.owned = owned
        total, private = 0, 0
        for pid in owned:
            handle = self.kernel.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle: continue
            try:
                memory = self.Memory(); memory.cb = ctypes.sizeof(memory)
                if self.memory_info(handle, ctypes.byref(memory), memory.cb):
                    total += memory.WorkingSetSize
                    private += memory.PrivateUsage
            finally:
                self.kernel.CloseHandle(handle)
        available = self.SystemMemory(); available.dwLength = ctypes.sizeof(available)
        if not self.kernel.GlobalMemoryStatusEx(ctypes.byref(available)):
            raise OSError('System memory sampling unavailable')
        self.rows.append({'working_set': total, 'private_bytes': private, 'available': available.ullAvailPhys,
                          'children': len(owned) - 1})

    def sample_gpu(self):
        if not self.nvidia: return
        try:
            result = subprocess.run([self.nvidia, '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
                                    capture_output=True, timeout=3, creationflags=0x08000000, check=True)
            self.gpu.extend(int(value) for value in result.stdout.decode().splitlines() if value.strip().isdigit())
            result = subprocess.run([self.nvidia, '--query-compute-apps=pid,used_gpu_memory', '--format=csv,noheader,nounits'],
                                    capture_output=True, timeout=3, creationflags=0x08000000, check=True)
            matched, unavailable = [], False
            for line in result.stdout.decode().splitlines():
                columns = [column.strip() for column in line.split(',')]
                if len(columns) == 2 and columns[0].isdigit() and int(columns[0]) in self.owned:
                    if columns[1].isdigit(): matched.append(int(columns[1]))
                    else: unavailable = True
            if matched and not unavailable:
                self.gpu_attribution_available = True
                self.owned_gpu.append(sum(matched))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

    def start(self):
        self.sample_gpu()
        self.sample()
        def monitor():
            while not self.stop.wait(.025):
                try: self.sample()
                except OSError: pass
        self.thread = threading.Thread(target=monitor, daemon=True)
        self.thread.start()
        def gpu_monitor():
            while not self.stop.wait(1): self.sample_gpu()
        self.gpu_thread = threading.Thread(target=gpu_monitor, daemon=True)
        self.gpu_thread.start()

    def finish(self):
        self.stop.set()
        self.thread.join()
        self.gpu_thread.join()
        self.sample_gpu()
        mib = lambda value: round(value / (1024 ** 2), 3)
        return {'samples': len(self.rows), 'peak_sampled_working_set_mib': mib(max(row['working_set'] for row in self.rows)),
                'peak_sampled_private_mib': mib(max(row['private_bytes'] for row in self.rows)),
                'minimum_system_available_mib': mib(min(row['available'] for row in self.rows)),
                'max_sampled_children': max(row['children'] for row in self.rows),
                'gpu_total_samples_mib': self.gpu,
                'gpu_peak_sampled_board_mib': max(self.gpu) if self.gpu else None,
                'gpu_peak_sampled_owned_mib': max(self.owned_gpu) if self.owned_gpu else None,
                'gpu_attribution_available': self.gpu_attribution_available,
                'gpu_scope': 'Whole GPU sampled before/after and every second, includes other applications. Owned PID memory is null when no attributed allocation is reported; Windows WDDM may report N/A. Null does not prove zero VRAM.',
                'ram_scope': 'Aggregate sampled working set/private bytes of harness plus direct/transitive owned children, 25ms interval.'}


def aggregate(rows):
    words = sum(row['reference_words'] for row in rows)
    characters = sum(row['reference_characters'] for row in rows)
    return {'clips': len(rows), 'wer': sum(row['word_edits'] for row in rows) / words if words else None,
            'cer': sum(row['character_edits'] for row in rows) / characters if characters else None,
            'reference_words': words, 'reference_characters': characters,
            'recognition_errors': sum(row['status'] != 'ok' for row in rows),
            'latency_median_seconds': round(statistics.median(row['seconds'] for row in rows), 4),
            'latency_max_seconds': max(row['seconds'] for row in rows),
            'peak_sampled_working_set_mib': max(row['resources']['peak_sampled_working_set_mib'] for row in rows),
            'peak_sampled_private_mib': max(row['resources']['peak_sampled_private_mib'] for row in rows),
            'gpu_peak_sampled_board_mib': max((row['resources']['gpu_peak_sampled_board_mib'] for row in rows if row['resources']['gpu_peak_sampled_board_mib'] is not None), default=None)}


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def validate_corpus(corpus, manifest):
    if manifest.get('format') != 1 or not manifest.get('clips'):
        raise ValueError('Unsupported corpus manifest')
    seen = set()
    for row in manifest['clips']:
        identity = (row['split'], row['id'])
        if identity in seen: raise ValueError('Duplicate corpus example')
        seen.add(identity)
        path = (corpus / row['path']).resolve(strict=True)
        if not path.is_relative_to(corpus) or hashlib.sha256(path.read_bytes()).hexdigest() != row['wav_sha256']:
            raise ValueError('Corpus WAV hash or path mismatch')
        values = pcm(path.read_bytes())
        if not 1600 <= len(values) <= 320000:
            raise ValueError('Corpus audio outside the product duration limit')


async def run(args):
    from sight_core.local_speech import LocalSpeech
    from sight_core.speech_engines import WhisperCpp
    corpus = args.corpus.resolve(strict=True)
    manifest_bytes = (corpus / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    validate_corpus(corpus, manifest)
    if args.output.exists() and not args.resume:
        raise ValueError('Preserve prior evidence; choose a new output file')
    clips = manifest['clips']
    engines = {'windows': lambda: LocalSpeech(True),
               'base-q5_1': lambda: WhisperCpp(args.assets, model='base-q5_1'),
               'small-q5_1': lambda: WhisperCpp(args.assets, model='small-q5_1')}
    choices = args.engines.split(',')
    if any(name not in engines for name in choices):
        raise ValueError('Unknown benchmark engine')
    record = {'format': 1, 'kind': 'Real offline ASR of licensed recorded human speech; no microphone',
              'started_utc': datetime.now(timezone.utc).isoformat(), 'corpus_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
              'corpus': {key: manifest.get(key) for key in ('corpus', 'dataset', 'revision', 'license', 'source', 'speakers', 'reference_words', 'seconds')},
              'normalization': 'NFKC/casefold; retain Unicode letters/marks/numbers, punctuation to spaces; CER excludes spaces; no transliteration or number expansion.',
              'engines': choices, 'device': 'CPU', 'microphone_access': False, 'cloud_requests': 0, 'rows': [],
              'limitations': ['Read-speech sample is not general conversational or owner-device qualification.',
                              'Noise is deterministic added Gaussian10dB, not recorded real-world environmental noise.',
                              'Windows confidence and Whisper token likelihood are not mutually calibrated accuracy probabilities.',
                              'No unpunctuated corpus can qualify punctuation accuracy. Numeral normalization is deliberately absent.'],
              'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), ROOT / 'sight_core/local_speech.py', ROOT / 'sight_core/speech_worker.py', ROOT / 'sight_core/speech_engines.py', ROOT / 'sight_core/asr_assets.py', ROOT / 'sight_core/speech_resources.py')},
              'asr_manifest_sha256': hashlib.sha256((args.assets / 'manifest.json').read_bytes()).hexdigest()}
    private = []
    raw_path = corpus / ('private-' + args.output.stem + '-hypotheses.json')
    if args.resume and args.output.exists():
        existing = json.loads(args.output.read_text(encoding='utf-8'))
        for key in ('corpus_manifest_sha256', 'engines', 'source_sha256', 'asr_manifest_sha256'):
            if existing.get(key) != record[key]:
                raise ValueError('Cannot combine evidence from changed code, engines or corpus')
        if existing.get('complete'): raise ValueError('Completed benchmark evidence is immutable')
        record = existing
        private = json.loads(raw_path.read_text(encoding='utf-8'))
        if len(private) != len(record['rows']):
            raise ValueError('Interrupted evidence transaction; retain it and use a new output')
    elif raw_path.exists():
        raise ValueError('Existing private evidence; choose a new output stem')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        write_json(raw_path, private)
        write_json(args.output, record)
    save()
    conditions = [(row, 'original') for row in clips]
    for split in ('clean', 'other'):
        conditions += [(row, 'noise10dB') for row in [r for r in clips if r['split'] == split][:5]]
    for name in choices:
        service = engines[name]()
        for row, condition in conditions:
            if any(item['engine'] == name and item['id'] == row['id'] and item['split'] == row['split'] and item['condition'] == condition for item in record['rows']):
                continue
            raw = (corpus / row['path']).read_bytes()
            if condition == 'noise10dB': raw = noisy(raw, row['id'])
            monitor = ResourceMonitor(); monitor.start()
            started = time.monotonic()
            hypothesis, confidence, status, error = '', None, 'ok', None
            try:
                result = await service.transcribe(raw, row['locale'])
                hypothesis, confidence = result['text'], result.get('confidence')
            except Exception as exc:
                status = type(exc).__name__
                # The offline adapters emit fixed diagnostics, never raw worker
                # stdout/stderr, credentials, audio or recognized words.
                error = str(exc)[:300] if status in {'SpeechUnavailable', 'SpeechInputError', 'SpeechBusy'} else 'Unexpected harness/adapter failure'
            finally:
                elapsed = round(time.monotonic() - started, 4)
                resources = monitor.finish()
            graded = {'engine': name, 'id': row['id'], 'split': row['split'], 'locale': row['locale'], 'condition': condition,
                      'seconds': elapsed, 'audio_seconds': row['seconds'], 'status': status, 'error': error, 'confidence': confidence,
                      'resources': resources, **score(row['reference'], hypothesis)}
            record['rows'].append(graded)
            private.append({'engine': name, 'id': row['id'], 'condition': condition, 'reference': row['reference'], 'hypothesis': hypothesis})
            save()
            print(json.dumps({key: graded[key] for key in ('engine', 'id', 'condition', 'status', 'word_edits', 'reference_words', 'seconds')}), flush=True)
        for case, values in [('silence', [0] * 32000), ('near_silence', [1, -1] * 16000)]:
            if any(item['engine'] == name and item['case'] == case for item in record.get('silence_checks', [])):
                continue
            raw = wav(values)
            monitor = ResourceMonitor(); monitor.start()
            started = time.monotonic()
            text, status = '', 'ok'
            try: text = (await service.transcribe(raw, 'en-US'))['text']
            except Exception as exc: status = type(exc).__name__
            finally:
                elapsed = round(time.monotonic() - started, 4)
                resources = monitor.finish()
            record.setdefault('silence_checks', []).append({'engine': name, 'case': case, 'status': status,
                'hallucinated_characters': len(text.strip()), 'safe_empty': not text.strip() and status in {'ok', 'SpeechInputError'},
                'seconds': elapsed, 'resources': resources})
            save()
    grouped = defaultdict(list)
    for row in record['rows']: grouped[(row['engine'], row['locale'], row['split'], row['condition'])].append(row)
    record['groups'] = [{'engine': key[0], 'locale': key[1], 'split': key[2], 'condition': key[3], **aggregate(rows)} for key, rows in grouped.items()]
    record['language_original'] = {locale: {name: aggregate([row for row in record['rows'] if row['engine'] == name and row['locale'] == locale and row['condition'] == 'original']) for name in choices}
                                   for locale in sorted({row['locale'] for row in record['rows']})}
    record['english_original'] = {name: aggregate([row for row in record['rows'] if row['engine'] == name and row['locale'].startswith('en-') and row['condition'] == 'original']) for name in choices} if any(row['locale'].startswith('en-') for row in record['rows']) else {}
    record['environment'] = {'platform': platform.platform(), 'python': platform.python_version(),
                             'logical_processors': os.cpu_count(), 'inference_threads': 4,
                             'device': 'CPU', 'other_system_workloads_controlled': False}
    record['source_files_unchanged'] = all(hashlib.sha256((Path(__file__) if name == Path(__file__).name else ROOT / 'sight_core' / name).read_bytes()).hexdigest() == expected for name, expected in record['source_sha256'].items())
    if not record['source_files_unchanged']:
        record['complete'] = False
        save()
        raise ValueError('Recognizer or harness source changed during evaluation; preserve this unqualified evidence and rerun')
    record['completed_utc'] = datetime.now(timezone.utc).isoformat()
    record['complete'] = True
    save()
    print(json.dumps({'english_original': record['english_original'], 'evidence': str(args.output)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--engines', default='windows,base-q5_1,small-q5_1')
    parser.add_argument('--resume', action='store_true', help='Continue only matching partial code/corpus evidence without replaying completed cases')
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
