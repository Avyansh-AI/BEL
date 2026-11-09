/** One reviewed transcript at a time. Cancellation targets an exact server request. */
export type DictationRequest = { requestId: string; controller: AbortController }

export class DictationSession {
  private current: DictationRequest | null = null
  private cancellation: Promise<void> | null = null
  private cancelRemote: (requestId: string) => Promise<unknown>

  constructor(cancelRemote: (requestId: string) => Promise<unknown>) { this.cancelRemote = cancelRemote }

  get active() { return this.current !== null }
  get requestId() { return this.current?.requestId ?? null }
  get stopping() { return this.cancellation !== null }

  begin(requestId = crypto.randomUUID()): DictationRequest {
    if (this.current || this.cancellation) throw new Error('Wait for the previous dictation request to stop.')
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(requestId)) throw new Error('Invalid capture session.')
    const request = { requestId, controller: new AbortController() }
    this.current = request
    return request
  }

  accepts(request: DictationRequest) { return this.current === request && !request.controller.signal.aborted }

  finish(request: DictationRequest) {
    if (this.current !== request) return false
    this.current = null
    return true
  }

  cancel(): Promise<void> {
    if (this.cancellation) return this.cancellation
    const request = this.current
    if (!request) return Promise.resolve()
    this.current = null
    request.controller.abort()
    const cancellation = (async () => { await this.cancelRemote(request.requestId) })().finally(() => {
      if (this.cancellation === cancellation) this.cancellation = null
    })
    this.cancellation = cancellation
    return cancellation
  }
}

export const dictationLanguages: Record<string, string> = {
  'en-US': 'English (United States)', 'en-GB': 'English (United Kingdom)',
  'en-IN': 'English (India)', 'hi-IN': 'Hindi (India)',
  'auto': 'Detect language locally',
}

export function installedLanguages(locales: unknown, allowAuto = false): string[] {
  return Array.isArray(locales) ? [...new Set(locales.filter((value): value is string => typeof value === 'string' && (value !== 'auto' || allowAuto) && Object.prototype.hasOwnProperty.call(dictationLanguages, value)))] : []
}
