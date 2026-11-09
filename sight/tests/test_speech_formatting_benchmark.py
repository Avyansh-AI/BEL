"""Integrity of supplemental metrics/fixtures, not recognition acceptance."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / 'scripts/benchmark_speech_formatting.py'
spec = importlib.util.spec_from_file_location('benchmark_speech_formatting', path)
formatting = importlib.util.module_from_spec(spec)
spec.loader.exec_module(formatting)


def test_numeric_tokens_preserve_sign_currency_decimal_time_and_ordinals():
    expected = 'At 9:30, pay $19.95 for 12 items; the 3rd box is -5 degrees.'
    result = formatting.formatting_score(expected, expected)
    assert result['numeric_reference_tokens'] == 5
    assert result['numeric_position_matches'] == 5
    assert result['numeric_sequence_exact'] is True
    assert result['punctuation_reference_marks'] == 3
    assert result['punctuation_sequence_exact'] is True


def test_written_number_metric_does_not_treat_spoken_words_as_digits():
    result = formatting.formatting_score('Buy 12 apples.', 'Buy twelve apples.')
    assert result['numeric_sequence_exact'] is False
    assert result['numeric_position_matches'] == 0
    assert result['numeric_observed_tokens'] == 0
    assert result['punctuation_sequence_exact'] is True


def test_extra_numbers_and_changed_order_fail_exact_sequence():
    assert formatting.formatting_score('Buy 12 apples.', 'Buy 12 apples and 3 pears.')['numeric_sequence_exact'] is False
    result = formatting.formatting_score('Buy 12 apples and 3 pears.', 'Buy 3 apples and 12 pears.')
    assert result['numeric_sequence_exact'] is False
    assert result['numeric_position_matches'] == 0


def test_punctuation_metric_ignores_numeric_separators_but_retains_sentence_marks():
    result = formatting.formatting_score('At 9:30, pay $1,250.50.', 'At 9:30 pay $1,250.50?')
    assert result['numeric_sequence_exact'] is True
    assert result['punctuation_reference_marks'] == 2
    assert result['punctuation_observed_marks'] == 1
    assert result['punctuation_sequence_exact'] is False


def test_failed_recognition_scores_missing_numbers_and_punctuation():
    result = formatting.formatting_score('Send 3 books?', '')
    assert result['numeric_sequence_exact'] is False
    assert result['punctuation_sequence_exact'] is False
    assert formatting.score('Send three books?', '')['word_edits'] == 3


def corpus(tmp_path):
    from benchmark_speech import wav
    rows = formatting.declared_cases()
    declaration = {'format': 1, 'cases': rows}
    declaration_raw = json.dumps(declaration).encode()
    (tmp_path / 'declaration.json').write_bytes(declaration_raw)
    raw = wav([1000, -1000] * 1600)
    manifest = {'format': 1, 'declaration_sha256': hashlib.sha256(declaration_raw).hexdigest(), 'cases': []}
    for row in rows:
        (tmp_path / row['path']).write_bytes(raw)
        manifest['cases'].append({**row, 'wav_sha256': hashlib.sha256(raw).hexdigest()})
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    return manifest


def test_declared_corpus_is_frozen_before_evaluation(tmp_path):
    corpus(tmp_path)
    manifest, digest = formatting.validate_corpus(tmp_path)
    assert len(manifest['cases']) == 24
    assert len(digest) == 64
    assert len({row['id'] for row in manifest['cases']}) == 24


def test_edited_reference_rejected_even_if_manifest_remains_well_formed(tmp_path):
    manifest = corpus(tmp_path)
    manifest['cases'][0]['written_reference'] = 'Recognition output changed this expected answer.'
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='reference changed'):
        formatting.validate_corpus(tmp_path)


def test_replaced_audio_rejected_before_recognition(tmp_path):
    manifest = corpus(tmp_path)
    (tmp_path / manifest['cases'][0]['path']).write_bytes(b'changed waveform')
    with pytest.raises(ValueError, match='audio changed'):
        formatting.validate_corpus(tmp_path)


def test_removed_corpus_case_cannot_inflate_reported_accuracy(tmp_path):
    manifest = corpus(tmp_path)
    manifest['cases'].pop()
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='reference set changed'):
        formatting.validate_corpus(tmp_path)


def test_empty_summary_has_no_fabricated_accuracy():
    result = formatting.summarize([])
    assert result['cases'] == 0
    assert result['numeric_position_exact_rate'] is None
    assert result['punctuation_sequence_exact_rate'] is None
    assert result['spoken_wer'] is None
    assert result['written_cer'] is None
