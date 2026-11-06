/** Same-origin owner-session transport. No cloud endpoints, tokens in storage, or action retries. */
export type BelState = 'idle' | 'wake_word' | 'listening' | 'speech_recognition' | 'thinking' | 'tool_execution' | 'speaking' | 'task_completed' | 'error' | 'offline' | 'background'
export type BelEvent = { type: 'state'; state: BelState; requestId?: string } | { type: 'error'; message: string; requestId?: string }
export type Proposal = { path: string; args: Record<string, unknown>; summary: string; tool?: string; confidence?: number }
export type ChatReply = { requestId: string; status: string; say: string; offline: boolean; proposal?: Proposal }
export type PreparedAction = Proposal & { approvalId: string; expiresAt: number }
export type HistoryItem = { id: string; role: 'user' | 'assistant'; text: string; at: number }
export type BelStatus = { name: string; full_name: string; owner: string; mode: string; voice: { recording_supported: boolean; stt_available: boolean; tts_available: boolean; playback_available: boolean; wake_word: string; wake_available: boolean; microphone_enabled: boolean; reason: string; locales?: string[]; locale?: string; engine?: string }; tool_router: { status: string; model: string; reason: string } }
const states = new Set<BelState>(['idle', 'wake_word', 'listening', 'speech_recognition', 'thinking', 'tool_execution', 'speaking', 'task_completed', 'error', 'offline', 'background'])
const actionPaths = new Set(['/api/bel/tools/execute', '/api/bel/history/clear', '/api/capability/invoke', '/api/models/configure', '/api/learning/memory/save', '/api/learning/memory/edit', '/api/learning/memory/delete'])

export function parseEvent(raw: string): BelEvent | null {
  if (raw.length > 100_000) return null
  try {
    const v = JSON.parse(raw)
    if (!v || typeof v !== 'object' || (v.requestId !== undefined && (typeof v.requestId !== 'string' || v.requestId.length > 100))) return null
    if (v.type === 'state' && states.has(v.state)) return { type: 'state', state: v.state, requestId: v.requestId }
    const error = typeof v.error === 'string' ? v.error : v.message
    if (v.type === 'error' && typeof error === 'string') return { type: 'error', message: error.slice(0, 500), requestId: v.requestId }
  } catch { /* Invalid wire data has no UI authority. */ }
  return null
}

export function parseHistory(value: unknown): HistoryItem[] {
  if (!Array.isArray(value)) return []
  return value.slice(-200).filter((x): x is HistoryItem => !!x && typeof x === 'object' && typeof x.id === 'string' && x.id.length <= 150 && ['user', 'assistant'].includes(x.role) && typeof x.text === 'string' && x.text.length <= 32000 && typeof x.at === 'number' && Number.isFinite(x.at))
}

export class BelApiClient {
  private csrf = ''
  private socket: WebSocket | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectAttempt = 0
  private generation = 0
  private closed = true
  private authentication: Promise<string> | null = null
  private onEvent: (event: BelEvent) => void = () => undefined
  private onConnection: (connected: boolean, reason?: string) => void = () => undefined

  async request<T>(path: string, body?: unknown, timeout = 15000, signal?: AbortSignal): Promise<T> {
    const base = window.location.origin
    const url = new URL(path, base)
    if (!path.startsWith('/api/') || url.origin !== base || !url.pathname.startsWith('/api/') || url.hash || /[\x00-\x1f\\]/.test(path) || decodeURIComponent(url.pathname).includes('..')) throw new Error('Invalid local API path.')
    const controller = new AbortController()
    const cancel = () => controller.abort()
    if (signal?.aborted) cancel()
    else signal?.addEventListener('abort', cancel, { once: true })
    const deadline = setTimeout(() => controller.abort(), timeout)
    try {
      const response = await fetch(path, { method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal, headers: body === undefined ? {} : { 'content-type': 'application/json', 'x-sight-csrf': this.csrf }, body: body === undefined ? undefined : JSON.stringify(body) })
      let data
      try { data = await response.json() } catch { throw new Error('The local service returned an invalid response. Check its status before retrying.') }
      if (!response.ok) {
        if (response.status === 401) throw new Error('Open BEL from its local launcher to establish an owner session.')
        const reason = typeof data.detail === 'string' ? data.detail : typeof data.error === 'string' ? data.error : `Request failed (${response.status}).`
        throw new Error(reason.slice(0, 500))
      }
      return data as T
    } catch (error) {
      if (signal?.aborted) throw new DOMException('Request cancelled.', 'AbortError')
      if (controller.signal.aborted) throw new Error('BEL did not answer before the deadline. Check task history before retrying; the backend may still be working.')
      if (error instanceof TypeError) throw new Error('The local BEL service is unavailable. No simulated reply or cloud request was made.')
      throw error
    } finally { clearTimeout(deadline); signal?.removeEventListener('abort', cancel) }
  }

