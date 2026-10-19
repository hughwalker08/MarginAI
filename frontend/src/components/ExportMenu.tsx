import { useEffect, useRef, useState } from 'react'
import { downloadCsv, filename } from '../exporters'
import type { Turn } from '../types'
import type { ExportAction } from './Report'

export function ExportMenu({ turn, hasChart, onExport }: {
  turn: Turn
  hasChart: boolean
  onExport: (turn: Turn, action: ExportAction) => void
}) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const r = turn.result!

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc) }
  }, [open])

  const pick = (fn: () => void) => () => { setOpen(false); fn() }
  return (
    <div className="export" ref={box}>
      <button className="export-btn" onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open}>
        <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11m0 0-4-4m4 4 4-4M5 19h14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
        Export
      </button>
      {open && (
        <div className="menu-pop export-pop" role="menu">
          <button role="menuitem" onClick={pick(() => onExport(turn, 'pdf'))}>Report as PDF <small>one page, via print</small></button>
          {hasChart && <button role="menuitem" onClick={pick(() => onExport(turn, 'png'))}>Chart as PNG</button>}
          {hasChart && <button role="menuitem" onClick={pick(() => onExport(turn, 'jpeg'))}>Chart as JPG</button>}
          <button role="menuitem" onClick={pick(() => downloadCsv(r.columns, r.rows, filename(turn.question, 'csv')))}>Table as CSV <small>opens in Excel</small></button>
        </div>
      )}
    </div>
  )
}
