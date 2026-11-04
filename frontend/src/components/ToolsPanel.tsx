import { useEffect, useState } from 'react'
import type { BelApiClient, Proposal } from '../lib/belApi'

type Tool = { name: string; description: string; input_schema: unknown; permissions: string[]; risk: string; reversible: boolean }
type Undo = { id: string; operation: string; state: string; name?: string; original_name?: string }

export function ToolsPanel({ api, review, busy = false }: { api: BelApiClient; review: (proposal: Proposal) => Promise<void>; busy?: boolean }) {
  const [tools, setTools] = useState<Tool[]>([])
  const [undo, setUndo] = useState<Undo[]>([])
  const [name, setName] = useState('files.list')
  const [args, setArgs] = useState('{}')
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState(false)
  const selected = tools.find(tool => tool.name === name)
  useEffect(() => {
    let mounted = true
    void Promise.all([api.request<{ items: Tool[] }>('/api/bel/tools'), api.request<{ items: Undo[] }>('/api/bel/undo')]).then(([registry, journal]) => {
      if (mounted) { setTools(registry.items); setUndo(journal.items.filter(item => item.state === 'ready')); setLoaded(true) }
    }).catch(() => { if (mounted) setError('Tool registry is unavailable.') })
    return () => { mounted = false }
  }, [api])
  const propose = async (tool: string, argumentsValue: Record<string, unknown>) => {
    await review({ path: '/api/bel/tools/execute', tool, summary: selected?.description || tool,
      args: { tool, arguments: argumentsValue, executionId: crypto.randomUUID(), taskId: crypto.randomUUID() } })
  }
  return <div className="scroll-panel">
    <p className="setting-description">Review an exact registered action here when automatic routing needs clarification. Nothing runs until you approve the preview.</p>
    <label className="field-label">Tool<select aria-label="Registered tool" value={name} onChange={event => { setName(event.target.value); setArgs('{}'); setError('') }}>
      {tools.map(tool => <option key={tool.name} value={tool.name}>{tool.name}</option>)}
    </select></label>
    {selected && <><p className="setting-description">{selected.description}</p><p className="overlay-footnote">Permission: {selected.permissions.join(', ')} · Risk: {selected.risk} · Undo: {selected.reversible ? 'supported with state checks' : 'not promised'}</p><details><summary>Argument schema</summary><pre className="json-preview">{JSON.stringify(selected.input_schema, null, 2)}</pre></details></>}
    <label className="field-label">Arguments (JSON)<textarea aria-label="Tool arguments" rows={5} value={args} maxLength={70000} onChange={event => setArgs(event.target.value)} /></label>
    {error && <p role="alert">{error}</p>}
    <button className="primary-button" disabled={!selected || busy} onClick={() => { try { const parsed = JSON.parse(args); if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw Error(); setError(''); void propose(name, parsed) } catch { setError('Enter a JSON object. The backend validates every field before preparing a preview.') } }}>Review tool action</button>
    <h3>Reversible file actions</h3>
    {busy ? <p className="setting-description">An action is in progress. Results will refresh after completion.</p> : !loaded ? <p className="setting-description">Loading the verified undo journal…</p> : undo.length ? undo.map(item => <div className="memory-item" key={item.id}><p>{item.operation}{item.name ? ' · ' + item.name : ''}{item.original_name && item.original_name !== item.name ? ' → ' + item.original_name : ''}</p><button className="text-button" onClick={() => void propose('files.undo', { undo_id: item.id })}>Review undo</button></div>) : <p className="setting-description">No verified file action is available to undo.</p>}
  </div>
}
