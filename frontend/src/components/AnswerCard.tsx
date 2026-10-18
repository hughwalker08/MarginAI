import { useEffect, useState } from 'react'
import type { Turn } from '../types'
import { LogoMark } from './Logo'
import { ResultChart } from './ResultChart'
import { ResultTable } from './ResultTable'
import { SqlBlock } from './SqlBlock'

function Thinking({ startedAt }: { startedAt: number }) {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setSecs(Math.floor((Date.now() - startedAt) / 1000)), 500)
    return () => clearInterval(t)
  }, [startedAt])
  return (
    <div className="card"><div className="card-body thinking" role="status" aria-live="polite">
      <span className="dots"><i /><i /><i /></span>
      <span>Looking through your sales data… {secs > 0 && <span style={{ color: 'var(--text-3)' }}>{secs}s</span>}</span>
    </div></div>
  )
}

const Head = ({ label }: { label: string }) => (
  <div className="card-head">
    <LogoMark size={20} />
    {label}
  </div>
)

export function AnswerCard({ turn, onRetry }: { turn: Turn; onRetry: (q: string) => void }) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  if (turn.status === 'loading') return <Thinking startedAt={turn.startedAt} />

  if (turn.status === 'error' || !turn.result) {
    return (
      <div className="card error"><div className="card-body">
        <Head label="MarginAI" />
        <p className="answer">That didn’t work.</p>
        <p className="error-text">{turn.error}</p>
        <button className="btn" onClick={() => onRetry(turn.question)}>Try again</button>
      </div></div>
    )
  }

  const r = turn.result
  if (r.clarification) {
    return (
      <div className="card clarify"><div className="card-body">
        <Head label="A quick check" />
        <p className="answer">{r.clarification}</p>
        {r.assumptions && <div className="note"><span><b>Note: </b>{r.assumptions}</span></div>}
      </div></div>
    )
  }

  const failed = !r.rows.length && r.error
  const hasChart = !!r.chart && r.rows.length > 1
  return (
    <div className={`card${failed ? ' error' : ''}`}>
      <div className="card-body">
        <Head label="MarginAI" />
        <p className="answer">{r.answer}</p>
        {r.assumptions && (
          <div className="note"><span><b>How I read this: </b>{r.assumptions}</span></div>
        )}
        {failed && <p className="error-text">{r.error}</p>}
      </div>

      {r.rows.length > 0 && (
        <div className="viz">
          {hasChart && (
            <div className="viz-bar">
              <div className="seg" role="group" aria-label="View">
                <button aria-pressed={view === 'chart'} onClick={() => setView('chart')}>Chart</button>
                <button aria-pressed={view === 'table'} onClick={() => setView('table')}>Table</button>
              </div>
            </div>
          )}
          {hasChart && view === 'chart' ? <ResultChart result={r} /> : <ResultTable result={r} />}
        </div>
      )}

      {r.sql && <SqlBlock sql={r.sql} />}
      <div className="meta">
        <span>{r.model}</span>
        <span>{(r.latency_ms / 1000).toFixed(1)}s</span>
        <span>{(r.input_tokens + r.output_tokens).toLocaleString()} tokens</span>
        {r.attempts > 1 && <span>{r.attempts} attempts</span>}
        {r.rows.length > 0 && <span>{r.rows.length.toLocaleString()} rows</span>}
      </div>
    </div>
  )
}
