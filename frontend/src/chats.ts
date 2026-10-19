import type { Turn } from './types'

/** A conversation. Chats live only in this browser's localStorage and are dropped after a week. */
export interface Chat {
  id: string
  store: string
  title: string
  createdAt: number
  updatedAt: number
  turns: Turn[]
}

const KEY = 'marginai.chats.v1'
export const RETAIN_MS = 7 * 24 * 3600 * 1000
export const MAX_CHATS = 40
const MAX_ROWS = 100 // a saved result keeps at most this many rows (the whole thing must fit in ~5 MB)

export const newChatId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`

export const titleFrom = (question: string) => {
  const q = question.trim().replace(/\s+/g, ' ')
  return q.length > 46 ? `${q.slice(0, 45).trimEnd()}…` : q
}

function slim(turn: Turn): Turn {
  const r = turn.result
  if (!r || r.rows.length <= MAX_ROWS) return turn
  return { ...turn, result: { ...r, rows: r.rows.slice(0, MAX_ROWS), truncated: true } }
}

/** Newest first, nothing older than a week, at most MAX_CHATS. */
export function pruneChats(chats: Chat[], now = Date.now()): Chat[] {
  return chats
    .filter((c) => now - c.updatedAt < RETAIN_MS)
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_CHATS)
}

/** A turn that was mid-flight when the page closed can never finish: keep what arrived, or mark it failed. */
function settle(turn: Turn): Turn {
  if (turn.status !== 'loading' && turn.status !== 'streaming') return turn
  if (turn.result?.answer) return { ...turn, status: 'done' }
  return { ...turn, status: 'error', result: undefined, error: 'This question was interrupted. Ask it again.' }
}

export function loadChats(now = Date.now()): Chat[] {
  try {
    const raw = localStorage.getItem(KEY)
    const data: unknown = raw ? JSON.parse(raw) : []
    if (!Array.isArray(data)) return []
    const valid = data.filter((c): c is Chat => !!c && typeof c.id === 'string' && Array.isArray(c.turns)
      && typeof c.updatedAt === 'number' && typeof c.store === 'string')
    return pruneChats(valid.map((c) => ({ ...c, turns: c.turns.map(settle) })), now)
  } catch {
    return [] // storage blocked or corrupt: start fresh
  }
}

export function saveChats(chats: Chat[], now = Date.now()): void {
  let keep = pruneChats(chats, now).map((c) => ({ ...c, turns: c.turns.map(slim) }))
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      localStorage.setItem(KEY, JSON.stringify(keep))
      return
    } catch {
      if (keep.length <= 1) return // cannot store even one chat: carry on without saving
      keep = keep.slice(0, Math.ceil(keep.length / 2)) // quota exceeded: drop the oldest half and retry
    }
  }
}

export function clearSavedChats(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* nothing to clear */
  }
}

export type DayGroup = 'Today' | 'Yesterday' | 'Earlier this week'

export function dayGroup(ts: number, now = Date.now()): DayGroup {
  const startOfToday = new Date(now).setHours(0, 0, 0, 0)
  if (ts >= startOfToday) return 'Today'
  if (ts >= startOfToday - 24 * 3600 * 1000) return 'Yesterday'
  return 'Earlier this week'
}

export function groupChats(chats: Chat[], now = Date.now()): { label: DayGroup; chats: Chat[] }[] {
  const out: { label: DayGroup; chats: Chat[] }[] = []
  for (const c of chats) {
    const label = dayGroup(c.updatedAt, now)
    const last = out[out.length - 1]
    if (last && last.label === label) last.chats.push(c)
    else out.push({ label, chats: [c] })
  }
  return out
}
