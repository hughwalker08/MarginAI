import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmtAxis, fmtCell, humanize, isMonthly } from '../format'
import type { AskResult } from '../types'

const MAX_SERIES = 5
const color = (i: number) => `var(--series-${(i % MAX_SERIES) + 1})`

interface Prepared {
  data: Record<string, string | number>[]
  keys: string[]
  xLabels: string[]
}

function prepare(r: AskResult, measure: string): Prepared | null {
  const chart = r.chart!
  const xi = r.columns.indexOf(chart.x)
  const yi = r.columns.indexOf(measure)
  if (xi < 0 || yi < 0) return null
  const monthly = isMonthly(r.rows.map((row) => row[xi]))
  const label = (row: AskResult['rows'][number]) => fmtCell(chart.x, row[xi], monthly)

  if (chart.series && chart.y.length === 1) {
    const si = r.columns.indexOf(chart.series)
    const keys = [...new Set(r.rows.map((row) => String(row[si])))]
    if (keys.length > MAX_SERIES) return null // more than 5 series is unreadable: show the table instead
    const byX = new Map<string, Record<string, string | number>>()
    for (const row of r.rows) {
      const x = label(row)
      const rec = byX.get(x) ?? { x }
      rec[String(row[si])] = Number(row[yi])
      byX.set(x, rec)
    }
    return { data: [...byX.values()], keys, xLabels: [...byX.keys()] }
  }
  const data = r.rows.map((row) => ({ x: label(row), [measure]: Number(row[yi]) }))
  return { data, keys: [measure], xLabels: data.map((d) => d.x as string) }
}

interface TipProps {
  active?: boolean
  label?: string
  payload?: { dataKey: string; value: number; color: string }[]
  measure: string
}

function Tip({ active, label, payload, measure }: TipProps) {
  if (!active || !payload?.length) return null
  return (
    <div className="tip">
      <div className="tip-title">{label}</div>
      {payload.map((p) => (
        <div className="tip-row" key={p.dataKey}>
          <i style={{ background: p.color }} />
          {payload.length > 1 || p.dataKey !== measure ? `${p.dataKey}: ` : `${humanize(measure)}: `}
          <b style={{ color: 'var(--text)' }}>{fmtCell(measure, p.value)}</b>
        </div>
      ))}
    </div>
  )
}

export function ResultChart({ result }: { result: AskResult }) {
  const chart = result.chart!
  // Different measures have different scales, so only one is plotted at a time (never a dual axis).
  // Prefer a money measure as the default (that is usually what the question is about).
  const [measure, setMeasure] = useState(
    chart.y.find((y) => /revenue|sales|profit|amount|total/i.test(y) && !/count|units|orders/i.test(y)) ?? chart.y[0],
  )
  const prepared = useMemo(() => prepare(result, measure), [result, measure])
  if (!prepared) return null
  const { data, keys, xLabels } = prepared

  const horizontal = chart.type === 'bar' && keys.length === 1 && (data.length > 6 || xLabels.some((l) => l.length > 11))
  const labelW = Math.min(180, Math.max(60, Math.max(...xLabels.map((l) => l.length)) * 6.6))
  const axis = { fontSize: 12, fill: 'var(--text-3)' }
  const tip = <Tooltip cursor={chart.type === 'line' ? { stroke: 'var(--border-strong)' } : { fill: 'var(--surface-2)' }}
    content={(p) => <Tip {...(p as unknown as TipProps)} measure={measure} />} />
  const yAxisFmt = (v: number) => fmtAxis(measure, v)

  return (
    <>
      <div className="viz-bar" style={{ paddingTop: 12 }}>
        <div className="chart-title" style={{ padding: 0 }}>
          {humanize(measure)} by {humanize(chart.x).toLowerCase()}
        </div>
        {chart.y.length > 1 && (
          <div className="seg" role="group" aria-label="Measure">
            {chart.y.map((y) => (
              <button key={y} aria-pressed={y === measure} onClick={() => setMeasure(y)}>{humanize(y)}</button>
            ))}
          </div>
        )}
      </div>
      {keys.length > 1 && (
        <div className="legend" style={{ paddingTop: 8 }}>
          {keys.map((k, i) => <span key={k}><i style={{ background: color(i) }} />{k}</span>)}
        </div>
      )}
      <div className="chart-wrap" style={{ height: horizontal ? Math.max(220, data.length * 30 + 30) : 280 }}>
        <ResponsiveContainer width="100%" height="100%">
          {chart.type === 'line' ? (
            <LineChart data={data} margin={{ top: 12, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" />
              <XAxis dataKey="x" tick={axis} tickLine={false} axisLine={{ stroke: 'var(--border-strong)' }} minTickGap={24} />
              <YAxis tick={axis} tickLine={false} axisLine={false} tickFormatter={yAxisFmt} width={56} />
              {tip}
              {keys.map((k, i) => (
                <Line key={k} dataKey={k} type="monotone" animationDuration={700} animationEasing="ease-out" stroke={color(i)} strokeWidth={2}
                  dot={data.length <= 24 ? { r: 3.5, fill: color(i), stroke: 'var(--surface)', strokeWidth: 2 } : false}
                  activeDot={{ r: 5, stroke: 'var(--surface)', strokeWidth: 2 }} />
              ))}
            </LineChart>
          ) : horizontal ? (
            <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 0, left: 4 }} barCategoryGap="22%">
              <CartesianGrid horizontal={false} stroke="var(--border)" />
              <XAxis type="number" tick={axis} tickLine={false} axisLine={false} tickFormatter={yAxisFmt} />
              <YAxis type="category" dataKey="x" tick={{ ...axis, fill: 'var(--text-2)' }} tickLine={false}
                axisLine={{ stroke: 'var(--border-strong)' }} width={labelW} interval={0} />
              {tip}
              <Bar dataKey={keys[0]} fill={color(0)} radius={[0, 4, 4, 0]} animationDuration={700} animationEasing="ease-out" />
            </BarChart>
          ) : (
            <BarChart data={data} margin={{ top: 12, right: 16, bottom: 0, left: 0 }} barCategoryGap="28%">
              <CartesianGrid vertical={false} stroke="var(--border)" />
              <XAxis dataKey="x" tick={axis} tickLine={false} axisLine={{ stroke: 'var(--border-strong)' }} interval={0} />
              <YAxis tick={axis} tickLine={false} axisLine={false} tickFormatter={yAxisFmt} width={56} />
              {tip}
              {keys.map((k, i) => <Bar key={k} dataKey={k} fill={color(i)} radius={[4, 4, 0, 0]} animationDuration={700} animationEasing="ease-out" />)}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </>
  )
}
