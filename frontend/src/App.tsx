import { useCallback, useEffect, useRef, useState } from 'react'
import { askStream, getExamples, getHealth, getStores } from './api'
import { AnswerCard } from './components/AnswerCard'
import { Composer } from './components/Composer'
import { LogoMark, Wordmark } from './components/Logo'
import { ago, fmtDate } from './format'
import type { Example, Health, HistoryItem, StoreInfo, Turn } from './types'

type Theme = 'light' | 'dark' | null

function readTheme(): Theme {
  try {
    const t = localStorage.getItem('theme')
    return t === 'light' || t === 'dark' ? t : null
  } catch {
    return null
  }
}

const HISTORY_SENT = 10 // the server decides how many it actually uses (MEMORY_TURNS)

/** Finished, successful turns only, in a compact form. */
function toHistory(turns: Turn[]): HistoryItem[] {
  return turns
    .filter((t) => t.status === 'done' && t.result && (t.result.sql || t.result.clarification))
    .slice(-HISTORY_SENT)
    .map((t) => ({
      question: t.question,
      answer: t.result!.answer,
      sql: t.result!.sql,
      assumptions: t.result!.assumptions,
      clarification: t.result!.clarification,
      columns: t.result!.columns,
      rows: t.result!.rows.slice(0, 5),
    }))
}

export default function App() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [offline, setOffline] = useState(false)
  const [examples, setExamples] = useState<Example[]>([])
  const [stores, setStores] = useState<StoreInfo[]>([])
  const [store, setStore] = useState('demo')
  const [theme, setTheme] = useState<Theme>(readTheme)
  const nextId = useRef(1)
  const scroller = useRef<HTMLDivElement>(null)

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setOffline(true))
    const loadStores = () => getStores().then(setStores).catch(() => {})
    loadStores()
    const t = setInterval(loadStores, 60_000) // keeps "updated 12 min ago" honest
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    getExamples(store).then(setExamples).catch(() => {})
  }, [store])

  const current = stores.find((s) => s.slug === store)
  const changeStore = (slug: string) => {
    setStore(slug)
    setTurns([]) // a conversation belongs to one store: never carry one store's answers into another
  }

  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme
    else delete document.documentElement.dataset.theme
  }, [theme])

  // Bring a newly asked question to the top of the view so its answer can be read from the start.
  useEffect(() => {
    const items = scroller.current?.querySelectorAll('.turn')
    items?.[items.length - 1]?.scrollIntoView({ block: 'start' })
  }, [turns.length])

  const toggleTheme = () => {
    const dark = theme ? theme === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches
    const next: Theme = dark ? 'light' : 'dark'
    setTheme(next)
    try {
      localStorage.setItem('theme', next!)
    } catch {
      /* storage blocked: theme still applies for this session */
    }
  }

  const turnsRef = useRef<Turn[]>([])
  turnsRef.current = turns

  const submit = useCallback((question: string) => {
    const id = nextId.current++
    const history = toHistory(turnsRef.current)
    const patch = (fn: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)))
    setTurns((t) => [...t, { id, question, status: 'loading', startedAt: Date.now() }])
    askStream(question, history, store, (e) => {
      setOffline(false)
      if (e.type === 'result') {
        const { type: _type, ...result } = e
        // Data and chart arrive first; the written answer streams in after. No answer text yet means "still writing".
        patch((t) => ({ ...t, status: result.answer ? 'done' : 'streaming', result }))
      } else if (e.type === 'delta') {
        patch((t) => (t.result ? { ...t, result: { ...t.result, answer: t.result.answer + e.text } } : t))
      } else {
        const { type: _type, ...final } = e
        patch((t) => ({ ...t, status: 'done', result: t.result ? { ...t.result, ...final } : t.result }))
      }
    }).catch((err: Error) => {
      patch((t) => (t.result && t.result.answer
        ? { ...t, status: 'done' }
        : { ...t, status: 'error', error: err.message }))
    })
  }, [store])

  const busy = turns.some((t) => t.status === 'loading' || t.status === 'streaming')

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <LogoMark />
          <Wordmark />
        </div>
        <div className="topbar-right">
          <div className="status" title={health ? `Model: ${health.model}` : undefined}>
            <span className={`dot${offline ? ' off' : ''}`} />
            {offline ? 'API offline: start the backend' : health ? (
              current && !current.demo
                ? <>{current.name}<span className="long"> · updated {ago(current.last_synced_at)}</span></>
                : <>Willow &amp; Finch<span className="long"> · demo data to {fmtDate(health.data_as_of)}</span></>
            ) : 'Connecting…'}
          </div>
          {stores.length > 1 && (
            <select className="store-select" value={store} onChange={(e) => changeStore(e.target.value)}
              disabled={busy} aria-label="Store">
              {stores.map((s) => <option key={s.slug} value={s.slug}>{s.demo ? `${s.name} (demo)` : s.name}</option>)}
            </select>
          )}
          {turns.length > 0 && (
            <button className="icon-btn" onClick={() => setTurns([])} aria-label="Clear conversation" title="Clear conversation">
              <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M10 11v6m4-6v6M6 7l1 12h10l1-12M9 7V4h6v3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </button>
          )}
          <button className="icon-btn" onClick={toggleTheme} aria-label="Toggle dark mode" title="Toggle dark mode">
            <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /></svg>
          </button>
        </div>
      </header>

      <main className="scroll" ref={scroller}>
        <div className="column">
          {turns.length === 0 ? (
            <section className="welcome">
              <span className="store-chip">
                {current && !current.demo ? `${current.name} · live data` : 'Demo store · Willow & Finch, Sydney'}
              </span>
              <h1>Ask your sales data anything</h1>
              <p>Plain-English questions in, answers out, with the table, a chart and the query behind every number.</p>
              <div className="examples">
                {examples.map((e) => (
                  <button key={e.question} className="example" onClick={() => submit(e.question)} disabled={busy}>
                    <small>{e.group}</small>
                    {e.question}
                  </button>
                ))}
              </div>
            </section>
          ) : (
            turns.map((t) => (
              <div className="turn" key={t.id}>
                <div className="user-row"><div className="user-bubble">{t.question}</div></div>
                <AnswerCard turn={t} onRetry={submit} />
              </div>
            ))
          )}
        </div>
      </main>

      <Composer onSubmit={submit} busy={busy} followUp={turns.length > 0} memory={health?.memory_turns}
        demo={!current || current.demo} />
    </div>
  )
}
