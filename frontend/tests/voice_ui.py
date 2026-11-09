"""Adversarial browser voice UI regression with explicitly simulated ASR replies.

Real Chromium, built React UI, local authentication and chat APIs are exercised.
Chromium's fake audio device is mandatory; no physical microphone is opened.
Recognition responses and device failures are fixtures, not accuracy evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import socket
import sys
import tempfile
import time

from playwright.async_api import async_playwright, expect

FRONTEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRONTEND.parent / 'sight'))
from sight_core.config import Config
from sight_core.desktop import BackendHost


async def main(output):
    checks, errors, calls = {}, [], []
    started = time.monotonic()
    pending = []
    mode = 'immediate'
    with tempfile.TemporaryDirectory(prefix='bel-voice-ui-') as directory:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        host = BackendHost(Config(Path(directory) / 'data', port=port, local_stt=True))
        try:
            launch = host.start()
            origin = launch.split('/#', 1)[0]
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=[
                    '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--mute-audio'])
                context = await browser.new_context(permissions=['microphone'], reduced_motion='reduce')

                async def network(route):
                    nonlocal mode
                    path = route.request.url.removeprefix(origin)
                    if not route.request.url.startswith(origin + '/'):
                        checks['no_external_requests'] = False
                        await route.abort(); return
                    if path == '/api/bel/status':
                        response = await route.fetch()
                        data = await response.json()
                        data['voice'].update({'stt_available': True, 'recording_supported': True,
                            'default_engine': 'whisper_cpp', 'locales': ['en-US', 'hi-IN', 'auto'],
                            'engines': [
                                {'id': 'whisper_cpp', 'label': 'whisper.cpp (test fixture)', 'available': True,
                                 'locales': ['en-US', 'hi-IN', 'auto'], 'reason': 'UI fixture only.'},
                                {'id': 'windows', 'label': 'Windows System.Speech', 'available': True,
                                 'locales': ['en-US'], 'reason': 'UI fixture only.'}]})
                        await route.fulfill(response=response, json=data); return
                    if path == '/api/speech/transcribe':
                        body = route.request.post_data_json
                        calls.append(('recognize', body['requestId']))
                        if mode == 'delayed':
                            release = asyncio.Event(); pending.append(release)
                            await release.wait()
                        await route.fulfill(json={'text': 'Untrusted fixture draft.', 'locale': body['locale'],
                            'confidence': None, 'confidence_kind': 'unavailable', 'engine': 'whisper.cpp fixture',
                            'engine_id': body['engine'], 'requested_engine': body['engine'], 'review_required': True})
                        return
                    if path == '/api/bel/chat':
                        calls.append(('chat', route.request.post_data_json['text']))
                    await route.continue_()

                checks['no_external_requests'] = True
                await context.route('**/*', network)
                await context.add_init_script("""(() => {
                    const devices = navigator.mediaDevices;
                    const original = devices.getUserMedia.bind(devices);
                    const enumerate = devices.enumerateDevices.bind(devices);
                    window.__voice = { mode: 'normal', calls: 0, enumerations: 0, streams: [] };
                    devices.enumerateDevices = async () => { window.__voice.enumerations++; return enumerate(); };
                    devices.getUserMedia = async options => {
                        window.__voice.calls++;
                        if (window.__voice.mode === 'deny') throw new DOMException('Fixture denied', 'NotAllowedError');
                        const stream = await original(options);
                        window.__voice.streams.push(stream);
                        if (window.__voice.mode === 'delayed') await new Promise(resolve => window.__voice.release = resolve);
                        return stream;
                    };
                })();""")
                page = await context.new_page()
                page.on('pageerror', lambda exc: errors.append(type(exc).__name__))
                await page.goto(launch, wait_until='networkidle')
                await expect(page.get_by_text('LOCALLY CONNECTED', exact=True)).to_be_visible()
                settings = page.get_by_role('button', name='Settings', exact=True)
                talk = page.get_by_role('button', name='Hold to talk', exact=True)
                message = page.get_by_role('textbox', name='Message BEL', exact=True)
                draft = page.get_by_role('textbox', name='Speech transcript', exact=True)
                await settings.click()
                checks['no_capture_or_enumeration_before_consent'] = await page.evaluate('window.__voice.calls === 0 && window.__voice.enumerations === 0')
                await expect(page.get_by_label('Recognition engine', exact=True)).to_have_value('whisper_cpp')
                checks['preferred_engine_offered'] = True
                await page.get_by_role('switch', name='Microphone consent').click()
                await expect(page.get_by_role('switch', name='Microphone consent')).to_have_attribute('aria-checked', 'true')
                checks['consent_does_not_capture_or_enumerate'] = await page.evaluate('window.__voice.calls === 0 && window.__voice.enumerations === 0')
                await page.get_by_role('button', name='Close panel').click()
                await message.fill('Preserve typed text')

                async def start():
                    await talk.focus(); await page.keyboard.down('Space')

                async def stop():
                    await page.keyboard.up('Space')

                await page.evaluate("window.__voice.mode = 'deny'")
                await start(); await stop()
                await expect(page.get_by_text('Microphone permission was denied.', exact=False)).to_be_visible()
                checks['permission_denied_actionable'] = True
                checks['denied_never_looks_listening'] = await page.locator('.orb-stage--listening').count() == 0

                await page.evaluate("window.__voice.mode = 'delayed'")
                await start()
                await page.wait_for_timeout(300)
                await stop()
                await page.evaluate('window.__voice.release()')
                await page.wait_for_timeout(300)
                checks['late_permission_stream_released'] = await page.evaluate('window.__voice.streams.every(s => s.getTracks().every(t => t.readyState === "ended"))')
                checks['late_permission_never_transcribed'] = not calls

                await page.evaluate("window.__voice.mode = 'normal'")
                await start()
                await expect(page.locator('.orb-stage--listening')).to_be_visible()
                await page.wait_for_timeout(800)
                await stop()
                await expect(draft).to_have_value('Untrusted fixture draft.')
                checks['audio_devices_enumerated_after_granted_capture'] = await page.evaluate('window.__voice.enumerations > 0')
                checks['draft_does_not_overwrite_typed_input'] = await message.input_value() == 'Preserve typed text'
                checks['unknown_confidence_warning'] = await page.get_by_text('does not provide a calibrated confidence score', exact=False).is_visible()
                checks['no_automatic_chat'] = not any(kind == 'chat' for kind, _ in calls)
                checks['review_blocks_ordinary_send'] = await page.get_by_role('button', name='Send message', exact=True).is_disabled()
                await message.press('Enter')
                checks['enter_does_not_bypass_review'] = not any(kind == 'chat' for kind, _ in calls)
                await draft.fill('Corrected speech')
                await page.get_by_role('button', name='Switch to compact mode').click()
                checks['compact_keeps_editable_review'] = await draft.is_visible()
                await page.get_by_role('button', name='Return to full window').click()
                await page.get_by_role('button', name='Discard speech draft').click()
                checks['discard_preserves_typed_input'] = await message.input_value() == 'Preserve typed text'

                mode = 'delayed'
                await start(); await page.wait_for_timeout(800); await stop()
                await expect(page.get_by_role('button', name='DISCARD TRANSCRIPT', exact=True)).to_be_visible()
                await page.get_by_role('button', name='DISCARD TRANSCRIPT', exact=True).click()
                for event in pending: event.set()
                await expect(talk).to_be_enabled()
                await page.wait_for_timeout(200)
                checks['cancelled_late_response_not_reviewed'] = await draft.count() == 0 and await message.input_value() == 'Preserve typed text'
                mode = 'immediate'

                await start(); await page.wait_for_timeout(400)
                await page.evaluate("window.dispatchEvent(new CustomEvent('bel-native-mode', {detail: {mode: 'background'}}))")
                await stop()
                checks['native_background_stops_tracks'] = await page.evaluate('window.__voice.streams.every(s => s.getTracks().every(t => t.readyState === "ended"))')
                checks['native_background_not_listening'] = await page.locator('.orb-stage--listening').count() == 0
                await page.evaluate("window.dispatchEvent(new CustomEvent('bel-native-mode', {detail: {mode: 'active'}}))")

                await start(); await page.wait_for_timeout(400)
                await page.evaluate("navigator.mediaDevices.dispatchEvent(new Event('devicechange'))")
                await stop()
                checks['device_change_stops_capture_safely'] = await page.evaluate('window.__voice.streams.every(s => s.getTracks().every(t => t.readyState === "ended"))')
                checks['interruption_preserves_typed_input'] = await message.input_value() == 'Preserve typed text'

                await start(); await page.wait_for_timeout(800); await stop()
                await expect(draft).to_be_visible()
                await message.fill(''); await draft.fill('help')
                await page.get_by_role('button', name='Send reviewed message').click()
                await expect(page.locator('.conversation-line--bel')).to_contain_text("BEL's local core is running", timeout=20000)
                checks['explicit_send_uses_real_chat_once'] = [value for kind, value in calls if kind == 'chat'] == ['help']
                checks['capture_ids_unique'] = len({value for kind, value in calls if kind == 'recognize'}) == sum(kind == 'recognize' for kind, _ in calls)
                checks['reduced_motion_applied'] = await page.locator('.app--reduced').count() == 1
                await start(); await page.wait_for_timeout(300)
                await page.evaluate("window.dispatchEvent(new Event('pagehide'))")
                await stop()
                checks['page_hide_releases_audio_tracks'] = await page.evaluate('window.__voice.streams.every(s => s.getTracks().every(t => t.readyState === "ended"))')
                checks['no_runtime_errors'] = not errors
                await context.close(); await browser.close()
        except Exception as exc:
            checks['harness_completed'] = False
            errors.append(type(exc).__name__ + ': ' + str(exc)[:1000])
        finally:
            for event in pending: event.set()
            host.stop()
            checks['backend_shutdown'] = host.thread is None or not host.thread.is_alive()
    result = {'kind': 'Browser reliability regression; simulated ASR and device failure fixtures',
              'physical_microphone_tested': False, 'recognition_accuracy_tested': False,
              'checks': checks, 'errors': errors, 'passed': sum(checks.values()), 'total': len(checks),
              'elapsed_seconds': round(time.monotonic() - started, 3)}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream: json.dump(result, stream, indent=2)
    print(json.dumps({key: result[key] for key in ('passed', 'total', 'elapsed_seconds')}))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    raise SystemExit(asyncio.run(main(parser.parse_args().output.resolve())))
