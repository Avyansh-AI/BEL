# BEL 0.4.2 Preview 2 — offline recognition comparison

Measured on 8 November 2026. These are fresh Preview 2 results, not the
historical Preview 1 synthetic two-phrase result. Speech accuracy and physical
microphone acceptance are separate gates.

The multilingual whisper.cpp **small-q5_1** candidate achieved **5.06% WER** on
the frozen 80-clip English read-speech evaluation, compared with **61.71%** for
the repaired Windows System.Speech adapter on exactly the same recordings.
The smaller **base-q5_1** candidate achieved **7.42%** and lower measured latency.
Both passed the provisional <=15% English WER threshold on this corpus. These
results do not establish conversational, owner-accent or microphone readiness.

## Engine selection and installation scope

| Candidate | Evaluation | Integration tradeoff |
|---|---|---|
| Windows System.Speech | Real local English inference; selectable fallback retained | Uses the installed Windows recognizer; much higher measured error on this corpus. Only installed languages are offered. |
| whisper.cpp base-q5_1 | Real local CPU inference | Smaller model and faster measured replies; less accurate than small on this English sample. |
| whisper.cpp small-q5_1 | Real local CPU inference; preferred preview model | Lowest measured English error among the tested candidates; greater CPU latency and memory demand. |
| faster-whisper | Documentation and dependency review only; NOT TESTED on this machine | CTranslate2 with CPU INT8 is feasible, but would add a separate native/Python inference stack. No comparative speed, memory or accuracy claim is made. |

