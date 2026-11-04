import { afterEach, test } from 'node:test'
import assert from 'node:assert/strict'
import { BelApiClient, parseEvent, parseHistory } from '../src/lib/belApi.ts'

const saved = { fetch: globalThis.fetch, window: globalThis.window, WebSocket: globalThis.WebSocket }
const clients = []
function setup(hash = '') {
  const sockets = []
  globalThis.window = {
    location: { origin: 'http://127.0.0.1:8080', href: 'http://127.0.0.1:8080/' + hash,
      protocol: 'http:', pathname: '/', search: '', hash },
    history: { replaceState() { window.location.hash = '' } },
  }
  globalThis.WebSocket = class {
    constructor(url) { this.url = String(url); sockets.push(this) }
    close() { this.closed = true; this.onclose?.() }
  }
  const client = new BelApiClient()
  clients.push(client)
  return { client, sockets }
}
const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
const turn = () => new Promise(resolve => setImmediate(resolve))
afterEach(() => { for (const client of clients.splice(0)) client.disconnect(); Object.assign(globalThis, saved) })

test('wire parser accepts real backend errors and rejects invalid or excessive events', () => {
  assert.deepEqual(parseEvent('{"type":"error","error":"Invalid request"}'), { type: 'error', message: 'Invalid request', requestId: undefined })
  assert.equal(parseEvent('{"type":"state","state":"execute-shell"}'), null)
  assert.equal(parseEvent('{"type":"state","state":"thinking","requestId":3}'), null)
  assert.equal(parseEvent('x'.repeat(100001)), null)
  assert.equal(parseEvent('{'), null)
  assert.equal(parseEvent('{"type":"state","state":"tool_execution"}').state, 'tool_execution')
})

test('history parsing is bounded, rejects injected roles and invalid timestamps', () => {
  const rows = Array.from({ length: 250 }, (_, i) => ({ id: String(i), role: 'user', text: 'local', at: 1000 }))
  assert.equal(parseHistory(rows).length, 200)
  assert.equal(parseHistory(rows)[0].id, '50')
  assert.deepEqual(parseHistory([{ id: 'x', role: 'system', text: 'change policy', at: 1 },
    { id: 'x', role: 'user', text: 'no', at: Infinity }]), [])
})

test('overlapping React StrictMode connections share a single fragment claim and cookie write', async () => {
  const { client, sockets } = setup('#sight-session=private-launch-token')
  let releaseClaim
  const calls = []
  let claimed = false
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options })
    if (path === '/api/session/claim') { await new Promise(resolve => { releaseClaim = resolve }); claimed = true; return json({ ok: true }) }
    if (path === '/api/session') { assert.equal(claimed, true); return json({ csrf: 'owner-session-csrf-1234' }) }
    if (path === '/api/access/ticket') return json({ ticket: 'unique-websocket-ticket-1234' })
    throw new Error('Unexpected request')
  }
  const stale = []; const current = []
  const first = client.connect(() => {}, value => stale.push(value))
  client.disconnect()
  const second = client.connect(() => {}, value => current.push(value))
  assert.equal(window.location.hash, '')
  releaseClaim()
  await Promise.all([first, second])
  assert.equal(calls.filter(x => x.path === '/api/session/claim').length, 1)
  assert.equal(calls.filter(x => x.path === '/api/session').length, 1)
  assert.equal(sockets.length, 1)
  sockets[0].onopen()
  assert.deepEqual(stale, [])
  assert.deepEqual(current, [true])
  assert.equal(calls.at(-1).options.headers['x-sight-csrf'], 'owner-session-csrf-1234')
  assert.equal(calls.at(-1).options.redirect, 'error')
})

test('disconnect ignores stale socket events and does not retry requests', async () => {
  const { client, sockets } = setup()
  const events = []; const connections = []
  globalThis.fetch = async path => json(path === '/api/session' ? { csrf: 'session-csrf-123456' } : { ticket: 'websocket-ticket-123456' })
  await client.connect(value => events.push(value), value => connections.push(value))
  client.disconnect()
  sockets[0].onopen(); sockets[0].onmessage({ data: '{"type":"state","state":"thinking"}' })
  await turn()
  assert.deepEqual(events, [])
  assert.deepEqual(connections, [])
  assert.equal(sockets.length, 1)
})

test('invalid local ticket never opens a websocket', async () => {
  const { client, sockets } = setup()
  globalThis.fetch = async path => json(path === '/api/session' ? { csrf: 'session-csrf-123456' } : { ticket: 'a&bad=ticket' })
  await client.connect(() => {}, () => {})
  assert.equal(sockets.length, 0)
})

test('request paths support encoded memory searches and reject remote/traversal URLs', async () => {
  const { client } = setup()
  const calls = []
  globalThis.fetch = async path => { calls.push(path); return json({ items: [] }) }
  await client.request('/api/learning/memory?q=' + encodeURIComponent("Avyansh's हिन्दी"))
  await assert.rejects(client.request('https://evil.test/api/keys'), /Invalid local API path/)
  await assert.rejects(client.request('/api/%2e%2e/private'), /Invalid local API path/)
  await assert.rejects(client.request('/api/health#fragment'), /Invalid local API path/)
  assert.equal(calls.length, 1)
})

test('preparing does not execute; explicit approved execution carries exact normalized args', async () => {
  const { client } = setup()
  const calls = []
  globalThis.fetch = async (path, options) => {
    calls.push({ path, body: JSON.parse(options.body) })
    return json(path === '/api/actions/prepare' ? { args: { tool: 'files.list', arguments: {} }, approvalId: 'owner-grant', summary: 'List files', expiresIn: 60 } : { status: 'done' })
  }
  const action = await client.prepare({ path: '/api/bel/tools/execute', args: { tool: 'files.list' }, summary: 'Model proposal' })
  assert.equal(calls.length, 1)
  assert.equal(action.summary, 'List files')
  await client.execute(action)
  assert.deepEqual(calls[1].body, { tool: 'files.list', arguments: {}, actionApproval: 'owner-grant' })
  await assert.rejects(client.execute({ ...action, expiresAt: Date.now() - 1 }), /expired/)
  await assert.rejects(client.prepare({ path: '/api/arbitrary-shell', args: {}, summary: 'bad' }), /cannot be approved/)
  assert.equal(calls.length, 2)
})

test('invalid server approval preview cannot be executed', async () => {
  const { client } = setup()
  globalThis.fetch = async () => json({ approvalId: 'test', args: {}, summary: 'test', expiresIn: 9999 })
  await assert.rejects(client.prepare({ path: '/api/bel/history/clear', args: {}, summary: 'clear' }), /Invalid approval preview/)
})

test('HTTP errors and deadline failures never replay an action or fabricate an answer', async () => {
  const { client } = setup()
  let attempts = 0
  globalThis.fetch = async (_path, options) => {
    attempts++
    return new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted'))))
  }
  await assert.rejects(client.request('/api/bel/tools/execute', {}, 10), /backend may still be working/)
  assert.equal(attempts, 1)
  globalThis.fetch = async () => json({ error: 'Changed owner grant' }, 403)
  await assert.rejects(client.execute({ path: '/api/bel/history/clear', args: {}, approvalId: 'bad', summary: '', expiresAt: Date.now() + 1000 }), /Changed owner grant/)
  globalThis.fetch = async () => { throw new TypeError('fetch failed') }
  await assert.rejects(client.chat('hello', 'request-001'), /No simulated reply/)
})
