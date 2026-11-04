"""Real Chromium + real BEL HTTP/WebSocket acceptance, with isolated synthetic data.

This harness does not simulate model answers or grant native desktop permissions.
The 'help' request is the backend's built-in response. Native tray/microphone/model
acceptance is deliberately a separate test.
"""
from __future__ import annotations
import json
from pathlib import Path
import socket
import sys
import tempfile
import time

FRONTEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRONTEND.parent / 'sight'))
from sight_core.config import Config
from sight_core.desktop import BackendHost
from playwright.sync_api import sync_playwright, expect


def wait_js(page, expression, timeout=5):
    # wait_for_function's string polling uses eval inside the renderer and is
    # correctly blocked by BEL's strict CSP. DevTools evaluation needs no bypass.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate(expression):
            return
        page.wait_for_timeout(50)
    raise AssertionError('UI condition did not settle: ' + expression)


def main():
    output = FRONTEND / 'test-results' / time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    output.mkdir(parents=True, exist_ok=False)
    checks, errors, external = {}, [], []
    started = time.monotonic()
    report = {'kind': 'real Chromium plus real local API/WS; synthetic test data', 'checks': checks,
              'model_inference_tested': False, 'microphone_tested': False, 'native_tray_tested': False}
    with tempfile.TemporaryDirectory(prefix='bel-ui-test-') as directory:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        host = BackendHost(Config(Path(directory) / 'data', port=port))
        try:
            launch = host.start()
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={'width': 1100, 'height': 800}, reduced_motion='reduce')
                def network(route):
                    if not route.request.url.startswith(f'http://127.0.0.1:{port}/'):
                        external.append(route.request.url.split('?')[0]); route.abort()
                    else:
                        route.continue_()
                context.route('**/*', network)
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)[:300]))
                page.goto(launch, wait_until='networkidle')
                expect(page.get_by_text('LOCALLY CONNECTED', exact=True)).to_be_visible(timeout=20000)
                checks['authenticated_bootstrap'] = True
                checks['fragment_removed'] = '#' not in page.url
                checks['title'] = page.title() == 'BEL — Behavioral Executive Logic'
                checks['official_logo_loaded'] = page.locator('.brand-mark').evaluate('(el) => el.complete && el.naturalWidth > 0')
                checks['local_fonts_loaded'] = page.evaluate("document.fonts.check('400 16px \"DM Sans Variable\"') && document.fonts.check('400 16px \"Manrope Variable\"')")
                expect(page.get_by_role('button', name='Hold to talk')).to_be_disabled()
                checks['microphone_disabled_without_stt'] = True
                expect(page.get_by_role('button', name='Minimize to tray')).to_be_disabled()
                checks['native_only_controls_disabled_in_browser'] = True
                page.get_by_role('textbox', name='Message BEL').fill('help')
                page.get_by_role('button', name='Send message', exact=True).click()
                expect(page.locator('.conversation-line--bel')).to_contain_text("BEL's local core is running", timeout=20000)
                checks['actual_http_chat'] = True
                page.get_by_role('button', name='Conversation history', exact=True).click()
                dialog = page.get_by_role('dialog', name='Conversation history')
                expect(dialog.locator('.history-item')).to_have_count(2)
                checks['persistent_history_visible'] = True
                page.get_by_role('button', name='Close panel').click()
                page.reload(wait_until='networkidle')
                expect(page.get_by_text('LOCALLY CONNECTED', exact=True)).to_be_visible()
                expect(page.locator('.conversation-line--bel')).to_contain_text("BEL's local core is running")
                checks['history_survives_page_reload'] = True
                page.get_by_role('button', name='Settings', exact=True).click()
                page.get_by_role('button', name='Memory management').click()
                page.get_by_role('textbox', name='Memory key').fill('ui.smoke')
                page.get_by_role('textbox', name='Memory content').fill('The synthetic UI fixture prefers blue.')
                page.get_by_role('button', name='Review memory', exact=True).click()
                expect(page.get_by_role('dialog', name='Confirm action')).to_contain_text('ui.smoke')
                checks['human_confirmation_shows_exact_memory'] = True
                page.get_by_role('button', name='Cancel', exact=True).click()
                expect(page.locator('.memory-item')).to_have_count(0)
                checks['cancelled_preview_has_no_effect'] = True
                page.get_by_role('button', name='Review memory', exact=True).click()
                page.get_by_role('button', name='Approve once', exact=True).click()
                expect(page.locator('.memory-item')).to_contain_text('prefers blue')
                checks['approved_memory_persists'] = True
                page.get_by_role('button', name='Correct', exact=True).click()
                page.get_by_role('textbox', name='Memory content').fill('The synthetic UI fixture prefers green.')
                page.get_by_role('button', name='Review memory', exact=True).click()
                page.get_by_role('button', name='Approve once', exact=True).click()
                expect(page.locator('.memory-item')).to_contain_text('prefers green')
                checks['memory_correction'] = True
                page.get_by_role('button', name='Review deletion', exact=True).click()
                page.get_by_role('button', name='Approve once', exact=True).click()
                expect(page.locator('.memory-item')).to_have_count(0)
                checks['memory_deletion'] = True
                page.get_by_role('button', name='Close panel').click()
                page.get_by_role('button', name='Settings', exact=True).click()
                page.get_by_role('button', name='AI providers', exact=True).click()
                expect(page.get_by_role('combobox', name='AI provider')).to_have_value('groq')
                expect(page.get_by_text('This panel only permits free use.', exact=False)).to_be_visible()
                checks['provider_policy_loaded_without_mutation'] = True
                page.get_by_role('button', name='Close panel').click()
                page.get_by_role('button', name='Settings', exact=True).click()
                page.get_by_role('button', name='Tools and undo', exact=True).click()
                page.get_by_role('combobox', name='Registered tool').select_option('files.create')
                page.get_by_role('textbox', name='Tool arguments').fill('["invalid"]')
                page.get_by_role('button', name='Review tool action', exact=True).click()
                expect(page.get_by_role('alert')).to_contain_text('Enter a JSON object')
                checks['invalid_tool_args_have_no_preview'] = page.get_by_role('dialog', name='Confirm action').count() == 0
                target = Path(directory) / 'data/files/ui-reviewed.txt'
                page.get_by_role('textbox', name='Tool arguments').fill(json.dumps({'name': 'ui-reviewed.txt', 'content': 'Reviewed UI fixture\n'}))
                page.get_by_role('button', name='Review tool action', exact=True).click()
                expect(page.get_by_role('dialog', name='Confirm action')).to_contain_text('ui-reviewed.txt')
                checks['tool_preview_has_no_file_side_effect'] = not target.exists()
                page.get_by_role('button', name='Approve once', exact=True).click()
                expect(page.get_by_role('button', name='Review undo', exact=True)).to_be_enabled(timeout=20000)
                checks['reviewed_file_created'] = target.read_bytes() == b'Reviewed UI fixture\n'
                checks['undo_list_refreshes_after_execution'] = True
                page.get_by_role('button', name='Review undo', exact=True).click()
                expect(page.get_by_role('dialog', name='Confirm action')).to_contain_text('undo_id')
                expect(page.get_by_role('dialog', name='Confirm action')).to_contain_text('ui-reviewed.txt')
                checks['undo_preview_identifies_file'] = True
                checks['undo_preview_has_no_file_side_effect'] = target.is_file()
                with page.expect_response(lambda response: response.url.endswith('/api/bel/tools/execute') and response.request.method == 'POST', timeout=20000) as undo_response:
                    page.get_by_role('button', name='Approve once', exact=True).click()
                outcome = undo_response.value.json()
                checks['undo_backend_reports_verified_result'] = outcome.get('status') == 'done'
                expect(page.get_by_text('No verified file action is available to undo.', exact=True)).to_be_visible(timeout=20000)
                checks['reviewed_file_undo'] = not target.exists()
                page.get_by_role('button', name='Close panel').click()
                expect(page.get_by_role('dialog')).to_have_count(0)
                report['layout'] = page.evaluate("Object.fromEntries(['html','body','#root','.app','.topbar','.orb-stage','.input-area'].map(s=>{const e=document.querySelector(s),r=e.getBoundingClientRect();return[s,{x:r.x,width:r.width,scrollLeft:e.scrollLeft,scrollWidth:e.scrollWidth,transform:getComputedStyle(e).transform}]}))")
                checks['active_orb_centered'] = abs(report['layout']['.orb-stage']['x'] + report['layout']['.orb-stage']['width'] / 2 - 550) < 2
                page.screenshot(path=str(output / 'active.png'))
                page.get_by_role('button', name='Switch to compact mode').click()
                expect(page.locator('.app--compact')).to_be_visible()
                wait_js(page, "document.querySelector('.input-area').getBoundingClientRect().width < document.querySelector('.app').getBoundingClientRect().width")
                checks['compact_mode'] = True
                page.screenshot(path=str(output / 'compact.png'))
                page.set_viewport_size({'width': 380, 'height': 480})
                wait_js(page, "getComputedStyle(document.querySelector('.presence-label')).display === 'none'")
                compact_input = page.get_by_role('textbox', name='Message BEL').bounding_box()
                checks['native_compact_input_in_view'] = compact_input['x'] >= 0 and compact_input['y'] >= 0 and compact_input['x'] + compact_input['width'] <= 380 and compact_input['y'] + compact_input['height'] <= 480
                checks['native_compact_content_does_not_overlap_header'] = page.evaluate("document.querySelector('.orb-stage').getBoundingClientRect().top >= document.querySelector('.topbar').getBoundingClientRect().bottom")
                page.screenshot(path=str(output / 'native-compact-layout.png'))
                page.get_by_role('button', name='Return to full window').click()
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(output / 'mobile.png'))
                bounds = page.get_by_role('textbox', name='Message BEL').bounding_box()
                checks['mobile_input_in_view'] = bounds['x'] >= 0 and bounds['y'] >= 0 and bounds['x'] + bounds['width'] <= 390 and bounds['y'] + bounds['height'] <= 844
                checks['mobile_no_horizontal_overflow'] = page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.get_by_role('button', name='Settings', exact=True).click()
                page.get_by_role('button', name='Tools and undo', exact=True).click()
                expect(page.get_by_role('heading', name='Tools and undo', exact=True)).to_be_visible()
                wait_js(page, "getComputedStyle(document.querySelector('.overlay-card')).opacity === '1' && getComputedStyle(document.querySelector('.overlay-backdrop')).opacity === '1'")
                page.screenshot(path=str(output / 'mobile-tools.png'))
                page.get_by_role('textbox', name='Tool arguments').focus()
                page.keyboard.press('Escape')
                expect(page.get_by_role('dialog')).to_have_count(0)
                checks['mobile_modal_keyboard_close'] = True
                page.set_viewport_size({'width': 1100, 'height': 800})
                page.get_by_role('button', name='Conversation history', exact=True).click()
                page.get_by_role('button', name='Review clearing history').click()
                page.get_by_role('button', name='Approve once', exact=True).click()
                expect(page.locator('.history-item')).to_have_count(0)
                checks['approved_history_clear'] = True
                page.get_by_role('button', name='Close panel').click()
                checks['no_external_network_requests'] = not external
                checks['no_javascript_errors'] = not errors
                browser.close()
            report['status'] = 'PASS' if all(checks.values()) else 'FAIL'
        except Exception as exc:
            report['status'] = 'FAIL'
            report['failure'] = type(exc).__name__ + ': ' + str(exc)[:1200]
        finally:
            host.stop()
            report.update(seconds=round(time.monotonic() - started, 3), errors=errors, external=external)
            (output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(output / 'result.json'), **report}, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
