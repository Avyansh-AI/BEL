"""Fixed worker entry point. JSON input is data, never source code or shell text."""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import wave


def memory_snapshot():
    """Best-effort numeric host counters; no process names, paths or page data."""
    if os.name != 'nt':
        return {}
    try:
        import ctypes
        from ctypes import wintypes
        class Memory(ctypes.Structure):
            _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
                (name, ctypes.c_uint64) for name in ('total', 'available', 'commit_total', 'commit_available',
                                                    'virtual_total', 'virtual_available', 'extended')]
        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            return {}
        return {'total_ram_mib': memory.total // 2**20, 'available_ram_mib': memory.available // 2**20,
                'available_commit_mib': memory.commit_available // 2**20}
    except (OSError, AttributeError):
        return {}


class BrowserFailure(Exception):
    def __init__(self, code, stage):
        self.code = code
        self.diagnostics = {'stage': stage, 'resources': memory_snapshot()}
        super().__init__('Isolated browser operation failed')


def browser_failure(exc, stage, native=None, page=None):
    from playwright.sync_api import TimeoutError as BrowserTimeout
    message = str(exc)  # Classify only; never transmit or log the message.
    if stage == 'screenshot' and 'Page.captureScreenshot' in message and 'Unable to capture screenshot' in message:
        code = 'browser_capture_unavailable'
    elif isinstance(exc, BrowserTimeout):
        code = 'browser_timeout'
    elif (native is not None and not native.is_connected()) or (page is not None and page.is_closed()):
        code = 'browser_closed'
    else:
        code = 'browser_failed'
    return BrowserFailure(code, stage)


def failure_payload(exc):
    payload = {'error': 'Adapter failed', 'code': 'adapter_failed'}
    if isinstance(exc, BrowserFailure):
        payload.update(code=exc.code, diagnostics=exc.diagnostics)
    return payload


def browser(value):
    # Playwright otherwise defaults frozen applications to a bundled browser
    # directory even when only its driver was bundled. Reuse the owner's normal
    # installed cache; never download or silently attach to their browser.
    if getattr(sys, 'frozen', False) and os.name == 'nt' and 'PLAYWRIGHT_BROWSERS_PATH' not in os.environ:
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'ms-playwright')
    from playwright.sync_api import sync_playwright, Error
    stage = 'launch'
    failure = None
    native = page = None
    try:
        with sync_playwright() as p:
            try:
                native=p.chromium.launch(headless=True,chromium_sandbox=True)
                stage='context'
                context=native.new_context(java_script_enabled=False,service_workers='block',accept_downloads=False,offline=True,viewport={'width':1024,'height':768})
                blocked=[]
                def reject(route):blocked.append(route.request.resource_type);route.abort()
                context.route('**/*',reject)
                stage='page'
                page=context.new_page();page.set_default_timeout(2000)
                stage='content'
                page.set_content(value['html'],wait_until='domcontentloaded',timeout=5000)
                stage='fields'
                for identifier,text in value['fields'].items():page.locator('#'+identifier).fill(text)
                result={'title':page.title()[:200],'text':page.locator('body').inner_text()[:16000],
                        'fields':{identifier:page.locator('#'+identifier).input_value() for identifier in value['fields']}}
                stage='screenshot'
                result.update(screenshot=base64.b64encode(page.screenshot(timeout=5000)).decode(),
                              blocked_requests=len(blocked),untrusted_content=True,network_allowed=False,scripts_enabled=False,submitted=False)
                stage='cleanup'
                context.close()
            except Error as exc:
                failure=browser_failure(exc,stage,native,page)
            finally:
                if native is not None:
                    try:native.close()
                    except Error as exc:
                        if failure is None:failure=browser_failure(exc,'cleanup',native,page)
        if failure is not None:raise failure
        return result
    except Error as exc:
        # Preserve the first failure if driver teardown also fails.
        raise failure if failure is not None else browser_failure(exc,stage,native,page) from None

def speech(value):
    if os.name!='nt':raise ValueError('Windows SAPI required')
    executable=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    # No interpolation of user text into commands; fixed script reads UTF-8 JSON.
    script="$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Speech; $sightInput=[Console]::In.ReadToEnd() | ConvertFrom-Json; $sightVoice=New-Object System.Speech.Synthesis.SpeechSynthesizer; try { $sightVoice.SetOutputToWaveFile([string]$sightInput.path); $sightVoice.Speak([string]$sightInput.text) } finally { $sightVoice.Dispose() }"
    with tempfile.TemporaryDirectory(prefix='sight-speech-') as directory:
        path=Path(directory)/'voice.wav'
        subprocess.run([str(executable),'-NoProfile','-NonInteractive','-Command',script],input=json.dumps({'path':str(path),'text':value['text']}),text=True,capture_output=True,check=True,timeout=15,shell=False)
        if path.stat().st_size>8*1024**2:raise ValueError('Speech output too large')
        data=path.read_bytes()
        with wave.open(io.BytesIO(data)) as audio:duration=audio.getnframes()/audio.getframerate()
        return {'wav':base64.b64encode(data).decode(),'duration_seconds':duration,'engine':'Windows System.Speech','network_allowed':False,'played':False}

def main():
    raw=sys.stdin.buffer.read(100001)
    if len(raw)>100000:raise ValueError('Worker payload too large')
    value=json.loads(raw)
    handler={'browser.inspect':browser,'speech.render':speech}[value['id']]
    print(json.dumps(handler(value['arguments']),ensure_ascii=True))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps(failure_payload(exc)));sys.exit(1)
