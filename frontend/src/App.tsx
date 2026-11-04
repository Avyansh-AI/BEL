import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { AnimatePresence, MotionConfig, motion, useReducedMotion } from 'framer-motion'
import { AudioLines, Check, ChevronDown, CircleHelp, History, Mic, MicOff, Minus, PanelTop, Send, Settings2, Volume2, Square, X } from 'lucide-react'
import { BelApiClient, parseHistory } from './lib/belApi'
import type { BelEvent, BelState, BelStatus, HistoryItem, PreparedAction, Proposal } from './lib/belApi'
import { LocalCapture, toBase64 } from './lib/voice'
import { Orb } from './components/Orb'
import type { OrbState } from './components/Orb'
import { Overlay } from './components/Overlay'
import { readyNativeApi } from './lib/native'
import { ToolsPanel } from './components/ToolsPanel'

type UserSettings = { animations: 'natural' | 'reduced'; theme: 'midnight' | 'blue' }
type NativeMode = 'active' | 'compact' | 'background'
type NativeStatus = { available: boolean; mode: NativeMode; tray_available: boolean }
type DesktopBridge = { set_mode: (mode: NativeMode) => Promise<NativeStatus>; status: () => Promise<NativeStatus>; close_app: () => Promise<unknown> }
type DesktopWindow = Window & { pywebview?: { api: DesktopBridge } }
type Memory = { id: string; store: string; project_id: string; key: string; content: string; source_uri: string; privacy_scope: string; confidence: number; expiry: number | null }
type Provider = { id: string; policy: Record<string, unknown>; status: string; reason?: string }
type Panel = 'settings' | 'history' | 'memory' | 'providers' | 'diagnostics' | 'tools' | null
const labels: Record<BelState, string> = { idle: 'Here when you need me', wake_word: 'Wake word detected', listening: 'Listening…', speech_recognition: 'Transcribing locally…', thinking: 'Thinking…', tool_execution: 'Carrying out your approved action…', speaking: 'Speaking…', task_completed: 'Task completed', error: 'Something needs attention', offline: 'Local service disconnected', background: 'Running in the background' }
const visualState = (state: BelState): OrbState => state === 'wake_word' || state === 'task_completed' ? 'happy' : state === 'tool_execution' || state === 'speech_recognition' ? 'thinking' : state === 'background' ? 'idle' : state
const message = (error: unknown) => error instanceof Error ? error.message : 'The request could not be completed.'
const makeId = () => crypto.randomUUID()
const bridge = () => { const api = (window as DesktopWindow).pywebview?.api; return readyNativeApi(api) ? api : undefined }
const defaultSettings: UserSettings = { animations: 'natural', theme: 'midnight' }
function readSettings(): UserSettings {
  try { const v = JSON.parse(localStorage.getItem('bel-interface-settings-v1') || '{}'); return { animations: v.animations === 'reduced' ? 'reduced' : 'natural', theme: v.theme === 'blue' ? 'blue' : 'midnight' } } catch { return defaultSettings }
}

