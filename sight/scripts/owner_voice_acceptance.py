"""Owner-attested hardware checklist. This script never records audio.

Run --template for an entirely NOT TESTED evidence form, or --interactive
--consent to walk through manual tests in BEL. Only fixed statuses are stored;
no device names, recordings, transcripts or free-text answers are collected.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STATUSES = ('PASS', 'PARTIAL', 'FAIL', 'NOT TESTED')
CHECKS = (
    ('disabled_startup', 'Start BEL normally. Confirm no microphone indicator and no listening orb before enabling voice.'),
    ('permission_denied', 'Enable voice, deny the Windows/browser microphone prompt, and start hold-to-talk. Confirm a clear error and no listening indicator.'),
    ('explicit_permission', 'Allow microphone permission in Windows/browser settings. Explicitly enable voice and hold-to-talk. Confirm capture starts only while requested.'),
    ('enumeration', 'After permission, inspect the microphone selector. Confirm available devices and the default option match your hardware.'),
    ('level_feedback', 'Speak a harmless test phrase while holding the control. Confirm the listening indicator and level feedback; release to stop.'),
    ('review_only', 'Confirm an editable speech draft appears, without a sent message, tool invocation or computer action.'),
    ('edit_send', 'Correct the harmless draft, then deliberately press Send reviewed message. Confirm only the reviewed content is sent once.'),
    ('discard_preserves_typing', 'Type a separate draft, dictate another phrase, and Discard speech draft. Confirm the original typed text remains.'),
    ('silence', 'Record silence in a quiet room. Confirm no misleading confident transcript or automatic submission appears.'),
    ('duration_limit', 'Keep hold-to-talk active for over 20 seconds. Confirm capture stops at its limit and releases the microphone.'),
    ('rapid_cancellation', 'Repeat start/stop/cancel five times. Confirm no stuck capture, stale draft or lost typed text.'),
    ('device_change', 'Switch to another available input and record a harmless phrase. Confirm no crash. If only one input exists, mark NOT TESTED.'),
    ('device_disappearance', 'While recording with a removable microphone, disconnect it. Confirm capture stops with a clear error and typing still works. Otherwise mark NOT TESTED.'),
    ('permission_revocation', 'Revoke microphone permission during a capture. Confirm capture stops and cannot restart until explicitly permitted again.'),
    ('closure_cleanup', 'Close the capturing window/tab. Confirm the Windows microphone-use indicator clears and no recognition process remains stuck.'),
    ('background_cleanup', 'Start capture, then hide/minimize BEL. Confirm capture is interrupted and the orb does not falsely indicate listening.'),
    ('restart_consent', 'Exit BEL fully and restart. Confirm microphone consent is off again and typing works normally.'),
    ('acoustic_echo', 'With benign speaker playback at normal volume, check whether recognition includes speaker echo. Mark PARTIAL if uncertain; browser constraints alone are not proof.'),
)


def identity(executable=None):
    paths = [Path(executable)] if executable else [ROOT / 'sight_core/local_speech.py', ROOT / 'pyproject.toml']
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def new_evidence(build):
    return {'format': 1, 'kind': 'Owner-attested physical hardware checklist; not automated measurement',
            'created_utc': datetime.now(timezone.utc).isoformat(), 'build_sha256': build,
            'script_opens_microphone': False, 'retained_audio': False, 'retained_transcripts': False,
            'consent_to_checklist': False, 'status': 'NOT TESTED',
            'checks': [{'id': key, 'status': 'NOT TESTED'} for key, _ in CHECKS]}


def overall(rows):
    values = [row['status'] for row in rows]
    if any(value not in STATUSES for value in values):
        raise ValueError('Unknown acceptance status')
    if 'FAIL' in values:
        return 'FAIL'
    if values and all(value == 'PASS' for value in values):
        return 'PASS'
    if any(value != 'NOT TESTED' for value in values):
        return 'PARTIAL'
    return 'NOT TESTED'


def write_new(path, evidence):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as output:
        json.dump(evidence, output, indent=2)
        output.write('\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--template', action='store_true')
    mode.add_argument('--interactive', action='store_true')
    parser.add_argument('--consent', action='store_true', help='Explicit consent to perform this manual hardware checklist')
    parser.add_argument('--executable', type=Path, help='Optional exact BEL.exe to identify by SHA-256')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('Evidence already exists; choose a new output path')
    if args.interactive and (not args.consent or not sys.stdin.isatty() or os.name != 'nt'):
        parser.error('Interactive hardware checks require Windows, a terminal and explicit --consent')
    evidence = new_evidence(identity(args.executable))
    if args.interactive:
        print('This script does not launch BEL or capture audio. Perform each step yourself in the exact identified build.')
        print('Use harmless phrases. Do not paste recordings, transcripts, device names or credentials here.')
        print('Answers: p=PASS, l=PARTIAL, f=FAIL, n=NOT TESTED, q=stop and save. These are owner observations.')
        evidence['consent_to_checklist'] = True
        began = time.monotonic()
        try:
            for row, (_, instruction) in zip(evidence['checks'], CHECKS):
                print('\n' + instruction)
                while True:
                    answer = input('[p/l/f/n/q]: ').strip().lower()
                    if answer in {'p', 'l', 'f', 'n', 'q'}:
                        break
                    print('Enter one of p, l, f, n or q; free text is not stored.')
                if answer == 'q':
                    break
                row['status'] = {'p': 'PASS', 'l': 'PARTIAL', 'f': 'FAIL', 'n': 'NOT TESTED'}[answer]
                row['observed_utc'] = datetime.now(timezone.utc).isoformat()
        except (KeyboardInterrupt, EOFError):
            pass
        evidence['elapsed_seconds'] = round(time.monotonic() - began, 3)
        evidence['status'] = overall(evidence['checks'])
    write_new(args.output, evidence)
    print(json.dumps({'status': evidence['status'], 'checks': len(evidence['checks']), 'kind': evidence['kind']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
