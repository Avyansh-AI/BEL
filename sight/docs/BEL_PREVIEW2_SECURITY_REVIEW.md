# Preview 2 independent speech security and lifecycle review

Review date: 8 November 2026. Scope: the new speech-engine service, pinned ASR
inventory, explicit installer, Windows resource containment, speech HTTP/session
boundary, disabled wake interface and voice stability harness. This review did
not open a microphone, run a second recognizer during the stability test, change
the running packaged application, or alter owner data.

This is a source and evidence review, not a claim that every hardware or release
gate passed. At the time of review, the fresh 3,600-second frozen voice run was
still in progress. Its final result belongs in the release report.

## Findings

1. **Installer parent permissions — repair required.** The reviewed installer
   called `private_directory(destination.parent)` and applied the same helper to
   an existing offline source directory. That helper replaces the directory DACL
   with a protected owner/System/Admin ACL. Selecting a new ASR folder underneath
   an existing shared parent could therefore change access to unrelated files.
   The release engineer confirmed the finding and is repairing the auxiliary
   installer separately from the frozen backend under test. Apply private ACLs
   only to newly created owned directories and staging, and preserve existing
   source/parent ACLs. The final report must identify the repaired installer and
   its regression evidence; this review alone does not certify the repair.

2. **Asset-verification deadline limitation.** The recognizer subprocess has an
   actively polled deadline, but the Python asset-probe runner does not enforce
   its supplied timeout. Hash verification checks cancellation between reads;
   recognition checks its remaining budget after verification. A blocked storage
   read is not forcibly interrupted. An isolated simulation replaced only the
   verifier in a disposable Python process: a probe with a 0.01-second requested
   deadline returned success after approximately 0.109 seconds. No recognizer
   was started. This does not grant execution of an unverified asset, but it
   prevents a hard wall-clock guarantee for damaged/unresponsive storage. Future
   work should isolate verification or enforce deadline checks between reads,
   while retaining drain-before-reuse behavior. Document this limit accurately.

No new critical speech-to-action, cross-session cancellation or asset-integrity
bypass was identified in the reviewed paths. That conclusion is bounded by the
review and tests below; it is not a proof of absence of defects.

## Boundaries checked

- Speech remains disabled without the startup offer and current owner-session
  consent. HTTP authorization and CSRF remain in force. A request ID is consumed
  before recognition starts, cancellation targets the exact session/request,
  and IDs are not evicted within a live session. Session expiry, disconnect and
  consent revocation discard late results. Speech state events carry request IDs
  and target the owner session.
- PCM format, duration, size and near-silence checks precede recognition. Both
  recognizers return reviewed drafts; no speech endpoint submits chat, invokes a
  tool or interprets transcript text as code. Whisper confidence is unavailable,
  rather than a fabricated probability.
- Engine execution is serialized. Invalid input, silence, busy conditions and
  cancellation propagate instead of starting fallback. Allowed fallback is an
  already available local engine supporting the requested language; its identity
  and reason are included in the result. There is no cloud speech adapter or
  automatic model download in the recognition path.
- The compiled catalog pins the runtime archive, selected executable/DLLs and
  weights by size and SHA-256. Extra runtime files, changed manifests and missing
  weights fail closed. The selected runtime and weight files are locked against
  Windows replacement during verification/use. Installer extraction names are
  fixed, outputs are verified again, and publication uses a complete staging
  directory. Existing installations are not overwritten.
- Whisper receives a fixed argument list, CPU-only flags and a reduced environment
  excluding provider credentials and plugin search overrides. Input/output use
  pipes. Its Job Object limits process memory to 1.5 GiB and active processes to
  one. This is resource containment, not an OS security sandbox. Same-owner or
  administrator compromise is outside the asset-lock claim.
- Cancellation drains the owned worker and pipe thread before releasing the
  engine lock. The stability harness records process creation identities, avoids
  killing unrelated reused PIDs, distinguishes persistent Windows launchers from
  recognition workers, and checks owned children have exited. Startup/shutdown do
  not count toward the lifecycle hour. Sparse samples, long telemetry gaps or too
  few lifecycle cycles prevent qualification.
- Hardware evidence uses explicit owner observations and fixed statuses, with
  unperformed checks left `NOT TESTED`. It stores no raw audio, transcripts,
  device names or free-text answers. The wake interface stays disabled and has
  no capture loop, BEL model, enrollment or activation authority.

## Evidence inspected

The following existing machine-readable receipts were read independently. They
are results produced by the implementation run, not additional executions by
this reviewer:

| Receipt | Tests | Failures | Errors | Skipped |
|---|---:|---:|---:|---:|
| `regression-003.xml` | 648 | 0 | 0 | 0 |
| `engine-final.xml` | 37 | 0 | 0 | 0 |
| `installer-eof-tests.xml` | 30 | 0 | 0 | 0 |
| `acceptance-preparation-005.xml` | 34 | 0 | 0 | 0 |

All receipts above are private under `.cache/preview2/`; raw XML contains local
environment metadata and should not be published indiscriminately. The tests
cover fallback policy, cancellation, cross-engine serialization, low-memory
refusal, actual Windows Job Object allocation containment, altered/missing ASR
assets, write locks, disabled wake behavior and evidence-tool guardrails.
The inspected 60-second frozen smoke completed 31/31 checks, no surviving owned
processes and no retained audio/message/tool rows. Its status is correctly
`PARTIAL`; it cannot qualify the required hour.

## Remaining limits

Physical microphones, native privacy dialogs, disconnect/reconnect behavior and
acoustic echo reduction need owner hardware acceptance. Silence/noise and
adversarial browser fixtures do not substitute for that. No BEL wake-word model
was trained or measured. ASR runtime b5454 is a pinned upstream prerelease.
CPU mode avoids deliberate GPU allocation but can still contend with Gemma for
RAM and CPU. Host/board GPU measurements are not exclusive ASR allocation.

Worker stdout/stderr size checks occur after pipe collection; they are not
streaming byte ceilings on the parent process. Only the pinned fixed recognizer
is allowed to use that transport. Hash/file locking cannot defend against an
already compromised owner account or administrator. A fresh-account Windows
installation and arbitrary storage/device failure recovery are not established
by this review. Preserve these limits in release claims.
