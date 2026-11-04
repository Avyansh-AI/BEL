import test from 'node:test'
import assert from 'node:assert/strict'
import { readyNativeApi } from '../src/lib/native.ts'

test('partial native bridge installation cannot crash the initial React effect', () => {
  for (const value of [null, undefined, {}, { status: () => {} }, { status: 1, set_mode: () => {}, close_app: () => {} }]) {
    assert.equal(readyNativeApi(value), false)
  }
  assert.equal(readyNativeApi({ status: () => {}, set_mode: () => {}, close_app: () => {} }), true)
})
