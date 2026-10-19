import assert from 'node:assert/strict'
import { test } from 'node:test'
import { filename, slugify, toCsv } from '../src/exporters.ts'

test('slugs and filenames are safe and tidy', () => {
  assert.equal(slugify('What was our revenue in each month?'), 'what-was-our-revenue-in-each-month')
  assert.equal(slugify('  ??? '), 'report')
  assert.ok(slugify('x'.repeat(200)).length <= 50)
  assert.equal(filename('Top 5 products!', 'csv', new Date(2026, 9, 5)), 'marginai-top-5-products-2026-10-05.csv')
  assert.ok(!filename('../../etc/passwd', 'pdf').includes('/'))
})

test('csv: header, raw numbers, quoting and BOM', () => {
  const csv = toCsv(['product_title', 'units_sold', 'note'], [['Straw Hat', 3619, 'say "hi", ok'], ['Belt', 12.5, null]])
  assert.equal(csv.charCodeAt(0), 0xfeff)
  assert.equal(csv, '﻿Product title,Units sold,Note\r\nStraw Hat,3619,"say ""hi"", ok"\r\nBelt,12.5,\r\n')
})

test('csv: text that a spreadsheet would run as a formula is neutralised, numbers are not', () => {
  const csv = toCsv(['a', 'b'], [['=HYPERLINK("http://evil")', '-5 off'], [-5, 0]])
  const lines = csv.split('\r\n')
  assert.equal(lines[1], '"\'=HYPERLINK(""http://evil"")",\'-5 off')
  assert.equal(lines[2], '-5,0')
})

test('csv: line breaks inside a value stay in one quoted field', () => {
  assert.equal(toCsv(['t'], [['line one\nline two']]), '﻿T\r\n"line one\nline two"\r\n')
})
