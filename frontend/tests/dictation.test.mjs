import { test } from 'node:test'
import assert from 'node:assert/strict'
import { DictationSession, installedLanguages } from '../src/lib/dictation.ts'

test('dictation cancellation names the exact request and blocks reuse until acknowledged', async () => {
  let release
  const calls = []
  const session = new DictationSession(id => { calls.push(id); return new Promise(resolve => { release = resolve }) })
  const first = session.begin()
  assert.match(first.requestId, /^[0-9a-f-]{36}$/)
  assert.equal(session.accepts(first), true)
  assert.throws(() => session.begin(), /previous dictation/)
  const pending = session.cancel()
  assert.deepEqual(calls, [first.requestId])
  assert.equal(first.controller.signal.aborted, true)
  assert.equal(session.accepts(first), false)
  assert.equal(session.finish(first), false)
  assert.equal(session.cancel(), pending)
  assert.equal(session.stopping, true)
  assert.throws(() => session.begin(), /previous dictation/)
  release()
  await pending
  const second = session.begin()
  assert.notEqual(first.requestId, second.requestId)
  assert.equal(session.finish(first), false)
  assert.equal(session.accepts(second), true)
  assert.equal(session.finish(second), true)
  assert.equal(session.accepts(second), false)
  await session.cancel()
  assert.equal(calls.length, 1)
})

test('failed cancellation discards the old transcript and reports failure without replay', async () => {
  let calls = 0
  const session = new DictationSession(() => { calls++; throw new Error('local service unavailable') })
  const request = session.begin()
  await assert.rejects(session.cancel(), /local service unavailable/)
  assert.equal(session.accepts(request), false)
  assert.equal(session.stopping, false)
  assert.equal(calls, 1)
})

test('language options reflect installed supported locales without prototype or unknown values', () => {
  assert.deepEqual(installedLanguages(['en-IN', 'en-GB', 'en-US', 'hi-IN', 'en-IN', '__proto__', 'toString', 'fr-FR', 3]), ['en-IN', 'en-GB', 'en-US', 'hi-IN'])
  assert.deepEqual(installedLanguages(null), [])
  assert.deepEqual(installedLanguages(['en-US']), ['en-US'])
})
