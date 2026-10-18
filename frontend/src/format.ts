import type { Cell } from './types'

const MONEY = /revenue|sales|profit|amount|discount|price|cost|aov|value|spend|takings|total_(?!units|orders|count)|refund/i
const PERCENT = /pct|percent|margin|rate|share|growth|change/i
const ISO = /^\d{4}-\d{2}-\d{2}(T|$)/

const money = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD' })
const money0 = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD', maximumFractionDigits: 0 })
const compact = new Intl.NumberFormat('en-AU', { notation: 'compact', maximumFractionDigits: 1 })
const int = new Intl.NumberFormat('en-AU', { maximumFractionDigits: 0 })
const dec = new Intl.NumberFormat('en-AU', { maximumFractionDigits: 2 })

export const isDate = (v: Cell): v is string => typeof v === 'string' && ISO.test(v)

export const humanize = (col: string) => {
  const s = col.replace(/_/g, ' ').trim()
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export function fmtDate(v: string, monthly = false): string {
  const [y, m, d] = v.slice(0, 10).split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1, d))
  return monthly
    ? date.toLocaleDateString('en-AU', { month: 'short', year: 'numeric', timeZone: 'UTC' })
    : date.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

export function fmtCell(col: string, v: Cell, monthly = false): string {
  if (v === null || v === undefined) return '–'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (typeof v === 'number') {
    if (PERCENT.test(col)) return `${dec.format(v)}%`
    if (MONEY.test(col)) return money.format(v)
    return Number.isInteger(v) ? int.format(v) : dec.format(v)
  }
  if (isDate(v)) return fmtDate(v, monthly)
  return v
}

export function fmtAxis(col: string, v: number): string {
  if (PERCENT.test(col)) return `${dec.format(v)}%`
  if (MONEY.test(col)) return Math.abs(v) >= 1000 ? `$${compact.format(v)}` : money0.format(v)
  return Math.abs(v) >= 10000 ? compact.format(v) : int.format(v)
}

/** All date cells in a column are the 1st of a month -> label as "Jul 2026". */
export const isMonthly = (values: Cell[]): boolean =>
  values.length > 0 && values.every((v) => isDate(v) && v.slice(8, 10) === '01')
