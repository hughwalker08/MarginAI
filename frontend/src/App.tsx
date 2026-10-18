import { useCallback, useEffect, useRef, useState } from 'react'
import { askStream, getExamples, getHealth } from './api'
import { AnswerCard } from './components/AnswerCard'
import { Composer } from './components/Composer'
import { LogoMark, Wordmark } from './components/Logo'
import { fmtDate } from './format'
import type { Example, Health, Turn } from './types'

type Theme = 'light' | 'dark' | null

function readTheme(): Theme {
  try {
    const t = localStorage.getItem('theme')
    return t === 'light' || t === 'dark' ? t : null
  } catch {
    return null
  }
}

export default function App() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [offline, setOffline] = useState(false)
  const [examples, setExamples] = useState<Example[]>([])
  const [theme, setTheme] = useState<Theme>(readTheme)
  const nextId = useRef(1)
  const scroller = useRef<HTMLDivElement>(null)

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setOffline(true))
    getExamples().then(setExamples).catch(() => {})
  }, [])

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

  const submit = useCallback((question: string) => {
    const id = nextId.current++
    const patch = (fn: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)))
    setTurns((t) => [...t, { id, question, status: 'loading', startedAt: Date.now() }])
    askStream(question, (e) => {
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
  }, [])

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
              <>Willow &amp; Finch<span className="long"> · demo data to {fmtDate(health.data_as_of)}</span></>
            ) : 'Connecting…'}
          </div>
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
              <span className="store-chip">Demo store · Willow &amp; Finch, Sydney</span>
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

      <Composer onSubmit={submit} busy={busy} />
    </div>
  )
}