  async connect(onEvent: (event: BelEvent) => void, onConnection: (connected: boolean, reason?: string) => void) {
    this.disconnect()
    this.closed = false
    this.onEvent = onEvent
    this.onConnection = onConnection
    const generation = this.generation
    try {
      const csrf = await this.authenticate()
      if (this.closed || generation !== this.generation) return
      this.csrf = csrf
      await this.openSocket(generation)
    } catch (error) {
      if (!this.closed && generation === this.generation) this.onConnection(false, error instanceof Error ? error.message : 'Connection failed.')
    }
  }

  private async authenticate(): Promise<string> {
    // React StrictMode and reconnect clicks may overlap the claim. Share only the
    // in-flight authentication so no second request races the first cookie write.
    if (this.authentication) return this.authentication
    const pending = (async () => {
      const params = new URLSearchParams(window.location.hash.slice(1))
      const token = params.get('bel-session') || params.get('sight-session')
      if (token) {
        window.history.replaceState(null, '', window.location.pathname + window.location.search)
        await this.request('/api/session/claim', { token })
      }
      const session = await this.request<{ csrf: string }>('/api/session')
      if (typeof session.csrf !== 'string' || session.csrf.length < 16) throw new Error('The local session response is invalid.')
      return session.csrf
    })()
    this.authentication = pending
    try { return await pending }
    finally { if (this.authentication === pending) this.authentication = null }
  }

  private async openSocket(generation: number) {
    if (this.closed || generation !== this.generation) return
    try {
      const ticket = await this.request<{ ticket: string }>('/api/access/ticket', {})
      if (this.closed || generation !== this.generation) return
      if (typeof ticket.ticket !== 'string' || !/^[A-Za-z0-9_-]{16,128}$/.test(ticket.ticket)) throw new Error('Invalid local WebSocket ticket.')
      const url = new URL('/ws/app', window.location.href)
      url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      url.searchParams.set('ticket', ticket.ticket)
      const socket = new WebSocket(url)
      this.socket = socket
      socket.onopen = () => { if (this.socket === socket && !this.closed) { this.reconnectAttempt = 0; this.onConnection(true) } }
      socket.onmessage = message => { if (this.socket === socket && !this.closed) { const event = parseEvent(String(message.data)); if (event) this.onEvent(event) } }
      socket.onerror = () => socket.close()
      socket.onclose = () => {
        if (this.socket !== socket || this.closed) return
        this.socket = null
        this.onConnection(false, 'Live updates disconnected. Reconnecting locally…')
        this.retry(generation)
      }
    } catch { if (!this.closed && generation === this.generation) { this.onConnection(false, 'Local connection unavailable.'); this.retry(generation) } }
  }

  private retry(generation: number) {
    if (this.closed || generation !== this.generation || this.reconnectAttempt >= 7 || this.reconnectTimer) return
    const delay = Math.min(15000, 600 * 2 ** this.reconnectAttempt++)
    this.reconnectTimer = setTimeout(() => { this.reconnectTimer = null; void this.openSocket(generation) }, delay)
  }

  chat(text: string, requestId: string) { return this.request<ChatReply>('/api/bel/chat', { text, requestId }, 135000) }

  async prepare(proposal: Proposal): Promise<PreparedAction> {
    if (!actionPaths.has(proposal.path)) throw new Error('This action cannot be approved from the BEL interface.')
    const value = await this.request<{ approvalId: string; args: Record<string, unknown>; summary: string; expiresIn: number }>('/api/actions/prepare', { path: proposal.path, args: proposal.args })
    if (typeof value.approvalId !== 'string' || typeof value.summary !== 'string' || !Number.isFinite(value.expiresIn) || value.expiresIn <= 0 || value.expiresIn > 60 || !value.args || typeof value.args !== 'object' || Array.isArray(value.args)) throw new Error('Invalid approval preview.')
    return { ...proposal, args: value.args, summary: value.summary, approvalId: value.approvalId, expiresAt: Date.now() + value.expiresIn * 1000 }
  }

  execute(action: PreparedAction) {
    if (!actionPaths.has(action.path) || Date.now() >= action.expiresAt) return Promise.reject(new Error('Approval expired. Review a fresh preview.'))
    return this.request<Record<string, unknown>>(action.path, { ...action.args, actionApproval: action.approvalId }, 135000)
  }

  disconnect() {
    this.closed = true
    this.generation += 1
    this.csrf = ''
    this.reconnectAttempt = 0
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    const socket = this.socket
    this.socket = null
    if (socket) socket.close()
  }
}
