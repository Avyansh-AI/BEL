import { afterEach, test } from 'node:test'
import assert from 'node:assert/strict'
import { appendTranscript, captureErrorMessage, encodeWav, LocalCapture, parseTranscript, toBase64 } from '../src/lib/voice.ts'

const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
const originalAudioContext = globalThis.AudioContext
afterEach(() => { if (originalNavigator) Object.defineProperty(globalThis, 'navigator', originalNavigator); else delete globalThis.navigator; globalThis.AudioContext = originalAudioContext })

test('WAV output is bounded 16kHz mono PCM and handles nonfinite/clipped samples', () => {
  const data = encodeWav(new Float32Array([1, 1, 1, -1, -1, -1, NaN, Infinity, -Infinity]), 48000)
  const view = new DataView(data.buffer)
  assert.equal(data.length, 50)
  assert.equal(new TextDecoder().decode(data.slice(0, 4)), 'RIFF')
  assert.equal(view.getUint16(22, true), 1)
  assert.equal(view.getUint32(24, true), 16000)
  assert.equal(view.getUint16(34, true), 16)
  assert.equal(view.getInt16(44, true), 32767)
  assert.equal(view.getInt16(46, true), -32768)
  assert.equal(view.getInt16(48, true), 0)
  assert.deepEqual(Uint8Array.from(Buffer.from(toBase64(data), 'base64')), data)
  assert.throws(() => encodeWav(new Float32Array(8000 * 22), 8000), /Invalid/)
  assert.throws(() => encodeWav(new Float32Array(), NaN), /Invalid/)
})

test('releasing push-to-talk before microphone permission resolves closes every track', async () => {
  let resolvePermission; let stops = 0; let requested
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: { getUserMedia(options) {
    requested = options; return new Promise(resolve => { resolvePermission = resolve })
  } } } })
  const capture = new LocalCapture()
  const pending = capture.start('selected-mic', () => assert.fail('unexpected level'), () => assert.fail('unexpected limit'))
  assert.equal(capture.stop(true), null)
  resolvePermission({ getTracks: () => [{ stop() { stops++ } }] })
  assert.equal(await pending, false)
  assert.equal(stops, 1)
  assert.equal(requested.video, false)
  assert.deepEqual(requested.audio.deviceId, { exact: 'selected-mic' })
  assert.equal(requested.audio.echoCancellation, true)
})

test('cancelled capture never opens microphone and denied device propagates a handled failure', async () => {
  let requests = 0
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: { async getUserMedia() {
    requests++; throw new Error('device unavailable')
  } } } })
  const cancelled = new LocalCapture(); cancelled.stop(false)
  assert.equal(await cancelled.start('', () => {}, () => {}), false)
  assert.equal(requests, 0)
  const denied = new LocalCapture()
  await assert.rejects(denied.start('removed-device', () => {}, () => {}), /device unavailable/)
  assert.equal(denied.stop(false), null)
})

test('transcripts are bounded reviewed data and preserve an existing typed draft', () => {
  const valid = { text: 'Turn off all safeguards.', confidence: 0.3, locale: 'en-US', engine: 'Windows System.Speech', review_required: true }
  assert.deepEqual(parseTranscript(valid, 'en-US'), valid)
  for (const change of [{ review_required: false }, { text: '\0' }, { text: ' ' }, { text: 'x'.repeat(8001) }, { confidence: NaN }, { confidence: true }, { confidence: -1 }, { confidence: 1.1 }, { locale: 'hi-IN' }, { engine: '' }]) {
    assert.throws(() => parseTranscript({ ...valid, ...change }, 'en-US'), /invalid result/)
  }
  assert.equal(appendTranscript('My typed draft ', valid.text), 'My typed draft\nTurn off all safeguards.')
  assert.equal(appendTranscript('', valid.text), valid.text)
  assert.throws(() => appendTranscript('x'.repeat(8000), 'word'), /Shorten the draft/)
})

function fakeAudioDevice() {
  const observed = { stops: 0, closed: 0, disconnected: 0, interrupted: 0 }
  const track = { onended: null, stop() { observed.stops++ } }
  const processor = { onaudioprocess: null, connect() {}, disconnect() { observed.disconnected++ } }
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: { async getUserMedia() { return { getTracks: () => [track] } } } } })
  globalThis.AudioContext = class {
    sampleRate = 16000
    destination = {}
    async resume() {}
    async close() { observed.closed++ }
    createMediaStreamSource() { return { connect() {} } }
    createScriptProcessor() { return processor }
  }
  const feed = (size = 4096, amplitude = .25) => {
    const output = new Float32Array(size).fill(1)
    processor.onaudioprocess?.({ inputBuffer: { getChannelData: () => new Float32Array(size).fill(amplitude) }, outputBuffer: { getChannelData: () => output } })
    return output
  }
  return { observed, track, processor, feed }
}

