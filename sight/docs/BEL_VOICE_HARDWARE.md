# Preview 2 voice hardware acceptance

Physical microphone capture, native permission dialogs, input-device removal and
acoustic echo protection require owner observation on the target Windows PC.
Synthetic audio and HTTP/browser fixtures cannot qualify these checks. Their
status remains **NOT TESTED** until the owner performs them. A requested browser
echo-cancellation constraint is not proof of effective acoustic echo reduction.

Use an isolated Preview 2 extraction and test profile. Keep the stable BEL 0.4.1
folder, ZIP and normal profile unchanged. Start the preview with its documented
`--local-dictation` switch; microphone consent still defaults off. Install only
the explicitly approved, integrity-verified local recognizer assets. Use harmless
phrases, never passwords or private content. The checklist itself never records,
launches BEL, enables a microphone, submits text or uploads evidence.

From a source checkout with the existing Python environment:

```powershell
.\sight\.venv\Scripts\python.exe .\sight\scripts\owner_voice_acceptance.py --template --output .\.cache\hardware-template.json
.\sight\.venv\Scripts\python.exe .\sight\scripts\owner_voice_acceptance.py --interactive --consent --executable 'C:\your-preview\BEL.exe' --output .\.cache\hardware-owner.json
```

The second command requires an interactive Windows terminal. Perform each
displayed instruction in BEL and enter a fixed status. Missing hardware is
`NOT TESTED`; uncertain or partly working behavior is `PARTIAL`. `q` or Ctrl+C
saves the completed observations with remaining checks untested. Existing
evidence files are never overwritten. The evidence identifies the executable
with SHA-256, stores fixed statuses and timings, and clearly labels the result
as **owner-attested**, not automatically instrumented verification. It contains
no recordings, transcripts, device names, hostname or free-text notes.

Checks cover startup off, permission denial/revocation, explicit capture,
enumeration, levels, reviewed draft and deliberate send, discard preserving
typed text, silence, recording limits, repeated cancellation, device switching
and disappearance, window/background cleanup, restart consent and acoustic echo.
Keep evidence private until reviewed. The checklist's send step deliberately
adds a harmless message to the isolated test profile; it must never run tools.

## Reproducible lifecycle stability test

`scripts/voice_soak.py` starts only its own isolated source backend or the exact
supplied frozen application. It accepts an integrity-checked synthetic or
licensed prerecorded WAV corpus, never opens a microphone, and sends no chat
messages or tool calls. A fresh data directory, owner sessions and CSRF checks
remain in force. Frozen mode enables a loopback-only debug port in that
disposable process to exercise its own window modes and close it cleanly.

```powershell
.\sight\.venv\Scripts\python.exe .\sight\scripts\voice_soak.py --seconds 3600 --engine whisper_cpp --asr-directory .\.cache\asr\whisper_cpp-b5454 --corpus .\.cache\preview2\corpus\manifest.json --output .\.cache\preview2\voice-soak.json
```

Add `--executable 'C:\your-preview\BEL.exe'` for frozen validation. Freeze the
source, compiled frontend and recognizer files before starting: any changes
invalidate the run. A short smoke run can use `--seconds 60`, but cannot pass the
hour gate. Startup and shutdown time do not count toward the required 3,600
seconds of lifecycle exercise. The test measures real recognition, replay and
session rejection, cancellation, consent revocation, child-process cleanup,
quiescent memory growth and shared GPU telemetry. It checks the isolated history
and tool tables remain empty. Shared-board VRAM is not exclusively ASR use.

Memory growth uses median quiescent backend private bytes in minutes 10–20 versus
50–60; its provisional allowance is the larger of 64 MiB and 25% of baseline.
Sampled peaks may miss brief allocations; observed OS working-set peaks are
also retained. Missing telemetry, insufficient samples, errors, altered inputs,
forced cleanup or an incomplete duration prevent an hour PASS. A source run
does not qualify the packaged application. This test does not qualify physical
microphones, native privacy dialogs, Hindi accuracy, wake words or fresh-account
installation. No earlier release's stability result applies to Preview 2.

## Experimental wake boundary

`sight_core/wake.py` defines a small engine protocol and a disabled implementation
that cannot emit an activation. No microphone loop, trained BEL model,
background listener, boot capture or automatic speech submission is implemented.
The fixed frame boundary is mono 16 kHz signed 16-bit PCM, 80 ms per frame.

[openWakeWord's upstream documentation](https://github.com/dscripka/openWakeWord)
describes Windows ONNX support and custom keyword training. Its code uses
Apache-2.0; included pretrained weights use CC-BY-NC-SA-4.0 and currently support
English. Those weights must not be assumed to recognize BEL. No upstream runtime
or weights were installed for this preview's wake preparation.

Before enabling a candidate, obtain explicit recording/listening consent and
document the model and training-data licenses, provenance and SHA-256. Train a
BEL-specific model; reserve independently labeled positive utterances and long
negative/noise/playback recordings across representative speakers, microphones,
distances and rooms. Keep training, threshold tuning and final acceptance sets
separate. Measure false accepts per hour, missed wakes and detection latency,
including similar-sounding words and English/Hindi speech. Personal recordings
stay local with owner-controlled retention and deletion. Separately test VAD,
debouncing, cooldown, playback/echo handling, device changes and immediate stop
on consent revocation. A detection may request visible activation only; a fresh
dictation capture and reviewed Send remain separate authorization steps.
