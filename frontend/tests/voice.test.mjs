import { afterEach, test } from 'node:test'
import assert from 'node:assert/strict'
import { encodeWav, LocalCapture, toBase64 } from '../src/lib/voice.ts'

const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
afterEach(() => { if (originalNavigator) Object.defineProperty(globalThis, 'navigator', originalNavigator); else delete globalThis.navigator })

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
