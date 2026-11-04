/** Opt-in bounded PCM capture. Audio stays in this page until sent to the local STT endpoint. */
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
  private stream: MediaStream | null = null
  private context: AudioContext | null = null
  private processor: ScriptProcessorNode | null = null
  private samples: Float32Array[] = []
  private count = 0
  private stopped = false
  private rate = 48000
  private timer: ReturnType<typeof setTimeout> | null = null

  async start(deviceId: string, onLevel: (level: number) => void, onLimit: () => void) {
    if (this.stopped) return false
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true, ...(deviceId ? { deviceId: { exact: deviceId } } : {}) }, video: false })
    if (this.stopped) { stream.getTracks().forEach(t => t.stop()); return false }
    this.stream = stream
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
        let energy = 0
        for (const value of copy) energy += value * value
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
    this.stream?.getTracks().forEach(t => t.stop()); this.stream = null
    if (this.context) void this.context.close().catch(() => undefined)
    this.context = null
    if (!keep || this.count < this.rate * 0.15) { this.samples = []; this.count = 0; return null }
    const joined = new Float32Array(this.count)
    let offset = 0
    for (const part of this.samples) { joined.set(part, offset); offset += part.length }
    this.samples = []; this.count = 0
    return encodeWav(joined, this.rate)
  }
}