The choice is a measured preview tradeoff among the tested engines, not a claim
that whisper.cpp is universally superior to faster-whisper. The latter's
[official documentation](https://github.com/SYSTRAN/faster-whisper) describes
CPU INT8 execution, CTranslate2 and PyAV dependencies. BEL's chosen standalone
worker fits the existing disposable-process boundary without importing an ASR
framework into the live backend.

The pinned native runtime is whisper.cpp **b5454**, an upstream prerelease at
`d1be6fde11ac6e0407606b4e42fe72d34add8037`; model conversion repository revision
is `5359861c739e955e79d9a303bcbc70fb988958b1`. Runtime and weights are MIT licensed.
The runtime ZIP is 8,928,640 bytes, base weights 59,707,625 bytes and small weights
190,085,487 bytes: **258,721,752 downloaded bytes** in total. Expanded installation
requires additional disk space. Exact hashes, opt-in installation and fallback
instructions are in [offline speech setup](BEL_OFFLINE_SPEECH.md). No model is
downloaded by a recognition request. Gemma's selected model is unchanged.

## Corpus, labels and reproducibility

The English subset contains **80 recorded human utterances from 71 speakers**:
40 test-clean and 40 test-other LibriSpeech examples, **954.655 seconds** of
audio. Its 2,654 whitespace-delimited reference words become **2,669 scoring
tokens** after the documented punctuation normalization. There are 11,527
scoring characters. Selection was frozen before inference using a deterministic
speaker round-robin and SHA-256 ordering, with 24–55 original reference words
and at most 20 seconds per clip. Two downloaded candidates were excluded by the
duration/format rule, without consulting model predictions. No references,
expected words or per-example hints were supplied to either recognizer.

This subset is drawn from [LibriSpeech/OpenSLR 12](https://www.openslr.org/12/),
CC BY 4.0, attributed to Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev
Khudanpur. The Hugging Face mirror revision is
`71cacbfb7e2354c4226d01e70d77d5fca3d04ba1`. Read audiobooks cover multiple speakers
and clean/challenging recordings, but do not represent spontaneous commands,
near-field/far-field owner capture or every accent.

The separate Hindi subset contains **24 human read-speech recordings** totaling
**236.58 seconds**, selected deterministically from 418 test rows in the
[FLEURS-RO mirror](https://huggingface.co/datasets/adalat-ai/fleurs-ro/tree/b952d79e607b5b1bf4d32e3b0ab394b838345439),
revision `b952d79e607b5b1bf4d32e3b0ab394b838345439`. The mirror documents
`source_transcription` as the original normalized Hindi label from
[Google FLEURS](https://huggingface.co/datasets/google/fleurs), CC BY 4.0,
attributed to Conneau et al. (SLT 2022). Only that source field is scored;
the mirror's LLM-curated `transcription` field is **not used**. Speaker identities
are absent, so Hindi speaker diversity cannot be established. The upstream and
an alternative mirror's rows endpoints failed; the selected mirror and this
provenance limitation are recorded rather than treating its rich labels as
independently human-annotated references.

English downloads consumed 18,216,932 audio bytes and Hindi 7,571,616 bytes:
**25,788,548 bytes**, below the approved shared 50,000,000-byte limit. Persistent
download accounting survives retries; completed manifests are immutable.
Audio, references, hypotheses and signed download metadata stay in the private
development cache and are excluded from the application release.

WER is total Levenshtein word edits divided by total reference tokens, not an
average of per-clip percentages. CER uses Unicode code-point edits after spaces
are removed. Both apply NFKC, case folding and punctuation-to-space replacement,
retaining Unicode letters, combining marks and numbers. Hindi is not
transliterated, and spoken numbers are not silently converted to digits. An
adapter error would count as an empty hypothesis with full deletion penalties;
low-confidence cases are never dropped. WER/CER do not measure semantic
equivalence, punctuation quality or confidence calibration.

## English results

Final run `benchmark-002.json`, 08:25:31–08:41:41 UTC. All source hashes matched
at the end. Each engine processed 80 original recordings and 10 deterministic
noise variants: **270/270 transcriptions returned without adapter errors**.

| Engine | Word edits / 2,669 | WER | CER | Median request latency | Maximum latency | Peak sampled working set | Peak sampled private bytes |
|---|---:|---:|---:|---:|---:|---:|---:|
| Windows System.Speech | 1,647 | 61.71% | 43.78% | 1.6645 s | 2.703 s | 246.016 MiB | 141.738 MiB |
| whisper.cpp base-q5_1 | 198 | 7.42% | 3.32% | 2.0470 s | 3.500 s | 295.820 MiB | 757.523 MiB |
| whisper.cpp small-q5_1 | 135 | 5.06% | 2.39% | 5.6405 s | 8.672 s | 685.879 MiB | 1,083.625 MiB |

Memory figures above cover original clips, aggregate the benchmark and its
owned child processes, and are sampled every 25 ms. They are not exact
per-model allocation measurements. Private bytes are committed process memory,
not necessarily resident RAM. Request latency includes asset verification,
worker startup, model loading and recognition. OS file caches were not cleared
between calls; these are not fresh-machine cold-start measurements.

| Engine | Clean WER / CER (40 clips) | Other WER / CER (40 clips) | Added-noise WER / CER (10 clips) |
|---|---:|---:|---:|
| Windows System.Speech | 47.51% / 32.40% | 76.59% / 56.22% | 91.69% / 75.23% |
| whisper.cpp base-q5_1 | 3.95% / 1.56% | 11.05% / 5.25% | 18.28% / 10.08% |
| whisper.cpp small-q5_1 | 3.15% / 1.23% | 7.06% / 3.65% | 11.36% / 6.46% |

Noise variants use the first five frozen examples from each split, adding
deterministic Gaussian noise at nominal 10 dB SNR with PCM clipping. These are
real recordings with synthetic added noise, not recordings in actual rooms,
traffic or meetings. Their denominator is 361 words / 1,518 characters.

All six zero/near-silence cases (two per engine) were rejected by the shared
audio-level guard before worker inference, with zero returned transcript
characters. This verifies the tested input guard, not universal immunity to
noise-induced hallucination.

An exploratory `benchmark-001.json` exposed a Windows end-of-stream bug that
could discard already-recognized text. The actual worker defect was repaired
and the complete comparison was rerun. That exploratory run and Preview 1's
two synthetic phrases are excluded from the table above.

## Hindi and formatting results

Hindi live inference and the separate synthetic formatting supplement are
awaiting their scheduled runs. Their status is **NOT TESTED** until measured
results are inserted here. Hindi-English mixed speech remains **NOT TESTED**:
Hindi read speech containing foreign names does not qualify code-switching.

## Resource and qualification limits

The English run used Windows 11 build 26300, Python 3.12.5 and four CPU inference
threads on a machine exposing 20 logical processors. The frozen voice lifecycle
stability workload was also running; host workloads were not fully controlled.
Latency is therefore shared-host evidence, not a dedicated performance-lab
measurement. The recognizer explicitly disables GPU inference. Board-level
GPU samples reported 0 MiB during this English run, but attributed process
VRAM was unavailable/null; this is not proof of zero driver allocation.

The native inference worker has a deadline, cancellation, process cleanup and
a 1.5 GiB Windows Job Object memory bound. Disk hash verification checks
cancellation cooperatively between reads; a kernel-blocked disk read cannot
be forcibly interrupted by that Python thread. Do not describe the complete
asset-validation path as hard real-time. This limitation is separate from the
measured healthy-storage latencies.

Physical microphone accuracy, device acoustics and actual echo reduction need
the [owner hardware acceptance procedure](BEL_VOICE_HARDWARE.md). A recognized
draft still requires explicit user review and submission. Neither these
benchmarks nor a successful transcribe response authorizes chat or tools.

## Evidence and rerun commands

| Private development evidence | SHA-256 |
|---|---|
| English corpus `corpus/manifest.json` | `60985f333ddd37756a9d8840b6bfa3f67ac584f327c7d907a4f7c58e399ef82f` |
| Hindi corpus `corpus-hi/manifest.json` | `d1ce46afa1a5e5d9a1d3305f1cefd81051936302d6f50721b910d5f72afb355d` |
| Final English `benchmark-002.json` | `3a3086e9dac4719c392dc79ebb2f858e40ce7fac40ab1b9b83a0273f9fe8b877` |

From the repository root, with the approved assets/corpora already installed:

```powershell
.\sight\.venv\Scripts\python.exe .\sight\scripts\benchmark_speech.py --corpus .\.cache\preview2\corpus --assets .\.cache\asr\whisper_cpp-b5454 --output .\.cache\preview2\benchmark-new.json
.\sight\.venv\Scripts\python.exe .\sight\scripts\benchmark_speech.py --corpus .\.cache\preview2\corpus-hi --assets .\.cache\asr\whisper_cpp-b5454 --engines base-q5_1,small-q5_1 --output .\.cache\preview2\benchmark-hi-new.json
```

The harness does not download, open a microphone, play audio, send chat or invoke
tools. Existing outputs are preserved; a matching interrupted run can use
`--resume`, while completed evidence cannot be overwritten. Corpus hashes and
recognizer/harness source hashes are checked. Unit tests cover the scorer,
Unicode normalization, deterministic noise, byte-budget retention, tamper
detection and duplicate/path rejection; those tests validate the harness,
not ASR quality.
