import assert from 'node:assert/strict'
import { beforeEach, test } from 'node:test'
import { MAX_CHATS, RETAIN_MS, groupChats, loadChats, pruneChats, saveChats, titleFrom, type Chat } from '../src/chats.ts'

class MemoryStorage {
  data = new Map<string, string>()
  limit = Infinity
  getItem(k: string) { return this.data.get(k) ?? null }
  setItem(k: string, v: string) {
    if (v.length > this.limit) throw new Error('QuotaExceededError')
    this.data.set(k, v)
  }
  removeItem(k: string) { this.data.delete(k) }
}
let storage: MemoryStorage
beforeEach(() => {
  storage = new MemoryStorage()
  ;(globalThis as unknown as { localStorage: MemoryStorage }).localStorage = storage
})

const NOW = new Date('2026-10-19T12:00:00').getTime()
const turn = (id: number, status = 'done', answer = 'ok', rows = 1) => ({
  id, question: `q${id}`, status, startedAt: 1,
  result: { question: `q${id}`, answer, sql: 'SELECT 1', columns: ['n'], rows: Array.from({ length: rows }, (_, i) => [i]) },
}) as never
const chat = (id: string, ageMs: number, turns = [turn(1)], store = 'demo'): Chat =>
  ({ id, store, title: id, createdAt: NOW - ageMs, updatedAt: NOW - ageMs, turns })

test('titles are trimmed to one tidy line', () => {
  assert.equal(titleFrom('  what   was our revenue? '), 'what was our revenue?')
  const t = titleFrom('x'.repeat(100))
  assert.ok(t.length <= 46 && t.endsWith('…'))
})

test('pruning drops chats older than a week, sorts newest first and caps the count', () => {
  const chats = [chat('old', RETAIN_MS + 1000), chat('b', 5000), chat('a', 1000)]
  assert.deepEqual(pruneChats(chats, NOW).map((c) => c.id), ['a', 'b'])
  const many = Array.from({ length: MAX_CHATS + 10 }, (_, i) => chat(`c${i}`, i * 1000 + 1))
  assert.equal(pruneChats(many, NOW).length, MAX_CHATS)
})

test('save then load round-trips, and expired chats do not come back', () => {
  saveChats([chat('keep', 1000), chat('gone', RETAIN_MS + 5000)], NOW)
  const loaded = loadChats(NOW)
  assert.deepEqual(loaded.map((c) => c.id), ['keep'])
  assert.equal(loaded[0].turns[0].result?.answer, 'ok')
})

test('a question that was mid-flight when the page closed is settled, not left spinning', () => {
  saveChats([chat('x', 1000, [turn(1, 'loading', ''), turn(2, 'streaming', 'half an answer'), turn(3, 'done')])], NOW)
  const [t1, t2, t3] = loadChats(NOW)[0].turns
  assert.equal(t1.status, 'error')
  assert.match(t1.error ?? '', /interrupted/)
  assert.equal(t2.status, 'done') // the partial answer is kept
  assert.equal(t3.status, 'done')
})

test('big results are slimmed to 100 rows', () => {
  saveChats([chat('big', 1000, [turn(1, 'done', 'ok', 500)])], NOW)
  const r = loadChats(NOW)[0].turns[0].result!
  assert.equal(r.rows.length, 100)
  assert.equal(r.truncated, true)
})

test('corrupt or blocked storage never throws', () => {
  storage.data.set('marginai.chats.v1', '{not json')
  assert.deepEqual(loadChats(NOW), [])
  storage.data.set('marginai.chats.v1', '{"a":1}')
  assert.deepEqual(loadChats(NOW), [])
  ;(globalThis as unknown as { localStorage: unknown }).localStorage = {
    getItem() { throw new Error('blocked') }, setItem() { throw new Error('blocked') }, removeItem() { throw new Error('blocked') },
  }
  assert.deepEqual(loadChats(NOW), [])
  saveChats([chat('a', 1)], NOW) // must not throw
})

test('when the quota is exceeded the oldest chats are dropped first', () => {
  const chats = Array.from({ length: 8 }, (_, i) => chat(`c${i}`, (i + 1) * 1000))
  const one = JSON.stringify(chats.slice(0, 2)).length
  storage.limit = one + 50
  saveChats(chats, NOW)
  const ids = loadChats(NOW).map((c) => c.id)
  assert.ok(ids.length > 0 && ids.length < 8)
  assert.equal(ids[0], 'c0') // the newest survives
})

test('grouping by day', () => {
  const day = 24 * 3600 * 1000
  const g = groupChats([chat('a', 1000), chat('b', day), chat('c', 3 * day)], NOW)
  assert.deepEqual(g.map((x) => x.label), ['Today', 'Yesterday', 'Earlier this week'])
})
