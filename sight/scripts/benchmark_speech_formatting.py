"""Supplementary synthetic offline numbers/punctuation evaluation.

This is NOT human speech, microphone, accent or general accuracy qualification.
Fixed spoken references and desired written forms are declared before recognition.
No reference, vocabulary hint or desired formatting is sent to an ASR engine.
Windows System.Speech synthesizes only to local WAV files; no playback or capture.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import statistics
import sys
import threading
import time
import unicodedata
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_speech import score, write_json
from sight_core.local_speech import LocalSpeech, powershell_path, run_process, validate_audio
from sight_core.speech_engines import WhisperCpp


# These references are intentionally not adjusted to model output. A strict
# written-form mismatch does not prove the recognizer misunderstood a number.
CASES = (
    ('counts', 'There are twelve blue notebooks and twenty four pencils.', 'There are 12 blue notebooks and 24 pencils.'),
    ('zero', 'The counter shows zero unread messages.', 'The counter shows 0 unread messages.'),
    ('negative', 'The temperature fell to minus five degrees overnight.', 'The temperature fell to -5 degrees overnight.'),
    ('decimal', 'The measured distance is three point seven five meters.', 'The measured distance is 3.75 meters.'),
    ('money', 'The notebook costs nineteen dollars and ninety five cents.', 'The notebook costs $19.95.'),
    ('large_money', 'The total is one thousand two hundred fifty dollars.', 'The total is $1,250.'),
    ('time', 'The meeting starts at nine thirty tomorrow morning.', 'The meeting starts at 9:30 tomorrow morning.'),
    ('time_question', 'Will the train arrive at six forty five?', 'Will the train arrive at 6:45?'),
    ('date', 'The appointment is on November eighth, twenty twenty six.', 'The appointment is on November 8, 2026.'),
    ('year', 'The library opened in nineteen ninety eight.', 'The library opened in 1998.'),
    ('phone', 'The extension is five five five zero one four seven.', 'The extension is 5550147.'),
    ('identifier', 'The reference code is eight zero three one nine.', 'The reference code is 80319.'),
    ('percentage', 'The battery is at forty two percent.', 'The battery is at 42%.'),
    ('decimal_percent', 'The annual rate is three point five percent.', 'The annual rate is 3.5%.'),
    ('fraction', 'Add one half cup of water.', 'Add 1/2 cup of water.'),
    ('range', 'The parcel weighs between seven and nine kilograms.', 'The parcel weighs between 7 and 9 kilograms.'),
    ('ordinal', 'Please use the third door on the left.', 'Please use the 3rd door on the left.'),
    ('duration', 'The timer will run for fifteen minutes and twenty seconds.', 'The timer will run for 15 minutes and 20 seconds.'),
    ('number_question', 'Do we need thirty six chairs for the guests?', 'Do we need 36 chairs for the guests?'),
    ('comma', 'After lunch, bring six cups, eight plates, and two bowls.', 'After lunch, bring 6 cups, 8 plates, and 2 bowls.'),
    ('statement', 'The blue notebook is beside the window.', 'The blue notebook is beside the window.'),
    ('question', 'Where did you put the green umbrella?', 'Where did you put the green umbrella?'),
    ('two_sentences', 'The package arrived today. Please leave it by the door.', 'The package arrived today. Please leave it by the door.'),
    ('contrast', 'The room is quiet, but the corridor is busy.', 'The room is quiet, but the corridor is busy.'),
)

NUMBER = re.compile(r'(?<!\w)[$£₹]?[+-]?\d+(?:[.,:/-]\d+)*(?:st|nd|rd|th|%)?(?!\w)', re.I)


def formatting_score(reference, hypothesis):
    expected = unicodedata.normalize('NFKC', reference)
    actual = unicodedata.normalize('NFKC', hypothesis)
    numeric_expected = NUMBER.findall(expected)
    numeric_actual = NUMBER.findall(actual)
    punctuation = lambda value: ''.join(c for c in NUMBER.sub('', value) if c in '.,:;?!')
    return {
        'numeric_reference_tokens': len(numeric_expected),
        'numeric_observed_tokens': len(numeric_actual),
        'numeric_sequence_exact': numeric_expected == numeric_actual,
        'numeric_position_matches': sum(a == b for a, b in zip(numeric_expected, numeric_actual)),
        'punctuation_reference_marks': len(punctuation(expected)),
        'punctuation_observed_marks': len(punctuation(actual)),
        'punctuation_sequence_exact': punctuation(expected) == punctuation(actual),
    }


SYNTHESIZE = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$voice = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $voices = @($voice.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'en-US' } | ForEach-Object { $_.VoiceInfo.Name } | Sort-Object)
    if ($voices.Count -eq 0) { throw 'No installed local English synthesis voice' }
    $voice.SelectVoice($voices[[int]$request.index % $voices.Count])
    $voice.Rate = 0
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $voice.SetOutputToWaveFile([string]$request.output, $format)
    $voice.Speak([string]$request.text)
    $voice.SetOutputToNull()
    @{ok=$true; voice=$voice.Voice.Name; locale=$voice.Voice.Culture.Name; rate=$voice.Rate} | ConvertTo-Json -Compress
} finally { $voice.Dispose() }
'''


def declared_cases():
    return [{'id': f'{i + 1:02d}-{name}', 'category': name, 'spoken_reference': spoken,
             'written_reference': written, 'path': f'{i + 1:02d}-{name}.wav', 'locale': 'en-US'}
            for i, (name, spoken, written) in enumerate(CASES)]


def prepare(corpus):
    if os.name != 'nt':
        raise RuntimeError('Synthetic corpus preparation requires Windows System.Speech')
    corpus.mkdir(parents=True, exist_ok=False)
    declaration = {'format': 1, 'kind': 'Synthetic Windows System.Speech TTS, not recorded human voices',
                   'created_utc': datetime.now(timezone.utc).isoformat(),
                   'microphone_access': False, 'playback': False, 'network_requests': 0,
                   'text_provenance': 'Original fixed test sentences authored for BEL evaluation; repository MIT license.',
                   'synthesis_provenance': 'Installed Microsoft Windows System.Speech voices; local evaluation only, audio not distributed.',
                   'cases': declared_cases()}
    # Freeze every label BEFORE the first audio file and any ASR observation.
    write_json(corpus / 'declaration.json', declaration)
    encoded = base64.b64encode(SYNTHESIZE.encode('utf-16-le')).decode('ascii')
    command = [str(powershell_path()), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]
    rows = []
    for i, case in enumerate(declaration['cases']):
        destination = corpus / case['path']
        request = {'index': i, 'output': str(destination), 'text': case['spoken_reference']}
        started = time.monotonic()
        metadata = json.loads(run_process(command, json.dumps(request).encode(), threading.Event(), 30).decode('utf-8-sig'))
        if metadata.get('ok') is not True or metadata.get('locale') != 'en-US':
            raise ValueError('Invalid synthesis response')
        raw = destination.read_bytes()
        validate_audio(raw)
        with wave.open(io.BytesIO(raw), 'rb') as audio:
            seconds = audio.getnframes() / audio.getframerate()
        rows.append({**case, 'wav_sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'seconds': seconds,
                     'synthesizer': metadata, 'synthesis_seconds': round(time.monotonic() - started, 4)})
    manifest = {**declaration, 'cases': rows, 'declaration_sha256': hashlib.sha256((corpus / 'declaration.json').read_bytes()).hexdigest()}
    write_json(corpus / 'manifest.json', manifest)
    print(json.dumps({'prepared': len(rows), 'seconds': sum(row['seconds'] for row in rows), 'corpus': str(corpus)}), flush=True)


def validate_corpus(corpus):
    manifest_raw = (corpus / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    declaration_raw = (corpus / 'declaration.json').read_bytes()
    declaration = json.loads(declaration_raw)
    if manifest.get('format') != 1 or manifest.get('declaration_sha256') != hashlib.sha256(declaration_raw).hexdigest():
        raise ValueError('Synthetic corpus declaration changed')
    if declaration.get('cases') != declared_cases() or len(manifest.get('cases', [])) != len(CASES):
        raise ValueError('Synthetic corpus reference set changed')
    for expected, row in zip(declared_cases(), manifest['cases']):
        if any(row.get(key) != value for key, value in expected.items()):
            raise ValueError('Synthetic corpus reference changed')
        raw = (corpus / row['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row.get('wav_sha256'):
            raise ValueError('Synthetic corpus audio changed')
        validate_audio(raw)
    return manifest, hashlib.sha256(manifest_raw).hexdigest()


def summarize(rows):
    count = len(rows)
    number_cases = [row for row in rows if row['numeric_reference_tokens']]
    numeric_total = sum(row['numeric_reference_tokens'] for row in rows)
    result = {'cases': count, 'recognition_errors': sum(row['status'] != 'ok' for row in rows),
              'numeric_cases': len(number_cases),
              'numeric_sequence_exact_cases': sum(row['numeric_sequence_exact'] for row in number_cases),
              'numeric_reference_tokens': numeric_total,
              'numeric_position_exact_rate': sum(row['numeric_position_matches'] for row in rows) / numeric_total if numeric_total else None,
              'punctuation_sequence_exact_cases': sum(row['punctuation_sequence_exact'] for row in rows),
              'punctuation_sequence_exact_rate': sum(row['punctuation_sequence_exact'] for row in rows) / count if count else None,
              'median_latency_seconds': statistics.median(row['latency_seconds'] for row in rows) if rows else None,
              'max_latency_seconds': max((row['latency_seconds'] for row in rows), default=None)}
    for kind in ('spoken', 'written'):
        words = sum(row[kind]['reference_words'] for row in rows)
        characters = sum(row[kind]['reference_characters'] for row in rows)
        result[kind + '_wer'] = sum(row[kind]['word_edits'] for row in rows) / words if words else None
        result[kind + '_cer'] = sum(row[kind]['character_edits'] for row in rows) / characters if characters else None
    return result


async def evaluate(args):
    if args.output.exists():
        raise ValueError('Choose new evidence output; never replace an earlier evaluation')
    manifest, corpus_hash = validate_corpus(args.corpus)
    engines = {'windows': lambda: LocalSpeech(True), 'base-q5_1': lambda: WhisperCpp(args.assets, 'base-q5_1'),
               'small-q5_1': lambda: WhisperCpp(args.assets, 'small-q5_1')}
    choices = args.engines.split(',')
    if not choices or len(set(choices)) != len(choices) or any(name not in engines for name in choices):
        raise ValueError('Invalid evaluation engines')
    source_paths = [Path(__file__), ROOT / 'scripts/benchmark_speech.py'] + [ROOT / 'sight_core' / name for name in
                    ('local_speech.py', 'speech_worker.py', 'speech_engines.py', 'speech_resources.py', 'asr_assets.py')]
    sources = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    assets_hash = hashlib.sha256((args.assets / 'manifest.json').read_bytes()).hexdigest()
    result = {'format': 1, 'kind': 'Supplementary synthetic number and punctuation formatting evaluation',
              'corpus_manifest_sha256': corpus_hash, 'source_sha256': sources, 'engines': choices,
              'asr_manifest_sha256': assets_hash,
              'corpus': {'cases': len(manifest['cases']), 'audio_seconds': sum(row['seconds'] for row in manifest['cases']),
                         'audio_bytes': sum(row['bytes'] for row in manifest['cases']),
                         'voices': sorted({row['synthesizer']['voice'] for row in manifest['cases']}),
                         'locale': 'en-US', 'synthesis_rate': 0, 'provenance': manifest['synthesis_provenance']},
              'environment': {'platform': platform.platform(), 'python': platform.python_version(), 'device': 'CPU',
                              'other_system_workloads_controlled': False},
              'started_utc': datetime.now(timezone.utc).isoformat(), 'microphone_access': False,
              'cloud_requests': 0, 'playback': False, 'complete': False, 'rows': [],
              'normalization': 'WER/CER use benchmark_speech.score unchanged, no number expansion. Strict numeric sequence preserves signs, currency, separators and ordinals. Punctuation compares .,;:?! after removing numeric spans.',
              'limitations': ['Synthetic text-to-file from installed Windows voices; not human-speech or microphone qualification.',
                              'Chosen written number forms and punctuation may be acoustically ambiguous; strict formatting scores do not measure semantic number comprehension.',
                              'Both spoken-word and desired-written-reference WER/CER are reported; an equivalent number rendered differently can increase either score.',
                              'No model prompt, expected text, vocabulary hint or post-recognition correction is supplied.',
                              'Resource consumption is measured in the separate representative speech benchmark; this supplement records latency only.']}
    private = []
    private_path = args.corpus / ('private-' + args.output.stem + '-hypotheses.json')
    if private_path.exists():
        raise ValueError('Choose a new private evidence stem')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    for name in choices:
        service = engines[name]()
        for case in manifest['cases']:
            started = time.monotonic()
            text, status = '', 'ok'
            try:
                text = (await service.transcribe((args.corpus / case['path']).read_bytes(), 'en-US'))['text']
            except Exception as exc:
                status = type(exc).__name__
            row = {'engine': name, 'id': case['id'], 'status': status,
                   'latency_seconds': round(time.monotonic() - started, 4), 'audio_seconds': case['seconds'],
                   'spoken': score(case['spoken_reference'], text), 'written': score(case['written_reference'], text),
                   **formatting_score(case['written_reference'], text)}
            result['rows'].append(row)
            private.append({'engine': name, 'id': case['id'], 'hypothesis': text})
            write_json(private_path, private); write_json(args.output, result)
            print(json.dumps({key: row[key] for key in ('engine', 'id', 'status', 'latency_seconds', 'numeric_sequence_exact', 'punctuation_sequence_exact')}), flush=True)
    result['summary'] = {name: summarize([row for row in result['rows'] if row['engine'] == name]) for name in choices}
    result['source_files_unchanged'] = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value for name, value in sources.items())
    result['corpus_unchanged'] = validate_corpus(args.corpus)[1] == corpus_hash
    result['asr_manifest_unchanged'] = hashlib.sha256((args.assets / 'manifest.json').read_bytes()).hexdigest() == assets_hash
    result['complete'] = result['source_files_unchanged'] and result['corpus_unchanged'] and result['asr_manifest_unchanged']
    result['completed_utc'] = datetime.now(timezone.utc).isoformat()
    write_json(args.output, result)
    print(json.dumps({'complete': result['complete'], 'summary': result['summary']}), flush=True)
    if not result['complete']:
        raise ValueError('Evidence source changed during evaluation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--prepare', action='store_true', help='Explicitly generate local synthetic WAVs, no playback or microphone')
    parser.add_argument('--assets', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--engines', default='windows,small-q5_1')
    args = parser.parse_args()
    args.corpus = args.corpus.resolve()
    if args.prepare:
        if args.output or args.assets:
            parser.error('Prepare and evaluate are separate commands')
        prepare(args.corpus)
    else:
        if not args.assets or not args.output:
            parser.error('Evaluation requires --assets and --output')
        args.assets = args.assets.resolve(); args.output = args.output.resolve()
        asyncio.run(evaluate(args))


if __name__ == '__main__':
    main()
