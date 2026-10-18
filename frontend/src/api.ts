import type { Example, HistoryItem, Health, StoreInfo, StreamEvent } from './types'

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export const getHealth = () => fetch('/api/health').then((r) => parse<Health>(r))
export const getStores = () => fetch('/api/stores').then((r) => parse<StoreInfo[]>(r))
export const getExamples = (store: string) =>
  fetch(`/api/examples?store=${encodeURIComponent(store)}`).then((r) => parse<Example[]>(r))

/** Read the newline-delimited JSON stream from /api/ask/stream, calling onEvent for each event. */
export async function askStream(
  question: string,
  history: HistoryItem[],
  store: string,
  onEvent: (e: StreamEvent) => void,
): Promise<void> {
  const res = await fetch('/api/ask/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, history, store }),
  })
  if (!res.ok || !res.body) {
    await parse<never>(res) // throws with the server's message
    return
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let nl: number
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl).trim()
      buffer = buffer.slice(nl + 1)
      if (line) onEvent(JSON.parse(line) as StreamEvent)
    }
  }
}
