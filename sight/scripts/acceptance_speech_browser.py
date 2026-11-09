"""Live BEL browser/audio/API acceptance with Chromium's synthetic audio device.

Never opens a physical microphone: fake-device/file switches are mandatory, and
all output is muted. Browser capture and Windows recognition remain real. This is
not evidence of native WebView2 permission prompts or physical-device quality.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import uuid
import wave

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sight_core.config import Config
from sight_core.desktop import BackendHost
from acceptance_local_speech import free_port


def run(fixture, engine='windows'):
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    cache = ROOT.parent / '.cache' / ('speech-browser-' + run_id)
    cache.mkdir(parents=True)
    with wave.open(str(fixture), 'rb') as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000):
            raise ValueError('Fixture must be synthetic mono 16 kHz PCM')
        frames = source.readframes(source.getnframes())
    padded = cache / 'fake-microphone.wav'
    with wave.open(str(padded), 'wb') as target:
        target.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        target.writeframes(b'\0' * 32000 + frames + b'\0' * 160000)
    sources = [ROOT / 'sight_core' / name for name in ('api.py', 'local_speech.py', 'speech_worker.py')]
    sources += sorted((ROOT.parent / 'frontend' / 'dist').rglob('*.js'))
    hashes = {p.relative_to(ROOT.parent).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    data = cache / 'data'
    host = BackendHost(Config(data, port=free_port(), local_stt=True))
    checks, calls, page_errors = [], [], []
    blocked_external = []
    response_codes = []
    observed_transcript = ''
    started = time.monotonic()
    result = {'format': 1, 'kind': 'Real headless Chromium capture and HTTP/local speech, synthetic audio device',
              'requested_engine': engine,
              'run_id': run_id, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'physical_microphone_access': False, 'audible_playback': False,
              'input_mode': 'Chromium --use-fake-device-for-media-stream plus local synthetic PCM WAV',
              'source_sha256': hashes, 'checks': checks,
              'limitations': ['Synthetic browser device only; physical microphone and accent quality remain unverified.',
                              'Headless Chromium does not validate native WebView2 permission UI.',
                              'Wake-word detection and Hindi voice input are not validated.']}

    def check(name, passed, **details):
        checks.append({'id': name, 'passed': bool(passed), **details})

    try:
        launch = host.start()
        origin = launch.split('/#', 1)[0]
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=[
                '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
                '--use-file-for-fake-audio-capture=' + str(padded), '--mute-audio',
            ])
            result['chromium_version'] = browser.version
            context = browser.new_context(viewport={'width': 1100, 'height': 800}, permissions=['microphone'])

            def local_only(route):
                if route.request.url.startswith(origin + '/'):
                    route.continue_()
                else:
                    blocked_external.append(route.request.url.split('?', 1)[0])
                    route.abort()
            context.route('**/*', local_only)
            context.add_init_script("""(() => {
                const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
                window.__belCaptureAudit = { calls: 0, streams: [] };
                navigator.mediaDevices.getUserMedia = async constraints => {
                    window.__belCaptureAudit.calls++;
                    const stream = await original(constraints);
                    window.__belCaptureAudit.streams.push(stream);
                    return stream;
                };
            })();""")
            page = context.new_page()
            page.on('pageerror', lambda error: page_errors.append(type(error).__name__))
            page.on('request', lambda request: calls.append((request.method, request.url.split('?', 1)[0].removeprefix(origin))))
            page.on('response', lambda response: response_codes.append((response.url.removeprefix(origin), response.status)))
            page.goto(launch, wait_until='networkidle')
            page.evaluate("""() => {
                const orb = document.querySelector('.orb-stage');
                window.__belOrbStates = [orb.getAttribute('aria-label')];
                new MutationObserver(() => window.__belOrbStates.push(orb.getAttribute('aria-label')))
                    .observe(orb, { attributes: true, attributeFilter: ['aria-label'] });
            }""")
            settings = page.get_by_role('button', name='Settings', exact=True)
            settings.click()
            consent = page.get_by_role('switch', name='Microphone consent', exact=True)
            expect(consent).to_be_enabled()
            check('microphone_initially_off', consent.get_attribute('aria-checked') == 'false')
            check('no_automatic_capture', page.evaluate('window.__belCaptureAudit.calls') == 0)
            page.get_by_label('Recognition engine', exact=True).select_option(engine)
            choices = page.get_by_label('Dictation language').locator('option').evaluate_all('(options) => options.map(x => x.value)')
            check('engine_language_choices_match_support', 'en-US' in choices and ('auto' not in choices if engine == 'windows' else 'auto' in choices))
            page.get_by_label('Dictation language').select_option('en-US')
            consent.click()
            expect(consent).to_have_attribute('aria-checked', 'true')
            check('consent_alone_does_not_capture', page.evaluate('window.__belCaptureAudit.calls') == 0)
            page.get_by_role('button', name='Close panel').click()
            message = page.get_by_role('textbox', name='Message BEL', exact=True)
            message.fill('Existing draft: ')
            talk = page.get_by_role('button', name='Hold to talk', exact=True)
            expect(talk).to_be_enabled()
            talk.focus()
            page.keyboard.down('Space')
            page.wait_for_function('window.__belCaptureAudit.calls === 1')
            page.wait_for_timeout(6100)
            with page.expect_response(lambda response: response.url.endswith('/api/speech/transcribe'), timeout=120000) as heard:
                page.keyboard.up('Space')
            response = heard.value
            transcript = response.json()
            check('capture_reaches_real_local_recognizer', response.status == 200 and transcript.get('engine_id', 'windows') == engine)
            observed_transcript = transcript.get('text', '')
            draft = page.get_by_role('textbox', name='Speech transcript', exact=True)
            expect(draft).to_have_value(observed_transcript)
            current = message.input_value()
            check('typed_draft_preserved_and_speech_separately_editable', current == 'Existing draft: ' and draft.is_editable())
            check('review_required_and_low_confidence_visible', transcript.get('review_required') is True and
                  ('does not provide a calibrated confidence' in page.locator('body').inner_text() if transcript.get('confidence') is None else
                   'Low recognition confidence.' in page.locator('body').inner_text() if transcript['confidence'] < .7 else
                   'Review the transcription before sending.' in page.locator('body').inner_text()))
            check('normal_send_and_capture_blocked_during_review', page.get_by_role('button', name='Send message', exact=True).is_disabled() and talk.is_disabled())
            check('capture_tracks_stop_after_release', page.evaluate('window.__belCaptureAudit.streams.every(s => s.getTracks().every(t => t.readyState === "ended"))'))
            observed_states = page.evaluate('[...new Set(window.__belOrbStates)]')
            check('orb_tracks_capture_processing_and_review', all(state in observed_states for state in
                  ('Listening…', 'Processing speech locally…', 'Draft ready — awaiting your review')) and
                  page.get_by_role('img', name='Draft ready — awaiting your review', exact=True).is_visible())
            check('dictation_never_auto_sends', not any(method == 'POST' and path in
                  {'/api/utterance', '/api/chat', '/api/bel/chat', '/api/tools/execute',
                   '/api/bel/tools/execute', '/api/capability/invoke'} for method, path in calls))
            result['first_transcript'] = {'characters': len(observed_transcript), 'confidence': transcript.get('confidence'),
                                          'engine': transcript.get('engine'), 'review_required': transcript.get('review_required')}

            draft.fill('An edited transcript which must be discarded.')
            expect(page.get_by_role('img', name='Awaiting your review', exact=True)).to_be_visible()
            page.get_by_role('button', name='Discard speech draft', exact=True).click()
            check('discard_review_preserves_typed_draft', message.input_value() == current and draft.count() == 0)

            # Start a second real capture, then discard its pending recognition.
            # Existing draft must survive any late response or cancellation race.
            talk.focus()
            page.keyboard.down('Space')
            page.wait_for_function('window.__belCaptureAudit.calls === 2')
            page.wait_for_timeout(2200)
            page.keyboard.up('Space')
            discard = page.get_by_role('button', name='DISCARD TRANSCRIPT', exact=True)
            expect(discard).to_be_visible()
            with page.expect_response(lambda response: response.url.endswith('/api/speech/cancel'), timeout=30000) as cancelled:
                discard.click()
            check('discard_acknowledged_by_backend', cancelled.value.status == 200)
            expect(talk).to_be_enabled()
            page.wait_for_timeout(700)
            check('discarded_transcript_does_not_replace_draft', message.input_value() == current)
            check('all_synthetic_tracks_closed_after_stop', page.evaluate('window.__belCaptureAudit.streams.every(s => s.getTracks().every(t => t.readyState === "ended"))'))

            # A third capture is deliberately edited into BEL's built-in help
            # request. Only the visible review button may submit that text.
            talk.focus()
            page.keyboard.down('Space')
            page.wait_for_function('window.__belCaptureAudit.calls === 3')
            page.wait_for_timeout(6100)
            page.keyboard.up('Space')
            expect(draft).to_be_visible(timeout=120000)
            message.fill('')
            draft.fill('help')
            check('editing_speech_still_does_not_send', not any(method == 'POST' and path == '/api/bel/chat' for method, path in calls))
            page.get_by_role('button', name='Send reviewed message', exact=True).click()
            expect(page.locator('.conversation-line--bel')).to_contain_text("BEL's local core is running", timeout=20000)
            check('explicit_review_sends_once_through_existing_chat', sum(method == 'POST' and path == '/api/bel/chat' for method, path in calls) == 1)
            check('successful_submission_clears_review', draft.count() == 0 and message.input_value() == '')
            settings.click()
            consent.click()
            expect(consent).to_have_attribute('aria-checked', 'false')
            page.get_by_role('button', name='Close panel').click()
            check('revoking_consent_disables_capture_control', talk.is_disabled())
            page.get_by_role('button', name='Switch to compact mode', exact=True).click()
            check('compact_ui_still_available', page.get_by_role('button', name='Return to full window', exact=True).is_visible())
            check('no_external_browser_requests', not blocked_external, blocked_count=len(blocked_external))
            check('no_browser_runtime_errors', not page_errors, error_count=len(page_errors))
            page.screenshot(path=str(cache / 'dictation.png'))
            with sqlite3.connect(data / 'sight.sqlite3') as db:
                counts = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                          for table in ('requests', 'bel_executions', 'bel_history')}
            check('reviewed_builtin_help_left_no_tool_records', counts['bel_executions'] == 0 and counts['bel_history'] == 2, row_counts=counts)
            context.close()
            browser.close()
    except Exception as exc:
        check('browser_harness_completed', False, error_type=type(exc).__name__)
        (cache / 'failure.txt').write_text(str(exc), encoding='utf-8')
    finally:
        host.stop()
        check('backend_exited', host.thread is None or not host.thread.is_alive())
    check('source_unchanged', all(hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() == expected
                                 for name, expected in hashes.items()))
    (cache / 'transcript.txt').write_text(observed_transcript, encoding='utf-8')
    (cache / 'http-statuses.json').write_text(json.dumps(response_codes, indent=2), encoding='utf-8')
    result.update({'passed': sum(row['passed'] for row in checks), 'total': len(checks),
                   'elapsed_seconds': round(time.monotonic() - started, 3),
                   'completed_utc': datetime.now(timezone.utc).isoformat()})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--engine', choices=('windows', 'whisper_cpp'), default='windows')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Choose a new evidence path')
    result = run(args.fixture.resolve(), args.engine)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'passed': result['passed'], 'total': result['total'], 'evidence': str(args.output.resolve())}))
    return 0 if result['passed'] == result['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
