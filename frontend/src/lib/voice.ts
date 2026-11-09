/** Opt-in bounded PCM capture. Audio stays in this page until sent to the local STT endpoint. */
export type SpeechEngineId = 'windows' | 'whisper_cpp'
export type Transcript = {
  text: string; confidence: number | null; locale: string; engine: string; review_required: true
  confidence_kind?: 'engine_score' | 'unavailable'; engine_id?: SpeechEngineId
  requested_engine?: SpeechEngineId; fallback_from?: SpeechEngineId | null; fallback_reason?: string | null
}

export function captureErrorMessage(error: unknown): string {
  const name = error && typeof error === 'object' && 'name' in error ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'Microphone permission was denied. Allow BEL in Windows and the browser permission settings, then hold to talk again.'
  if (name === 'NotFoundError') return 'No microphone was found. Connect a microphone or select another device.'
  if (name === 'NotReadableError') return 'The microphone could not be opened. It may be busy in another application.'
  if (name === 'OverconstrainedError') return 'The selected microphone is unavailable. Choose System default or another device.'
  return 'Microphone capture was interrupted. Check the selected device and try again.'
}

export function appendTranscript(draft: string, transcript: string): string {
  const merged = draft.trimEnd() ? draft.trimEnd() + '\n' + transcript : transcript
  if (merged.length > 8000) throw new Error('The draft and transcript exceed 8,000 characters. Shorten the draft before dictating again.')
  return merged
}

export function parseTranscript(value: unknown, locale: string): Transcript {
  if (!value || typeof value !== 'object') throw new Error('Local transcription returned an invalid result.')
  const result = value as Partial<Transcript>
  if (typeof result.text !== 'string' || !result.text.trim() || result.text.length > 8000 || result.text.includes('\0') ||
      (result.confidence !== null && (typeof result.confidence !== 'number' || !Number.isFinite(result.confidence) || result.confidence < 0 || result.confidence > 1)) ||
      (result.confidence === null && result.confidence_kind !== 'unavailable') ||
      (result.confidence !== null && result.confidence_kind === 'unavailable') ||
      (result.confidence_kind !== undefined && !['engine_score', 'unavailable'].includes(result.confidence_kind)) ||
      [result.engine_id, result.requested_engine, result.fallback_from].some(id => id !== undefined && id !== null && !['windows', 'whisper_cpp'].includes(id)) ||
      (result.fallback_reason !== undefined && result.fallback_reason !== null && (typeof result.fallback_reason !== 'string' || result.fallback_reason.length > 500)) ||
      (result.fallback_from != null && (result.fallback_from === result.engine_id || result.requested_engine !== result.fallback_from)) ||
      result.locale !== locale || typeof result.engine !== 'string' || !result.engine || result.engine.length > 80 || result.review_required !== true) {
    throw new Error('Local transcription returned an invalid result.')
  }
  return result as Transcript
}

export function encodeWav(samples: Float32Array, sampleRate: number): Uint8Array {
  if (!Number.isFinite(sampleRate) || sampleRate < 8000 || sampleRate > 192000 || samples.length > sampleRate * 21) throw new Error('Invalid audio capture.')
  const count = Math.floor(samples.length * 16000 / sampleRate)
  const bytes = new Uint8Array(44 + count * 2)
  const view = new DataView(bytes.buffer)
  const label = (at: number, text: string) => [...text].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)))
  label(0, 'RIFF'); view.setUint32(4, bytes.length - 8, true); label(8, 'WAVE'); label(12, 'fmt ')
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true)
  label(36, 'data'); view.setUint32(40, count * 2, true)
  for (let i = 0; i < count; i++) {
    const begin = Math.floor(i * sampleRate / 16000)
    const end = Math.max(begin + 1, Math.floor((i + 1) * sampleRate / 16000))
    let value = 0
    for (let j = begin; j < end && j < samples.length; j++) value += Number.isFinite(samples[j]) ? samples[j] : 0
    value = Math.max(-1, Math.min(1, value / (end - begin)))
    view.setInt16(44 + i * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true)
  }
  return bytes
}

export function toBase64(bytes: Uint8Array) {
  let binary = ''
  for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192))
  return btoa(binary)
}

export class LocalCapture {
  readonly id = crypto.randomUUID()
  failure: 'too_short' | 'silent' | null = null
  private stream: MediaStream | null = null
  private context: AudioContext | null = null
  private processor: ScriptProcessorNode | null = null
  private samples: Float32Array[] = []
  private count = 0
  private stopped = false
  private rate = 48000
  private timer: ReturnType<typeof setTimeout> | null = null
  private audible = false

  async start(deviceId: string, onLevel: (level: number) => void, onLimit: () => void, onInterrupted?: () => void) {
    if (this.stopped) return false
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true, ...(deviceId ? { deviceId: { exact: deviceId } } : {}) }, video: false })
    if (this.stopped) { stream.getTracks().forEach(t => t.stop()); return false }
    this.stream = stream
    stream.getTracks().forEach(track => {
      track.onended = () => { if (!this.stopped) { this.stop(false); onInterrupted?.() } }
    })
    try {
      const context = new AudioContext()
      this.context = context
      this.rate = context.sampleRate
      await context.resume()
      if (this.stopped) return false
      const source = context.createMediaStreamSource(stream)
      // A silent output connection is required by older WebView2 audio engines.
      const processor = context.createScriptProcessor(4096, 1, 1)
      this.processor = processor
      processor.onaudioprocess = event => {
        if (this.stopped) return
        const data = event.inputBuffer.getChannelData(0)
        if (this.count + data.length > this.rate * 20) { onLimit(); return }
        const copy = new Float32Array(data)
        this.samples.push(copy); this.count += copy.length
        let energy = 0; let peak = 0
        for (const value of copy) { if (Number.isFinite(value)) { energy += value * value; peak = Math.max(peak, Math.abs(value)) } }
        // A near-zero signal guard, not a voice detector or acoustic-quality claim.
        if (peak >= 0.0005 && energy / copy.length >= 1e-8) this.audible = true
        onLevel(Math.min(1, Math.sqrt(energy / copy.length) * 4.3))
        event.outputBuffer.getChannelData(0).fill(0)
      }
      source.connect(processor); processor.connect(context.destination)
      this.timer = setTimeout(onLimit, 20000)
      return true
    } catch (error) { this.stop(false); throw error }
  }

  stop(keep: boolean): Uint8Array | null {
    this.stopped = true
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
    if (this.processor) { this.processor.onaudioprocess = null; this.processor.disconnect() }
    this.processor = null
    this.stream?.getTracks().forEach(t => { t.onended = null; t.stop() }); this.stream = null
    if (this.context) void this.context.close().catch(() => undefined)
    this.context = null
    if (!keep || this.count < this.rate * 0.15 || !this.audible) {
      this.failure = !keep ? null : this.count < this.rate * 0.15 ? 'too_short' : 'silent'
      this.samples = []; this.count = 0; return null
    }
    const joined = new Float32Array(this.count)
    let offset = 0
    for (const part of this.samples) { joined.set(part, offset); offset += part.length }
    this.samples = []; this.count = 0
    return encodeWav(joined, this.rate)
  }
}
