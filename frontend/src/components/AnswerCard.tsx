import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import type { Turn } from '../types'
import { LogoMark } from './Logo'
import { ExportMenu } from './ExportMenu'
import type { ExportAction } from './Report'
import { ResultChart } from './ResultChart'
import { ResultTable } from './ResultTable'
import { SqlBlock } from './SqlBlock'

const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * Reveals `full` at a steady pace instead of in the bursts the network delivers it in. Speed scales with
 * the backlog (so it never falls far behind) with a floor so short texts still feel typed, not dumped.
 */
function useSmoothText(full: string): { shown: string; typing: boolean } {
  const shownLen = useRef(0)
  const fullRef = useRef(full)
  fullRef.current = full
  const [, redraw] = useState(0)

  useEffect(() => {
    if (reducedMotion()) {
      shownLen.current = full.length
      redraw((x) => x + 1)
      return
    }
    let raf = 0
    const tick = () => {
      const backlog = fullRef.current.length - shownLen.current
      if (backlog <= 0) return
      shownLen.current += Math.min(backlog, Math.max(2, Math.ceil(backlog / 10)))
      redraw((x) => x + 1)
      raf = requestAnimationFrame(tick)
    }
    if (shownLen.current < full.length) raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [full])

  return { shown: full.slice(0, shownLen.current), typing: shownLen.current < full.length }
}

/** Animates the card's height as its content changes, so things grow smoothly instead of snapping. */
function AutoHeight({ children }: { children: ReactNode }) {
  const inner = useRef<HTMLDivElement>(null)
  const [height, setHeight] = useState<number | undefined>(undefined)
  useLayoutEffect(() => {
    const el = inner.current
    if (!el) return
    setHeight(el.getBoundingClientRect().height)
    const ro = new ResizeObserver(() => setHeight(el.getBoundingClientRect().height))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return (
    <div className="auto-h" style={{ height }}>
      <div ref={inner}>{children}</div>
    </div>
  )
}

function Thinking({ startedAt }: { startedAt: number }) {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setSecs(Math.floor((Date.now() - startedAt) / 1000)), 500)
    return () => clearInterval(t)
  }, [startedAt])
  return (
    <div className="thinking reveal" role="status" aria-live="polite">
      <span className="dots"><i /><i /><i /></span>
      <span>Looking through your sales data… {secs > 1 && <span style={{ color: 'var(--text-3)' }}>{secs}s</span>}</span>
    </div>
  )
}

const Head = ({ label }: { label: string }) => (
  <div className="card-head">
    <LogoMark size={20} />
    {label}
  </div>
)

function Answer({ text, streaming }: { text: string; streaming: boolean }) {
  const { shown, typing } = useSmoothText(text)
  if (!shown) return null
  return <p className="answer">{shown}{(streaming || typing) && <span className="caret" aria-hidden="true" />}</p>
}

export function AnswerCard({ turn, onRetry, onExport }: {
  turn: Turn
  onRetry: (q: string) => void
  onExport?: (turn: Turn, action: ExportAction) => void
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const r = turn.result
  const writing = turn.status === 'streaming'
  const failedRequest = turn.status === 'error' || (turn.status !== 'loading' && !r)
  const failed = !!r && !r.rows.length && !!r.error && !r.clarification
  const hasChart = !!r?.chart && r.rows.length > 1

  const cardClass = `card${r?.clarification ? ' clarify' : ''}${failed || failedRequest ? ' error' : ''}`
  return (
    <div className={cardClass}>
      <AutoHeight>
        <div className="card-body">
          <Head label={r?.clarification ? 'A quick check' : 'MarginAI'} />

          {turn.status === 'loading' && <Thinking startedAt={turn.startedAt} />}

          {failedRequest && (
            <div className="reveal">
              <p className="answer">That didn’t work.</p>
              <p className="error-text">{turn.error}</p>
              <button className="btn" onClick={() => onRetry(turn.question)}>Try again</button>
            </div>
          )}

          {r && <Answer text={r.clarification ?? r.answer} streaming={writing} />}
          {r?.assumptions && (
            <div className="note reveal">
              <span><b>{r.clarification ? 'Note: ' : 'How I read this: '}</b>{r.assumptions}</span>
            </div>
          )}
          {failed && <p className="error-text reveal">{r!.error}</p>}
        </div>

        {r && !r.clarification && r.rows.length > 0 && (
          <div className="viz reveal">
            <div className="viz-bar">
              {hasChart ? (
                <div className="seg" role="group" aria-label="View">
                  <button aria-pressed={view === 'chart'} onClick={() => setView('chart')}>Chart</button>
                  <button aria-pressed={view === 'table'} onClick={() => setView('table')}>Table</button>
                </div>
              ) : <span />}
              {onExport && !writing && <ExportMenu turn={turn} hasChart={hasChart} onExport={onExport} />}
            </div>
            {hasChart && view === 'chart' ? <ResultChart result={r} /> : <ResultTable result={r} />}
          </div>
        )}

        {r?.sql && !r.clarification && <div className="reveal"><SqlBlock sql={r.sql} /></div>}
        {r && !r.clarification && !writing && (
          <div className="meta reveal">
            <span>{r.model}</span>
            <span>
              {(r.latency_ms / 1000).toFixed(1)}s
              {r.timings?.to_result_ms != null && ` (data in ${(r.timings.to_result_ms / 1000).toFixed(1)}s)`}
            </span>
            <span>{(r.input_tokens + r.output_tokens).toLocaleString()} tokens</span>
            {r.attempts > 1 && <span>{r.attempts} attempts</span>}
            {r.rows.length > 0 && <span>{r.rows.length.toLocaleString()} rows</span>}
          </div>
        )}
      </AutoHeight>
    </div>
  )
}
