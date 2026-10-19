import type { Cell } from './types'
import { humanize } from './format.ts'

export const slugify = (text: string, max = 50) =>
  text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, max).replace(/-+$/, '') || 'report'

export function filename(question: string, ext: string, now = new Date()): string {
  const d = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  return `marginai-${slugify(question)}-${d}.${ext}`
}

function csvField(v: Cell): string {
  if (v === null || v === undefined) return ''
  let s = typeof v === 'string' ? v : String(v)
  // A spreadsheet runs a cell starting with = + - @ as a formula: neutralise text that does (numbers are left alone).
  if (typeof v === 'string' && /^[=+\-@\t\r]/.test(s)) s = `'${s}`
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** CSV for Excel/Sheets: UTF-8 with a BOM, CRLF line endings, raw (unformatted) values. */
export function toCsv(columns: string[], rows: Cell[][]): string {
  const lines = [columns.map((c) => csvField(humanize(c))).join(',')]
  for (const r of rows) lines.push(r.map(csvField).join(','))
  return '﻿' + lines.join('\r\n') + '\r\n'
}

export function downloadBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export const downloadCsv = (columns: string[], rows: Cell[][], name: string) =>
  downloadBlob(new Blob([toCsv(columns, rows)], { type: 'text/csv;charset=utf-8' }), name)

// ---------------------------------------------------------------- chart image

const STYLE_PROPS = ['fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'stroke-linecap', 'stroke-linejoin', 'opacity',
  'fill-opacity', 'stroke-opacity', 'font-family', 'font-size', 'font-weight', 'text-anchor', 'dominant-baseline']

/** SVG drawn outside the page loses the page's CSS (including var(--series-1)), so bake the computed styles in. */
function inlineStyles(orig: Element, clone: Element): void {
  const cs = getComputedStyle(orig)
  const style = STYLE_PROPS.map((p) => `${p}:${cs.getPropertyValue(p)}`).join(';')
  clone.setAttribute('style', style)
  for (let i = 0; i < orig.children.length; i++) inlineStyles(orig.children[i], clone.children[i])
}

function wrapLines(ctx: CanvasRenderingContext2D, text: string, maxWidth: number, maxLines: number): string[] {
  const words = text.split(/\s+/)
  const lines: string[] = []
  let line = ''
  for (const w of words) {
    const next = line ? `${line} ${w}` : w
    if (ctx.measureText(next).width > maxWidth && line) {
      lines.push(line)
      line = w
    } else line = next
  }
  if (line) lines.push(line)
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines)
    kept[maxLines - 1] = kept[maxLines - 1].replace(/\s*\S*$/, '') + '…'
    return kept
  }
  return lines
}

export interface ChartImageOptions {
  svg: SVGSVGElement
  title: string // the question
  subtitle: string // e.g. "Gross revenue by month"
  legend: { color: string; label: string }[]
  footer: string
  format: 'png' | 'jpeg'
}

const INK = '#2a2420'
const INK2 = '#5e5448'
const INK3 = '#8a7e6c'

/** A tidy, self-contained picture: the question as a heading, the chart, a legend if needed, and a footer. */
export async function chartImage(o: ChartImageOptions): Promise<Blob> {
  await document.fonts?.ready
  const rect = o.svg.getBoundingClientRect()
  const w = Math.round(rect.width)
  const h = Math.round(rect.height)
  const clone = o.svg.cloneNode(true) as SVGSVGElement
  inlineStyles(o.svg, clone)
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(w))
  clone.setAttribute('height', String(h))
  clone.setAttribute('viewBox', `0 0 ${w} ${h}`)
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(clone))}`
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const im = new Image()
    im.onload = () => resolve(im)
    im.onerror = () => reject(new Error('Could not draw the chart'))
    im.src = url
  })

  const pad = 28
  const scale = 2
  const width = Math.max(w, 560) + pad * 2
  const probe = document.createElement('canvas').getContext('2d')!
  probe.font = '600 20px Inter, sans-serif'
  const titleLines = wrapLines(probe, o.title, width - pad * 2, 2)
  const headerH = pad + titleLines.length * 26 + 24
  const legendH = o.legend.length > 1 ? 30 : 0
  const height = headerH + legendH + h + 52

  const canvas = document.createElement('canvas')
  canvas.width = width * scale
  canvas.height = height * scale
  const ctx = canvas.getContext('2d')!
  ctx.scale(scale, scale)
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, width, height)

  ctx.textBaseline = 'alphabetic'
  ctx.fillStyle = INK
  ctx.font = '600 20px Inter, sans-serif'
  titleLines.forEach((l, i) => ctx.fillText(l, pad, pad + 18 + i * 26))
  ctx.fillStyle = INK2
  ctx.font = '500 13px Inter, sans-serif'
  ctx.fillText(o.subtitle, pad, pad + titleLines.length * 26 + 14)

  let y = headerH
  if (legendH) {
    ctx.font = '500 12px Inter, sans-serif'
    let x = pad
    for (const item of o.legend) {
      ctx.fillStyle = item.color
      ctx.fillRect(x, y + 4, 10, 10)
      ctx.fillStyle = INK2
      ctx.fillText(item.label, x + 16, y + 13)
      x += 16 + ctx.measureText(item.label).width + 18
    }
    y += legendH
  }
  ctx.drawImage(img, (width - w) / 2, y, w, h)

  ctx.fillStyle = INK3
  ctx.font = '500 11px Inter, sans-serif'
  ctx.fillText(o.footer, pad, height - 18)
  ctx.fillStyle = '#e3dccd'
  ctx.fillRect(pad, height - 38, width - pad * 2, 1)

  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('Could not create the image'))), `image/${o.format}`, 0.92))
}
