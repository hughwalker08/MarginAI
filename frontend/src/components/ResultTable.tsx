import { useState } from 'react'
import { columnKind, fmtCell, humanize, isMonthly } from '../format'
import type { AskResult } from '../types'

const PREVIEW = 10

export function ResultTable({ result }: { result: AskResult }) {
  const [all, setAll] = useState(false)
  const rows = all ? result.rows : result.rows.slice(0, PREVIEW)
  const monthly = result.columns.map((_, i) => isMonthly(result.rows.map((r) => r[i])))
  const numeric = result.columns.map((_, i) => result.rows.some((r) => typeof r[i] === 'number'))
  const kinds = result.columns.map((c, i) => columnKind(c, result.rows.map((r) => r[i])))

  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {result.columns.map((c, i) => <th key={c} className={numeric[i] ? 'num' : ''}>{humanize(c)}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={ri}>
                {r.map((v, ci) => (
                  <td key={ci} className={numeric[ci] ? 'num' : ''}>{fmtCell(v, kinds[ci], monthly[ci])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {result.rows.length > PREVIEW && (
        <button className="more" onClick={() => setAll(!all)}>
          {all ? 'Show fewer rows' : `Show all ${result.rows.length} rows`}
        </button>
      )}
      {result.truncated && <div className="meta">Results were capped at {result.rows.length} rows.</div>}
    </>
  )
}
