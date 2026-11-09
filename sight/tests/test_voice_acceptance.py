"""Safety properties of preview evidence tools; these are not hardware tests."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

import pytest

from sight_core.wake import DisabledWakeEngine, WakeDetection, WakeEngine, FRAME_BYTES

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_disabled_wake_cannot_load_a_model_launch_process_or_activate(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Disabled wake launched a process'))
    engine = DisabledWakeEngine()
    assert isinstance(engine, WakeEngine)
    for _ in range(50):
        assert engine.feed(b'\x40' * FRAME_BYTES) is None
    engine.reset()
    engine.close()
    assert engine.feed(b'\0' * FRAME_BYTES) is None
    assert engine.status()['available'] is False
    assert engine.status()['enabled'] is False
    assert engine.status()['enrolled'] is False


@pytest.mark.parametrize('frame', [b'', b'\0' * (FRAME_BYTES - 1), b'\0' * (FRAME_BYTES + 1), bytearray(FRAME_BYTES), 'BEL'])
def test_wake_boundary_rejects_unbounded_or_untyped_data(frame):
    with pytest.raises(ValueError):
        DisabledWakeEngine().feed(frame)


@pytest.mark.parametrize('score', [True, -1, 2, float('nan'), float('inf'), '.9', None])
def test_wake_event_does_not_accept_invalid_score(score):
    with pytest.raises(ValueError):
        WakeDetection('BEL', score, '0' * 64)


@pytest.mark.parametrize('phrase,identity', [('Hey Jarvis', '0' * 64), ('BEL', ''), ('BEL', 'x' * 64), ('BEL', None)])
def test_wake_event_requires_phrase_and_pinned_model_identity(phrase, identity):
    with pytest.raises(ValueError):
        WakeDetection(phrase, .9, identity)


def test_hardware_template_never_claims_execution_and_refuses_overwrite(tmp_path):
    owner = script('owner_voice_acceptance')
    target = tmp_path / 'evidence.json'
    assert owner.main(['--template', '--output', str(target)]) == 0
    report = json.loads(target.read_text())
    assert report['status'] == 'NOT TESTED'
    assert not report['consent_to_checklist'] and not report['script_opens_microphone']
    assert not report['retained_audio'] and not report['retained_transcripts']
    assert all(row['status'] == 'NOT TESTED' for row in report['checks'])
    assert all(set(row) == {'id', 'status'} for row in report['checks'])
    before = target.read_bytes()
    with pytest.raises(SystemExit):
        owner.main(['--template', '--output', str(target)])
    assert target.read_bytes() == before


def test_interactive_hardware_evidence_requires_consent(tmp_path, monkeypatch):
    owner = script('owner_voice_acceptance')
    monkeypatch.setattr(owner.sys.stdin, 'isatty', lambda: True)
    with pytest.raises(SystemExit):
        owner.main(['--interactive', '--output', str(tmp_path / 'no.json')])
    assert not (tmp_path / 'no.json').exists()


@pytest.mark.parametrize('values,expected', [([], 'NOT TESTED'), (['NOT TESTED'], 'NOT TESTED'),
    (['PASS', 'NOT TESTED'], 'PARTIAL'), (['PASS', 'PARTIAL'], 'PARTIAL'),
    (['PASS', 'FAIL'], 'FAIL'), (['PASS', 'PASS'], 'PASS')])
def test_owner_evidence_never_counts_unperformed_checks_as_passed(values, expected):
    assert script('owner_voice_acceptance').overall([{'status': v} for v in values]) == expected


def fixture(tmp_path, *, clips=False):
    data = io.BytesIO()
    with wave.open(data, 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\x40' * 6400)
    raw = data.getvalue()
    (tmp_path / 'sample.wav').write_bytes(raw)
    row = {'path': 'sample.wav', 'wav_sha256' if clips else 'sha256': hashlib.sha256(raw).hexdigest(), 'locale': 'en-US'}
    document = {'format': 1, 'kind': 'Recorded human read speech' if clips else 'synthetic',
                'license': 'CC-BY-4.0' if clips else 'Test fixture generated locally',
                'source' if clips else 'provenance': 'independent fixture', 'clips' if clips else 'files': [row]}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(document), encoding='utf-8')
    return path, document


@pytest.mark.parametrize('clips', [False, True])
def test_soak_accepts_integrity_checked_licensed_or_synthetic_manifest_only(tmp_path, clips):
    path, document = fixture(tmp_path, clips=clips)
    rows, provenance = script('voice_soak').load_fixtures(path)
    assert len(rows) == 1 and rows[0]['locale'] == 'en-US'
    assert set(provenance['files'][0]) == {'sha256', 'locale'}
    assert 'reference' not in provenance and 'audio' not in provenance
    assert provenance['manifest_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('mutation', ['hash', 'path', 'license', 'language', 'oversized'])
def test_soak_rejects_changed_or_unapproved_input_before_any_process(tmp_path, monkeypatch, mutation):
    path, document = fixture(tmp_path)
    row = document['files'][0]
    if mutation == 'hash':
        row['sha256'] = '0' * 64
    elif mutation == 'path':
        row['path'] = str((tmp_path / 'sample.wav').resolve())
    elif mutation == 'license':
        document['license'] = ''
    elif mutation == 'language':
        row['locale'] = 'invented'
    else:
        (tmp_path / 'sample.wav').write_bytes(b'0' * 700001)
    path.write_text(json.dumps(document), encoding='utf-8')
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Invalid input launched process'))
    with pytest.raises(ValueError):
        script('voice_soak').load_fixtures(path)


def test_memory_gate_requires_quiescent_samples_and_detects_growth():
    summary = script('voice_soak').memory_summary
    assert summary([], 3600)['status'] == 'NOT TESTED'
    rows = [{'quiescent': True, 'elapsed': t, 'backend_private_mib': 100} for t in (601, 800, 1100)]
    rows += [{'quiescent': True, 'elapsed': t, 'backend_private_mib': 180} for t in (3001, 3200, 3500)]
    assert summary(rows, 3600)['status'] == 'FAIL'
    for row in rows[3:]:
        row['backend_private_mib'] = 110
    assert summary(rows, 3600)['status'] == 'PASS'
    for row in rows[3:]:
        row['quiescent'] = False
    assert summary(rows, 3600)['status'] == 'NOT TESTED'


@pytest.mark.skipif(os.name != 'nt', reason='Actual Windows telemetry API required')
def test_soak_observes_and_cleans_only_its_owned_process():
    soak = script('voice_soak')
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(15)'],
                               creationflags=0x08000000, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        sampler = soak.ProcessSampler(process.pid)
        # Windows venv executables may keep a persistent interpreter child.
        time.sleep(.2)
        sampler.establish_baseline()
        row = sampler.sample()
        assert row['backend_private_mib'] > 0
        assert row['worker_count'] == 0
        assert process.pid in sampler.previously_seen_alive()
        assert os.getpid() not in sampler.previously_seen_alive()
        sampler.terminate_seen()
        assert process.wait(timeout=5) == 1
        assert sampler.previously_seen_alive() == []
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
