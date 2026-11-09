# Preview 2 offline speech setup

This preview preserves Windows System.Speech and adds an isolated CPU whisper.cpp
adapter. Microphone capture is disabled by default. Starting with
`BEL.exe --local-dictation` only offers the feature; enable session consent in
Settings, select an engine/language and explicitly hold the microphone control.
Review the separate editable transcript and deliberately choose **Send reviewed
message** or **Discard speech draft**. Typed text is preserved on cancellation.
Neither recognition nor a wake event authorizes a tool or sends chat by itself.

## Explicit model installation

The installer requires Windows x64 and Python 3.12. Ordinary BEL use does not
require a console. Recognition never downloads anything. Models and runtime
files remain outside the application ZIP and owner memories.

The pinned CPU runtime is whisper.cpp **b5454**, an upstream prerelease, commit
`d1be6fde11ac6e0407606b4e42fe72d34add8037`. Converted multilingual weights use
repository revision `5359861c739e955e79d9a303bcbc70fb988958b1`. Runtime and weights
are MIT licensed; notices accompany the installer and resulting installation.

| Download | Exact bytes | SHA-256 |
|---|---:|---|
| whisper-bin-x64.zip | 8,928,640 | `6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb` |
| ggml-base-q5_1.bin | 59,707,625 | `422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898` |
| ggml-small-q5_1.bin | 190,085,487 | `ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb` |

From a source checkout, this explicit command downloads the runtime and selected
small model, verifies size/hash, installs only the 13 required native files and
publishes a complete manifest last. It refuses to overwrite an installation.

```powershell
$belSpeechHome = Join-Path $env:LOCALAPPDATA 'BEL\asr\whisper_cpp-b5454'
.\sight\.venv\Scripts\python.exe .\sight\scripts\provision_asr.py --download --source-directory .\.cache\speech-downloads --destination $belSpeechHome --model small-q5_1
```

In the extracted preview ZIP, use the included installer with an installed
Python 3.12 instead:

```powershell
$belSpeechHome = Join-Path $env:LOCALAPPDATA 'BEL\asr\whisper_cpp-b5454'
py -3.12 .\tools\speech-installer\scripts\provision_asr.py --download --source-directory .\speech-downloads --destination $belSpeechHome --model small-q5_1
```

To install entirely offline, provide the already verified ZIP and model in
`--source-directory` and omit `--download`. Add `--model base-q5_1` to install the
smaller candidate too. Preserve an interrupted staging/download directory for
inspection; choose a new cache/destination for a clean retry. A changed file is
an integrity error, never an excuse to reset the expected hash.

The frozen app checks `%LOCALAPPDATA%\BEL\asr\whisper_cpp-b5454` by default.
Source runs check this checkout's `.cache\asr\whisper_cpp-b5454`. Override with
`BEL_ASR_DIRECTORY` if needed. `BEL_ASR_MODEL=base-q5_1` selects the smaller model;
the default is `small-q5_1`. These speech settings do not change Gemma.

## Selection, fallback and privacy

`BEL_SPEECH_ENGINE=whisper_cpp` is the default preference; `windows` explicitly
prefers the legacy recognizer. The old `BEL_LOCAL_STT=windows` enable switch is
retained, and `BEL_LOCAL_STT=whisper_cpp` also enables the offered feature.
Settings lists actual engine installation status and supported language options.
Language support in weights does not establish recognition accuracy.

If an engine is absent or fails safely, the service may use another already
installed local recognizer that supports the selected language. The transcript
identifies the actual engine and fallback reason. API callers can set
`allow_fallback: false`. Cancellation, malformed/silent input and busy workers
never trigger fallback. There is no cloud ASR path or model installation during
a recognition request. Whisper confidence is explicitly unavailable; it is not
invented from an unrelated model score.

Each request is limited to mono 16 kHz 16-bit PCM WAV, 20 seconds and 700,000
bytes. A single CPU worker uses four threads, a 60-second inference/verification
budget and a Windows Job Object with a 1.5 GiB process-memory limit. Below 256 MiB
available system RAM, Whisper refuses to start. This is containment, not a host
sandbox. CPU inference avoids deliberate GPU allocation, but CPU/RAM contention
and paging can still increase latency while Gemma or other applications run.

Assets are rechecked against the compiled catalog and held against Windows
replacement while used. WAVs travel through stdin; transcripts return through
stdout. The backend retains neither recording nor unsubmitted transcript.
Explicitly sent text follows the existing conversation retention rules.

Browser echo cancellation/noise suppression are requests, not measured hardware
guarantees. Physical microphones, native permission dialogs, accents and
Hindi/mixed-language quality need separate acceptance. See
[owner hardware acceptance](BEL_VOICE_HARDWARE.md). BEL wake listening remains
disabled because no validated BEL-specific model or corpus is available.

## Rollback

Exit Preview 2 through its tray. Start the preserved BEL 0.4.1 folder or Preview 1
folder, using the intended existing profile. Do not delete or replace either
archive or your data directory. Preview 2 adds no destructive memory migration.
Source rollback is `rollback/bel-preview1-20261106` at
`98c8f3120e5f7fc3ce960dcfbe90323e859cacdf`; inspect or create a separate checkout
from that reference instead of resetting a directory with uncommitted work.

## Provenance

- [whisper.cpp pinned source and license](https://github.com/ggml-org/whisper.cpp/tree/d1be6fde11ac6e0407606b4e42fe72d34add8037)
- [Pinned converted model catalog](https://huggingface.co/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1)
- [OpenAI Whisper license](https://github.com/openai/whisper/blob/v20250625/LICENSE)
