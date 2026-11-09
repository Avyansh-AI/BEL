"""Evaluation integrity checks; these do not qualify speech recognition quality."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def load(name):
    path = Path(__file__).resolve().parents[1] / 'scripts' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


benchmark = load('benchmark_speech')
provision = load('provision_speech_corpus')


def test_word_and_character_errors_use_independent_reference():
    result = benchmark.score('one two three', 'one four')
    assert result['word_edits'] == 2
    assert result['reference_words'] == 3
    assert result['character_edits'] == 6
    assert result['reference_characters'] == 11


def test_normalization_retains_hindi_marks_and_does_not_expand_digits():
    assert benchmark.normalize('नमस्ते! सुबह १०:३०।') == 'नमस्ते सुबह १० ३०'
    assert benchmark.score('twenty five', '25')['word_edits'] == 2
    assert benchmark.normalize("Don't stop.") == "don t stop"


def test_recognition_failure_counts_full_deletions():
    result = benchmark.score('one two three', '')
    assert result['word_edits'] == result['reference_words'] == 3
    assert result['character_edits'] == result['reference_characters'] == 11


def test_noise_is_reproducible_bounded_and_changes_signal():
    original = benchmark.wav([1000, -1000] * 1600)
    first = benchmark.noisy(original, 'fixed-clip')
    assert first == benchmark.noisy(original, 'fixed-clip')
    assert first != original
    assert len(benchmark.pcm(first)) == 3200
    assert first != benchmark.noisy(original, 'another-clip')


def test_successful_audio_resumes_without_second_download(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(provision, 'fetch', lambda *args, **kwargs: calls.append(args) or b'licensed audio')
    first = provision.AudioBudget(tmp_path)
    assert first.read_or_fetch('clean-1-2-3.flac', 'https://huggingface.co/sample') == b'licensed audio'
    assert first.data['charged_bytes'] == len(b'licensed audio')
    resumed = provision.AudioBudget(tmp_path)
    assert resumed.read_or_fetch('clean-1-2-3.flac', 'https://huggingface.co/sample') == b'licensed audio'
    assert len(calls) == 1


def test_failed_transfer_is_charged_across_resume(tmp_path, monkeypatch):
    def failure(*args, **kwargs): raise OSError('interrupted transfer')
    monkeypatch.setattr(provision, 'fetch', failure)
    first = provision.AudioBudget(tmp_path)
    with pytest.raises(OSError): first.read_or_fetch('clean-1-2-3.flac', 'https://huggingface.co/sample')
    assert provision.AudioBudget(tmp_path).data['charged_bytes'] == 2_000_000
    assert provision.AudioBudget(tmp_path).data['failed_transfer_reserved_bytes'] == 2_000_000


def test_tampered_retained_audio_rejected_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, 'fetch', lambda *args, **kwargs: b'licensed audio')
    budget = provision.AudioBudget(tmp_path)
    budget.read_or_fetch('clean-1-2-3.flac', 'https://huggingface.co/sample')
    (tmp_path / 'clean-1-2-3.flac').write_bytes(b'changed audio!')
    monkeypatch.setattr(provision, 'fetch', lambda *args, **kwargs: pytest.fail('Unexpected re-download'))
    with pytest.raises(ValueError, match='changed'):
        provision.AudioBudget(tmp_path).read_or_fetch('clean-1-2-3.flac', 'https://huggingface.co/sample')


def test_exhausted_budget_never_contacts_network(tmp_path, monkeypatch):
    budget = provision.AudioBudget(tmp_path)
    budget.data['charged_bytes'] = provision.LIMIT
    provision.write_json(budget.path, budget.data)
    monkeypatch.setattr(provision, 'fetch', lambda *args, **kwargs: pytest.fail('Cap exceeded'))
    with pytest.raises(ValueError, match='exhausted'):
        provision.AudioBudget(tmp_path).read_or_fetch('clean-1-2-3.flac', 'https://huggingface.co/sample')


def corpus(tmp_path):
    raw = benchmark.wav([1000, -1000] * 1600)
    path = tmp_path / 'example.wav'
    path.write_bytes(raw)
    return {'format': 1, 'clips': [{'split': 'clean', 'id': '1-2-3', 'path': path.name,
                                  'wav_sha256': hashlib.sha256(raw).hexdigest()}]}


def test_corpus_hashes_checked_before_recognition(tmp_path):
    manifest = corpus(tmp_path)
    benchmark.validate_corpus(tmp_path, manifest)
    (tmp_path / 'example.wav').write_bytes(b'bad')
    with pytest.raises(ValueError, match='hash or path'):
        benchmark.validate_corpus(tmp_path, manifest)


def test_duplicate_corpus_entries_cannot_inflate_score(tmp_path):
    manifest = corpus(tmp_path)
    manifest['clips'] *= 2
    with pytest.raises(ValueError, match='Duplicate'):
        benchmark.validate_corpus(tmp_path, manifest)


def test_corpus_parent_escape_rejected(tmp_path):
    root = tmp_path / 'corpus'; root.mkdir()
    manifest = corpus(tmp_path)
    manifest['clips'][0]['path'] = '../example.wav'
    with pytest.raises(ValueError, match='hash or path'):
        benchmark.validate_corpus(root, manifest)


def test_completed_corpus_is_never_overwritten(tmp_path):
    (tmp_path / 'manifest.json').write_text(json.dumps({'format': 1}))
    with pytest.raises(ValueError, match='immutable'):
        provision.provision(tmp_path, tmp_path / 'missing-deps', 40)