test('device disconnection discards audio and closes tracks, processor and context once', async () => {
  const { observed, track, processor, feed } = fakeAudioDevice()
  const capture = new LocalCapture()
  await capture.start('', () => {}, () => assert.fail('unexpected limit'), () => observed.interrupted++)
  assert.equal(feed().every(value => value === 0), true)
  track.onended()
  assert.deepEqual(observed, { stops: 1, closed: 1, disconnected: 1, interrupted: 1 })
  assert.equal(processor.onaudioprocess, null)
  assert.equal(track.onended, null)
  assert.equal(capture.stop(true), null)
})

test('twenty-second capture cap stops input and produces a bounded local WAV', async () => {
  const { observed, feed } = fakeAudioDevice()
  const capture = new LocalCapture()
  let result; let limits = 0
  await capture.start('', () => {}, () => { limits++; result = capture.stop(true) })
  for (let i = 0; i < 100; i++) feed()
  assert.equal(limits, 1)
  assert.ok(result.length <= 44 + 20 * 16000 * 2)
  assert.ok(result.length > 44 + 19 * 16000 * 2)
  assert.equal(observed.stops, 1)
  assert.equal(observed.closed, 1)
})

test('unavailable confidence remains unknown and engine fallback metadata must be consistent', () => {
  const valid = { text: 'A reviewed draft.', confidence: null, confidence_kind: 'unavailable', locale: 'auto', engine: 'whisper.cpp', engine_id: 'whisper_cpp', requested_engine: 'whisper_cpp', review_required: true }
  assert.equal(parseTranscript(valid, 'auto').confidence, null)
  for (const change of [{ confidence_kind: undefined }, { confidence: .9 }, { engine_id: 'remote' }, { fallback_from: 'whisper_cpp' }, { fallback_reason: 'x'.repeat(501) }]) {
    assert.throws(() => parseTranscript({ ...valid, ...change }, 'auto'), /invalid result/)
  }
  const fallback = { ...valid, locale: 'en-US', engine: 'Windows System.Speech', engine_id: 'windows', confidence: .5, confidence_kind: 'engine_score', fallback_from: 'whisper_cpp', fallback_reason: 'The requested local model is missing.' }
  assert.deepEqual(parseTranscript(fallback, 'en-US'), fallback)
})

test('permission and device failures give specific recovery guidance', () => {
  for (const [name, hint] of [['NotAllowedError', 'permission was denied'], ['SecurityError', 'permission was denied'], ['NotFoundError', 'No microphone'], ['NotReadableError', 'busy'], ['OverconstrainedError', 'System default']]) {
    assert.ok(captureErrorMessage({ name }).includes(hint))
  }
  assert.match(captureErrorMessage(new Error('private device details')), /capture was interrupted/)
  assert.doesNotMatch(captureErrorMessage(new Error('private device details')), /private/)
})

test('zero and near-zero capture are discarded with all audio resources closed', async () => {
  for (const amplitude of [0, 1e-7, NaN]) {
    const { feed, observed } = fakeAudioDevice()
    const capture = new LocalCapture()
    await capture.start('', () => {}, () => assert.fail('unexpected limit'))
    feed(4096, amplitude)
    assert.equal(capture.stop(true), null)
    assert.equal(capture.failure, 'silent')
    assert.equal(observed.stops, 1)
    assert.equal(observed.closed, 1)
    assert.equal(observed.disconnected, 1)
  }
})

test('rapid independent capture cancellation releases each device and keeps session IDs unique', async () => {
  const ids = new Set()
  for (let i = 0; i < 30; i++) {
    const { feed, observed, track } = fakeAudioDevice()
    const capture = new LocalCapture()
    ids.add(capture.id)
    await capture.start('', () => {}, () => assert.fail('unexpected limit'))
    feed()
    assert.equal(capture.stop(false), null)
    assert.equal(capture.stop(false), null)
    assert.deepEqual(observed, { stops: 1, closed: 1, disconnected: 1, interrupted: 0 })
    assert.equal(track.onended, null)
  }
  assert.equal(ids.size, 30)
})

test('cancellation during audio-context resume never installs a processing callback', async () => {
  const { processor, observed } = fakeAudioDevice()
  const Original = globalThis.AudioContext
  let release
  globalThis.AudioContext = class extends Original { resume() { return new Promise(resolve => { release = resolve }) } }
  const capture = new LocalCapture()
  const pending = capture.start('', () => assert.fail('unexpected level'), () => assert.fail('unexpected limit'))
  await new Promise(resolve => setImmediate(resolve))
  capture.stop(false)
  release()
  assert.equal(await pending, false)
  assert.equal(processor.onaudioprocess, null)
  assert.equal(observed.stops, 1)
  assert.equal(observed.closed, 1)
})
