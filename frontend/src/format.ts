import type { Cell } from './types'

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

export type Kind = 'money' | 'percent' | 'count' | 'number'

const words = (col: string) =>
  col.replace(/([a-z])([A-Z])/g, '$1_$2').toLowerCase().split(/[^a-z0-9]+/).filter(Boolean)

const PERCENT = new Set(['pct', 'percent', 'percentage', 'rate', 'share', 'ratio'])
const COUNT = new Set(['units', 'qty', 'quantity', 'count', 'number', 'num', 'n'])
const MONEY = new Set(['revenue', 'sales', 'profit', 'amount', 'price', 'cost', 'spend', 'spent', 'takings', 'value',
  'aov', 'income', 'fee', 'fees', 'shipping', 'tax', 'gmv', 'dollars'])
const THINGS = new Set(['orders', 'order', 'events', 'items', 'customers', 'products', 'transactions', 'visits',
  'locations', 'days', 'months', 'weeks', 'sizes', 'colours', 'colors'])
const MAYBE_MONEY = new Set(['total', 'totals', 'discount', 'discounts', 'refund', 'refunds', 'refunded'])

/**
 * What a numeric column holds, from its name first and its values second. Decided per column (never per cell)
 * so every row of a column is formatted the same way. A name like "units_refunded" must not read as dollars
 * just because it contains "refund": counts win over money words, and vague names (total, refunds...) only
 * count as money when some value has cents.
 */
export function columnKind(col: string, values: Cell[]): Kind {
  const w = words(col)
  const has = (set: Set<string>) => w.some((x) => set.has(x))
  if (has(PERCENT) || (w.includes('margin') && !has(MONEY))) return 'percent'
  if (has(COUNT)) return 'count'
  if (has(MONEY)) return 'money'
  if (has(THINGS)) return 'count'
  const nums = values.filter((v): v is number => typeof v === 'number')
  if (has(MAYBE_MONEY) && nums.some((n) => !Number.isInteger(n))) return 'money'
  return 'number'
}

export function fmtNumber(v: number, kind: Kind): string {
  if (kind === 'percent') return `${dec.format(v)}%`
  if (kind === 'money') return money.format(v)
  return Number.isInteger(v) ? int.format(v) : dec.format(v)
}

export function fmtCell(v: Cell, kind: Kind, monthly = false): string {
  if (v === null || v === undefined) return '–'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (typeof v === 'number') return fmtNumber(v, kind)
  if (isDate(v)) return fmtDate(v, monthly)
  return v
}

export function fmtAxis(v: number, kind: Kind): string {
  if (kind === 'percent') return `${dec.format(v)}%`
  if (kind === 'money') return Math.abs(v) >= 1000 ? `$${compact.format(v)}` : money0.format(v)
  return Math.abs(v) >= 10000 ? compact.format(v) : int.format(v)
}

/** All date cells in a column are the 1st of a month -> label as "Jul 2026". */
export const isMonthly = (values: Cell[]): boolean =>
  values.length > 0 && values.every((v) => isDate(v) && v.slice(8, 10) === '01')

/** "just now", "12 min ago", "3 h ago", "2 d ago" */
export function ago(iso: string | null, now = Date.now()): string {
  if (!iso) return 'not synced yet'
  const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000))
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h ago`
  return `${Math.round(mins / 1440)} d ago`
}