export default function App() {
  const [settings, setSettings] = useState(readSettings)
  const [messages, setMessages] = useState<HistoryItem[]>([])
  const [state, setState] = useState<BelState>('offline')
  const [status, setStatus] = useState<BelStatus | null>(null)
  const statusRef = useRef<BelStatus | null>(null)
  const [connected, setConnected] = useState(false)
  const connectedRef = useRef(false)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const [panel, setPanel] = useState<Panel>(null)
  const [compact, setCompact] = useState(false)
  const [native, setNative] = useState<NativeStatus | null>(null)
  const [toast, setToast] = useState('')
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [approval, setApproval] = useState<PreparedAction | null>(null)
  const [now, setNow] = useState(Date.now())
  const [audioLevel, setAudioLevel] = useState(0)
  const [micAllowed, setMicAllowed] = useState(false)
  const [recording, setRecording] = useState(false)
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [device, setDevice] = useState('')
  const [playing, setPlaying] = useState(false)
  const [audioReady, setAudioReady] = useState('')
  const [memories, setMemories] = useState<Memory[]>([])
  const [memoryQuery, setMemoryQuery] = useState('')
  const [memoryProject, setMemoryProject] = useState('default')
  const [memoryEdit, setMemoryEdit] = useState<Memory | null>(null)
  const [memoryKey, setMemoryKey] = useState('')
  const [memoryContent, setMemoryContent] = useState('')
  const [providers, setProviders] = useState<Provider[]>([])
  const [selectedProvider, setSelectedProvider] = useState('')
  const [providerPolicy, setProviderPolicy] = useState<Record<string, unknown>>({})
  const [localOnly, setLocalOnly] = useState(false)
  const [diagnostics, setDiagnostics] = useState<unknown>(null)
  const [toolsRevision, setToolsRevision] = useState(0)
  const api = useRef(new BelApiClient()).current
  const activeRequest = useRef('')
  const capture = useRef<LocalCapture | null>(null)
  const held = useRef(false)
  const audio = useRef<HTMLAudioElement | null>(null)
  const mounted = useRef(true)
  const systemReduced = useReducedMotion()
  const reducedMotion = settings.animations === 'reduced' || systemReduced === true
  const canRecord = !!(status?.voice.stt_available && status.voice.recording_supported && navigator.mediaDevices?.getUserMedia)

  const notify = (text: string) => { if (mounted.current) setToast(text) }
  const report = (error: unknown) => { if (mounted.current) { setState('error'); notify(message(error)) } }
  const refreshHistory = async () => { const data = await api.request<{ items: unknown }>('/api/bel/history'); if (mounted.current && !busyRef.current) setMessages(parseHistory(data.items)) }
  const refreshStatus = async () => { const data = await api.request<BelStatus>('/api/bel/status'); if (mounted.current) { statusRef.current = data; setStatus(data) } }
  const stopPlayback = () => { if (audio.current) { audio.current.pause(); audio.current.currentTime = 0; audio.current = null } setPlaying(false); setState(connectedRef.current ? 'idle' : 'offline') }
  const cancelCapture = () => { held.current = false; capture.current?.stop(false); capture.current = null; setRecording(false); setAudioLevel(0) }

  const onEvent = (event: BelEvent) => {
    if (event.requestId && event.requestId !== activeRequest.current) return
    if (event.type === 'error') { notify(event.message); if (!audio.current && !capture.current) setState('error'); return }
    // Only actual local playback/capture drives these two states.
    if (event.state === 'speaking' || event.state === 'listening' || audio.current || capture.current) return
    if (event.state === 'wake_word' && !statusRef.current?.voice.wake_available) return
    setState(event.state)
  }
  const connect = () => {
    void api.connect(onEvent, (value, reason) => {
      if (!mounted.current) return
      connectedRef.current = value; setConnected(value)
      if (!audio.current && !capture.current && !busyRef.current) setState(value ? 'idle' : 'offline')
      if (reason) notify(reason)
      if (value) { void refreshStatus().catch(report); void refreshHistory().catch(report) }
    })
  }

  useEffect(() => {
    mounted.current = true
    connect()
    const nativeReady = () => { const host = bridge(); if (host) void host.status().then(s => { if (mounted.current) { setNative(s); setCompact(s.mode === 'compact') } }).catch(report) }
    const nativeMode = (event: Event) => { const mode = (event as CustomEvent<{ mode: NativeMode }>).detail?.mode; if (['active', 'compact', 'background'].includes(mode)) { setCompact(mode === 'compact'); setNative(s => s ? { ...s, mode } : s); if (mode === 'background' && !busyRef.current) setState('background') } }
    const cancel = () => { if (capture.current) { cancelCapture(); setState(connectedRef.current ? 'idle' : 'offline') } }
    const visibility = () => { if (document.hidden) cancel() }
    nativeReady()
    window.addEventListener('pywebviewready', nativeReady)
    window.addEventListener('bel-native-mode', nativeMode)
    window.addEventListener('blur', cancel)
    document.addEventListener('visibilitychange', visibility)
    return () => { mounted.current = false; api.disconnect(); capture.current?.stop(false); capture.current = null; audio.current?.pause(); audio.current = null; window.removeEventListener('pywebviewready', nativeReady); window.removeEventListener('bel-native-mode', nativeMode); window.removeEventListener('blur', cancel); document.removeEventListener('visibilitychange', visibility) }
  }, [])
  useEffect(() => { try { localStorage.setItem('bel-interface-settings-v1', JSON.stringify(settings)) } catch { /* Appearance can work without storage. */ } }, [settings])
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(''), 8000); return () => clearTimeout(timer) }, [toast])
  useEffect(() => { if (!approval) return; const timer = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(timer) }, [approval])
  useEffect(() => { const list = () => { if (micAllowed) void navigator.mediaDevices?.enumerateDevices().then(items => setDevices(items.filter(d => d.kind === 'audioinput'))).catch(() => setDevices([])) }; list(); navigator.mediaDevices?.addEventListener('devicechange', list); return () => navigator.mediaDevices?.removeEventListener('devicechange', list) }, [micAllowed])

  const sendMessage = async (raw: string) => {
    const text = raw.trim()
    if (!text || text.length > 8000 || busyRef.current || !connectedRef.current || approval) return
    stopPlayback(); cancelCapture(); setAudioReady(''); setProposal(null)
    busyRef.current = true; setBusy(true); setInput(''); setState('thinking')
    const requestId = makeId(); activeRequest.current = requestId
    const assistantId = requestId + '-assistant'
    setMessages(rows => [...rows, { id: requestId + '-user', role: 'user' as const, text, at: Date.now() / 1000 }, { id: assistantId, role: 'assistant' as const, text: '', at: Date.now() / 1000 }].slice(-200))
    try {
      const reply = await api.chat(text, requestId)
      if (reply.requestId !== requestId || typeof reply.say !== 'string' || !reply.say.trim()) throw new Error('BEL returned an invalid or empty reply. Review task history before retrying.')
      if (!mounted.current) return
      setMessages(rows => rows.map(row => row.id === assistantId ? { ...row, text: reply.say } : row))
      setProposal(reply.proposal || null)
      setState(['ok', 'done', 'pending_confirmation'].includes(reply.status) ? 'idle' : 'error')
    } catch (error) {
      if (mounted.current) { setMessages(rows => rows.map(row => row.id === assistantId ? { ...row, text: message(error) } : row)); report(error) }
    } finally { busyRef.current = false; if (mounted.current) setBusy(false) }
  }
  const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); void sendMessage(input) }

  const prepare = async (value: Proposal) => {
    if (busyRef.current || approval) return
    busyRef.current = true; setBusy(true)
    try { const action = await api.prepare(value); if (mounted.current) { setNow(Date.now()); setApproval(action) } } catch (error) { report(error) }
    finally { busyRef.current = false; if (mounted.current) setBusy(false) }
  }
  const execute = async () => {
    if (!approval || busyRef.current || Date.now() >= approval.expiresAt) return
    const action = approval; setApproval(null); setProposal(null)
    busyRef.current = true; setBusy(true); setState('tool_execution')
    try {
      const result = await api.execute(action)
      if (!mounted.current) return
      if (action.path === '/api/capability/invoke' && action.args.id === 'speech.render') {
        const artifact = (result.result as { artifact?: { download?: string } } | undefined)?.artifact
        if (!artifact?.download || !/^\/api\/capability\/artifacts\/[a-f0-9]{32}\.wav$/.test(artifact.download)) throw new Error('Speech output did not contain a valid local WAV artifact.')
        setAudioReady(artifact.download); notify('Speech is ready. Press Play audio to listen.')
      } else if (action.path === '/api/bel/history/clear') setMessages([])
      else if (action.path.startsWith('/api/learning/memory/')) { setMemoryEdit(null); setMemoryContent(''); setMemoryKey(''); void loadMemories().catch(report) }
      else if (action.path === '/api/models/configure') void loadProviders().catch(report)
      const outcome = typeof result.status === 'string' ? result.status : typeof (result.outcome as { status?: unknown } | undefined)?.status === 'string' ? (result.outcome as { status: string }).status : ''
      const say = typeof result.say === 'string' ? result.say : outcome ? `Action result: ${outcome}.` : 'The local service returned the action result.'
      if (action.path === '/api/bel/tools/execute') { setMessages(rows => [...rows, { id: makeId(), role: 'assistant' as const, text: say, at: Date.now() / 1000 }].slice(-200)); setToolsRevision(value => value + 1) }
      setState(outcome === 'failed' || outcome === 'unverified' ? 'error' : 'task_completed')
      if (action.path !== '/api/capability/invoke') notify(say)
    } catch (error) { report(error) }
    finally { busyRef.current = false; if (mounted.current) setBusy(false) }
  }

  const playAudio = async () => {
    if (!audioReady || busyRef.current) return
    stopPlayback(); cancelCapture()
    const player = new Audio(audioReady); audio.current = player
    player.onplaying = () => { if (audio.current === player) { setPlaying(true); setState('speaking') } }
    player.onended = () => { if (audio.current === player) { audio.current = null; setPlaying(false); setState(connectedRef.current ? 'idle' : 'offline') } }
    player.onerror = () => { if (audio.current === player) { audio.current = null; setPlaying(false); report(new Error('The local WAV could not be played.')) } }
    try { await player.play() } catch (error) { if (audio.current === player) { audio.current = null; setPlaying(false); report(error) } }
  }
  const finishCapture = async () => {
    held.current = false
    const current = capture.current; capture.current = null
    if (!current) return
    const wav = current.stop(true); setRecording(false); setAudioLevel(0)
    if (!wav) { setState(connectedRef.current ? 'idle' : 'offline'); return }
    busyRef.current = true; setBusy(true); setState('speech_recognition')
    try {
      const result = await api.request<{ text: string }>('/api/speech/transcribe', { audio: toBase64(wav), mimeType: 'audio/wav' }, 60000)
      if (typeof result.text !== 'string' || result.text.length > 8000) throw new Error('Local transcription returned an invalid result.')
      setInput(result.text); setState('idle'); notify('Transcript ready. Review it and press Send.')
    } catch (error) { report(error) }
    finally { busyRef.current = false; if (mounted.current) setBusy(false) }
  }
  const startCapture = async () => {
    if (!micAllowed || !canRecord || busyRef.current || capture.current || approval || !connectedRef.current) return
    held.current = true; stopPlayback()
    const current = new LocalCapture(); capture.current = current
    try {
      const started = await current.start(device, setAudioLevel, () => void finishCapture())
      if (!started || !held.current || capture.current !== current || !mounted.current) { current.stop(false); return }
      setRecording(true); setState('listening')
    } catch { if (capture.current === current) { cancelCapture(); report(new Error('Microphone access failed. Check permission and the selected audio device.')) } }
  }
  const setMode = async (mode: NativeMode) => {
    if (mode === 'background' && !native?.tray_available) return
    try { const host = bridge(); if (host) { const result = await host.set_mode(mode); setNative(result); setCompact(result.mode === 'compact') } else if (mode !== 'background') setCompact(mode === 'compact') } catch (error) { report(error) }
  }

  const loadMemories = async () => {
    if (!/^[A-Za-z0-9_-]{1,80}$/.test(memoryProject)) throw new Error('Use a simple project name (letters, digits, underscore or hyphen).')
    const result = await api.request<{ items: Memory[] }>('/api/learning/memory?project_id=' + encodeURIComponent(memoryProject) + '&q=' + encodeURIComponent(memoryQuery))
    setMemories(Array.isArray(result.items) ? result.items.slice(0, 200) : [])
  }
  const saveMemory = () => {
    const args: Record<string, unknown> = { store: memoryEdit?.store || 'profile', project_id: memoryEdit?.project_id || memoryProject, key: memoryKey, content: memoryContent, source_uri: memoryEdit?.source_uri || 'owner_statement', privacy_scope: memoryEdit?.privacy_scope || 'local', confidence: memoryEdit?.confidence ?? 1, ttl_days: memoryEdit?.expiry ? Math.max(1, Math.ceil((memoryEdit.expiry - Date.now() / 1000) / 86400)) : null }
    if (memoryEdit) args.id = memoryEdit.id
    void prepare({ path: '/api/learning/memory/' + (memoryEdit ? 'edit' : 'save'), args, summary: 'Review this memory.' })
  }
  const loadProviders = async () => {
    const result = await api.request<{ items: Provider[]; local_only: boolean }>('/api/bel/providers')
    const rows = result.items.filter(x => ['groq', 'gemini', 'openrouter'].includes(x.id))
    setProviders(rows); setLocalOnly(result.local_only)
    const row = rows.find(x => x.id === selectedProvider) || rows[0]
    if (row) { setSelectedProvider(row.id); setProviderPolicy({ ...row.policy }) }
  }
  const openPanel = (value: Panel) => {
    setPanel(value)
    if (value === 'history' && !busyRef.current) void refreshHistory().catch(report)
    if (value === 'memory') void loadMemories().catch(report)
    if (value === 'providers') void loadProviders().catch(report)
    if (value === 'diagnostics') void Promise.all([api.request('/api/models'), api.request('/api/bel/status')]).then(([models, bel]) => setDiagnostics({ bel, models })).catch(report)
  }
  const lastUser = [...messages].reverse().find(x => x.role === 'user')
  const lastBel = [...messages].reverse().find(x => x.role === 'assistant')

  return <MotionConfig reducedMotion={reducedMotion ? 'always' : 'never'}>
    <div className={`app app--${settings.theme}${compact ? ' app--compact' : ''}${reducedMotion ? ' app--reduced' : ''}`}>
      <div className="ambient ambient--left" /><div className="ambient ambient--right" />
      <header className="topbar">
        <div className="brand" aria-label="BEL, Behavioral Executive Logic"><img className="brand-mark" src="/bel-logo.webp" alt="BEL logo" /><div className="brand-copy"><span className="brand-name">BEL</span><span className="brand-subtitle">BEHAVIORAL EXECUTIVE LOGIC</span></div></div>
        <div className="connection-note"><span className={`connection-dot${connected ? ' is-connected' : ''}`} />{connected ? 'LOCALLY CONNECTED' : 'SERVICE DISCONNECTED'}</div>
        <nav className="window-actions" aria-label="Window and app controls">
          <button className={`icon-button${compact ? ' is-active' : ''}`} type="button" onClick={() => void setMode(compact ? 'active' : 'compact')} aria-label={compact ? 'Return to full window' : 'Switch to compact mode'} title="Compact mode"><PanelTop size={16} strokeWidth={1.7} /></button>
          <button className="icon-button" type="button" onClick={() => openPanel('history')} aria-label="Conversation history" title="Conversation history"><History size={16} strokeWidth={1.7} /></button>
          <button className="icon-button" type="button" onClick={() => openPanel('settings')} aria-label="Settings" title="Settings"><Settings2 size={16} strokeWidth={1.7} /></button>
          <span className="window-separator" />
          <button className="icon-button window-button" type="button" disabled={!native?.tray_available} onClick={() => void setMode('background')} aria-label="Minimize to tray" title={native?.tray_available ? 'Minimize to tray' : 'Available in BEL desktop'}><Minus size={16} strokeWidth={1.7} /></button>
          <button className="icon-button close-button" type="button" disabled={!native?.available} onClick={() => { void bridge()?.close_app().catch(report) }} aria-label="Exit BEL" title="Exit BEL"><X size={16} strokeWidth={1.7} /></button>
        </nav>
      </header>
      <main className="main-stage">
        <div className="presence-label"><span className="presence-line" /><span>A QUIETLY INTELLIGENT PRESENCE</span><span className="presence-line" /></div>
        <div className="hero-orb-wrap"><Orb state={visualState(state)} audioLevel={audioLevel} reducedMotion={reducedMotion} /><div className="orb-caption"><span className={`state-indicator state-indicator--${visualState(state)}`} /><span>{state === 'offline' && connected ? 'Working locally' : labels[state]}</span></div></div>
        <section className="conversation" aria-live="polite" aria-label="Recent conversation">
          <AnimatePresence mode="wait"><motion.div className="conversation-content" key={`${lastUser?.id ?? 'hello'}-${lastBel?.id ?? ''}`} initial={{ opacity: 0, y: 7 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }} transition={{ duration: 0.22 }}>
            {lastUser && <div className="conversation-line conversation-line--user"><span className="speaker-label">YOU</span><p>{lastUser.text}</p></div>}
            <div className="conversation-line conversation-line--bel"><span className="speaker-label">BEL</span><p>{lastBel?.text || (busy ? 'Thinking…' : 'Hello, Avyansh. I’m here when you need me.')}</p></div>
          </motion.div></AnimatePresence>
        </section>
        <div className="demo-control">
          {proposal && <button className="demo-button" disabled={busy || !!approval} onClick={() => void prepare(proposal)}>Review {proposal.tool || 'proposed action'}</button>}
          {playing ? <button className="demo-button" onClick={stopPlayback}><Square size={13} />STOP SPEAKING</button> : audioReady ? <button className="demo-button" disabled={busy} onClick={() => void playAudio()}><Volume2 size={13} />PLAY AUDIO</button> : lastBel?.text && status?.voice.tts_available && <button className="demo-button" disabled={busy || !!approval || lastBel.text.length > 500} title={lastBel.text.length > 500 ? 'Local voice currently accepts up to 500 characters.' : 'Review local speech generation'} onClick={() => void prepare({ path: '/api/capability/invoke', args: { id: 'speech.render', arguments: { text: lastBel.text } }, summary: 'Render this reply with the installed local voice.' })}><Volume2 size={13} />READ REPLY ALOUD</button>}
          {!connected && <button className="demo-button" onClick={connect}>RECONNECT</button>}
        </div>
      </main>
      <footer className="input-area">
        <form className="input-pill" onSubmit={submit}>
          <button className={`mic-button${recording ? ' is-listening' : ''}`} type="button" disabled={!micAllowed || !canRecord || busy || !connected || !!approval} aria-label="Hold to talk" title={!canRecord ? 'Local speech recognition is unavailable; use text input.' : !micAllowed ? 'Enable microphone consent in Settings.' : 'Hold to talk; release to transcribe locally.'} onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); void startCapture() }} onPointerUp={() => void finishCapture()} onPointerCancel={() => { cancelCapture(); setState('idle') }} onKeyDown={event => { if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) { event.preventDefault(); void startCapture() } }} onKeyUp={event => { if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); void finishCapture() } }}>
            {micAllowed && canRecord ? <Mic size={18} strokeWidth={1.8} /> : <MicOff size={18} strokeWidth={1.8} />}
          </button>
          <input value={input} onChange={event => setInput(event.target.value)} maxLength={8000} placeholder="Talk to BEL…" aria-label="Message BEL" autoComplete="off" />
          <span className="input-hint">↵</span><button className="send-button" type="submit" aria-label="Send message" disabled={!input.trim() || busy || !connected || !!approval} title="Send message"><Send size={16} strokeWidth={1.8} /></button>
        </form>
        <div className="input-meta"><span><AudioLines size={12} />{recording ? 'MICROPHONE ACTIVE' : 'LOCAL-FIRST ASSISTANT'}</span><span className="meta-divider" /><span>{status?.voice.wake_available ? 'BEL WAKE WORD AVAILABLE' : 'WAKE WORD NOT ENROLLED'}</span></div>
      </footer>
      <AnimatePresence>
        {panel && !approval && <Overlay label={panel === 'history' ? 'Conversation history' : 'BEL ' + panel} onClose={() => setPanel(null)}>
          <div className="overlay-header"><div><span className="overlay-eyebrow">YOUR LOCAL ASSISTANT</span><h2>{panel === 'history' ? 'Conversation history' : panel === 'memory' ? 'Memory' : panel === 'providers' ? 'AI providers' : panel === 'diagnostics' ? 'Diagnostics' : panel === 'tools' ? 'Tools and undo' : 'Settings'}</h2></div><button className="overlay-close" onClick={() => setPanel(null)} aria-label="Close panel"><X size={17} /></button></div>
          {panel === 'history' && <><div className="history-list">{messages.length ? [...messages].reverse().map(row => <article className={`history-item history-item--${row.role === 'user' ? 'you' : 'bel'}`} key={row.id}><div className="history-item-meta"><span>{row.role === 'user' ? 'YOU' : 'BEL'}</span><time>{new Date(row.at < 1e12 ? row.at * 1000 : row.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div><p>{row.text || 'Thinking…'}</p></article>) : <div className="empty-state"><History size={21} /><p>Your conversations will appear here.</p><span>Send a message to begin.</span></div>}</div><div className="overlay-footnote">Up to 200 messages in BEL’s local data store. Browser demo history is retained separately and is not imported.</div><button className="text-button" disabled={!messages.length || busy} onClick={() => void prepare({ path: '/api/bel/history/clear', args: {}, summary: 'Clear BEL conversation history.' })}>Review clearing history</button></>}
          {panel === 'settings' && <div className="settings-list scroll-panel">
            <div className="setting-row"><div className="setting-copy"><strong>Animation</strong><span>Choose how much movement BEL uses.</span></div><label className="select-wrap"><select aria-label="Animation" value={settings.animations} onChange={e => setSettings(s => ({ ...s, animations: e.target.value === 'reduced' ? 'reduced' : 'natural' }))}><option value="natural">Natural</option><option value="reduced">Reduced</option></select><ChevronDown size={13} /></label></div>
            <div className="setting-row"><div className="setting-copy"><strong>Appearance</strong><span>Subtle variations on the midnight palette.</span></div><label className="select-wrap"><select aria-label="Appearance" value={settings.theme} onChange={e => setSettings(s => ({ ...s, theme: e.target.value === 'blue' ? 'blue' : 'midnight' }))}><option value="midnight">Midnight</option><option value="blue">Blue hour</option></select><ChevronDown size={13} /></label></div>
            <div className="setting-row"><div className="setting-copy"><strong>Microphone consent</strong><span>{canRecord ? 'Allow hold-to-talk for this session. Audio goes only to local speech recognition; review the transcript before sending.' : status?.voice.reason || 'Local speech recognition is not configured. The microphone stays off.'}</span></div><button className={`switch${micAllowed ? ' is-on' : ''}`} disabled={!canRecord} role="switch" aria-checked={micAllowed} aria-label="Microphone consent" onClick={() => { if (micAllowed) { cancelCapture(); setState('idle') } setMicAllowed(!micAllowed) }}><span /></button></div>
            {micAllowed && <label className="field-label">Microphone<select value={device} aria-label="Microphone device" onChange={e => { cancelCapture(); setDevice(e.target.value); setState('idle') }}><option value="">System default</option>{devices.filter(d => d.deviceId && d.deviceId !== 'default').map((d, i) => <option key={d.deviceId} value={d.deviceId}>{d.label || `Microphone ${i + 1}`}</option>)}</select></label>}
            <div className="setting-info"><CircleHelp size={15} /><p>{status?.voice.wake_available ? 'A configured BEL wake service is available.' : 'BEL wake-word enrollment is unavailable until a valid trained model and owner consent are provided.'}<br />No sleeping-mode microphone audio is sent to the cloud.</p></div>
            <button className="panel-link" onClick={() => openPanel('providers')}>AI providers <ChevronDown size={13} /></button><button className="panel-link" onClick={() => openPanel('memory')}>Memory management <ChevronDown size={13} /></button><button className="panel-link" onClick={() => openPanel('diagnostics')}>Diagnostics <ChevronDown size={13} /></button>
            <button className="panel-link" onClick={() => openPanel('tools')}>Tools and undo <ChevronDown size={13} /></button>
            <a className="panel-link" href="/legacy/" target="_blank" rel="noreferrer">Advanced workspace</a>
            <div className="overlay-footnote"><Check size={13} /> Appearance is saved locally. Microphone consent expires when this page closes.</div>
          </div>}
          {panel === 'tools' && <ToolsPanel key={toolsRevision} api={api} review={prepare} busy={busy} />}
          {panel === 'memory' && <div className="scroll-panel">
            <label className="field-label">Project<input aria-label="Memory project" value={memoryProject} maxLength={80} onChange={e => setMemoryProject(e.target.value)} /></label>
            <form onSubmit={e => { e.preventDefault(); void loadMemories().catch(report) }} className="search-row"><input aria-label="Search memories" value={memoryQuery} maxLength={200} onChange={e => setMemoryQuery(e.target.value)} placeholder="Search memories" /><button className="text-button">Search</button></form>
            {memories.map(row => <article className="memory-item" key={row.id}><strong>{row.key}</strong><p>{row.content}</p><small>{row.store} · {row.privacy_scope} · {row.source_uri}</small><div className="action-row"><button className="text-button" disabled={busy} onClick={() => { setMemoryEdit(row); setMemoryKey(row.key); setMemoryContent(row.content) }}>Correct</button><button className="text-button" disabled={busy} onClick={() => void prepare({ path: '/api/learning/memory/delete', args: { id: row.id }, summary: 'Forget this memory and derived summaries.' })}>Review deletion</button></div></article>)}
            <label className="field-label">{memoryEdit ? 'Correct memory' : 'New local memory'}<input aria-label="Memory key" value={memoryKey} maxLength={80} onChange={e => setMemoryKey(e.target.value)} placeholder="preference.name" /></label><textarea aria-label="Memory content" value={memoryContent} maxLength={12000} onChange={e => setMemoryContent(e.target.value)} placeholder="A fact or preference to remember" rows={4} />
            <div className="action-row"><button className="text-button" disabled={busy || !memoryKey || !memoryContent} onClick={saveMemory}>Review memory</button>{memoryEdit && <button className="text-button" onClick={() => { setMemoryEdit(null); setMemoryKey(''); setMemoryContent('') }}>Cancel correction</button>}</div>
            <p className="overlay-footnote">Memories are data, not executable instructions. Deletion also removes derived summaries; separate backups and task receipts may retain earlier text.</p>
          </div>}
          {panel === 'providers' && <div className="scroll-panel">
            <p className="setting-description">Gemma remains the first choice. Select a cloud fallback policy to review; disabled providers receive no requests. This panel only permits free use.</p>
            <label className="field-label">Fallback provider<select aria-label="AI provider" value={selectedProvider} onChange={e => { setSelectedProvider(e.target.value); setProviderPolicy({ ...providers.find(p => p.id === e.target.value)?.policy }) }}><option value="" disabled>Select provider</option>{providers.map(p => <option key={p.id} value={p.id}>{p.id} · {p.status}</option>)}</select></label>
            {selectedProvider && <><label className="field-label">Model<input aria-label="Provider model" value={String(providerPolicy.model || '')} maxLength={150} onChange={e => setProviderPolicy(p => ({ ...p, model: e.target.value }))} /></label><label className="checkbox-row"><input type="checkbox" checked={providerPolicy.enabled === true} onChange={e => setProviderPolicy(p => ({ ...p, enabled: e.target.checked }))} />Enable this fallback</label><label className="checkbox-row"><input type="checkbox" checked={providerPolicy.allow_remote_text === true} onChange={e => setProviderPolicy(p => ({ ...p, allow_remote_text: e.target.checked }))} />Allow typed text to this provider</label>{selectedProvider !== 'openrouter' && <label className="checkbox-row"><input type="checkbox" checked={providerPolicy.free_tier_confirmed === true} onChange={e => setProviderPolicy(p => ({ ...p, free_tier_confirmed: e.target.checked }))} />My account is Free tier with paid billing disabled</label>}<p className="setting-description">Daily request cap: {String(providerPolicy.daily_request_limit ?? 'unknown')} · daily token cap: {String(providerPolicy.daily_token_limit ?? 'unknown')}. The existing quota ledger is preserved. {selectedProvider === 'openrouter' ? 'An exact :free model is required.' : ''}</p><button className="text-button" disabled={busy || localOnly || !providerPolicy.provider} onClick={() => void prepare({ path: '/api/models/configure', args: { ...providerPolicy, free_only: true, billing_enabled: false, daily_budget_usd: 0, input_usd_per_million: 0, output_usd_per_million: 0 }, summary: 'Review the free provider policy.' })}>Review provider policy</button></>}
            {localOnly && <p className="setting-description">This backend was launched in local-only mode. Cloud routing remains blocked.</p>}
          </div>}
          {panel === 'diagnostics' && <div className="scroll-panel"><p className="setting-description">Live status from the local service. A configured integration is only verified after its acceptance tests pass.</p><pre className="json-preview">{JSON.stringify(diagnostics, null, 2)}</pre></div>}
        </Overlay>}
        {approval && <Overlay label="Confirm action" onClose={() => { if (!busy) setApproval(null) }}><div className="overlay-header"><div><span className="overlay-eyebrow">OWNER AUTHORIZATION</span><h2>Review this action</h2></div><button className="overlay-close" onClick={() => setApproval(null)} aria-label="Cancel approval"><X size={17} /></button></div><div className="scroll-panel"><p className="setting-description">{approval.summary}</p><pre className="json-preview">{JSON.stringify(approval.args, null, 2)}</pre><p className="overlay-footnote">{now >= approval.expiresAt ? 'This preview has expired. Cancel and request a new preview.' : `One use only · expires in ${Math.ceil((approval.expiresAt - now) / 1000)} seconds.`}</p></div><div className="action-row"><button className="text-button" onClick={() => setApproval(null)}>Cancel</button><button className="primary-button" disabled={busy || now >= approval.expiresAt} onClick={() => void execute()}>Approve once</button></div></Overlay>}
      </AnimatePresence>
      <AnimatePresence>{toast && <motion.div className="toast" role="status" style={{ x: '-50%' }} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}><span className="toast-dot" />{toast}</motion.div>}</AnimatePresence>
    </div>
  </MotionConfig>
}
