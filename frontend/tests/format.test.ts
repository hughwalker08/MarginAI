import assert from 'node:assert/strict'
import { test } from 'node:test'
import { columnKind, fmtCell, fmtNumber } from '../src/format.ts'

const kind = (col: string, ...values: number[]) => columnKind(col, values)

test('counts are never money, even when the name contains refund/discount', () => {
  assert.equal(kind('units_refunded', 165), 'count')
  assert.equal(kind('Refund events', 155), 'count')
  assert.equal(kind('refund_events', 155), 'count')
  assert.equal(kind('refunded_orders_with_product', 19), 'count')
  assert.equal(kind('total_orders_with_product', 305), 'count')
  assert.equal(kind('order_count', 5), 'count')
  assert.equal(kind('number_of_refunds', 12), 'count')
  assert.equal(kind('customers', 2909), 'count')
})

test('money is recognised by explicit words', () => {
  for (const c of ['total_refund_amount', 'gross_revenue', 'avg_order_value', 'gross_profit', 'total_sales', 'unit_price'])
    assert.equal(kind(c, 12.5), 'money', c)
  assert.equal(kind('revenue', 100), 'money') // whole dollars still money
})

test('vague names are money only if a value has cents, and the whole column agrees', () => {
  assert.equal(kind('total', 120.5, 80), 'money')
  assert.equal(kind('total', 500, 1000), 'number')
  assert.equal(kind('refunds', 12, 15), 'number')
  assert.equal(kind('discount_total', 10.25), 'money')
})

test('percentages', () => {
  assert.equal(kind('refund_percentage', 6.23), 'percent')
  assert.equal(kind('refund_rate', 5.7), 'percent')
  assert.equal(kind('gross_margin', 58.3), 'percent')
  assert.equal(kind('margin_amount', 1200.5), 'money')
})

test('formatting', () => {
  assert.equal(fmtNumber(165, 'count'), '165')
  assert.equal(fmtNumber(2909, 'count'), '2,909')
  assert.equal(fmtNumber(13043.64, 'money'), '$13,043.64')
  assert.equal(fmtNumber(6.234, 'percent'), '6.23%')
  assert.equal(fmtCell(null, 'money'), '–')
  assert.match(fmtCell('2026-07-01T00:00:00', 'number', true), /^Jul.* 2026$/)
})

test('the screenshot case: the table from the refund question', () => {
  const cols = { units_refunded: [165], refund_events: [155], total_refund_amount: [13043.64] }
  assert.equal(fmtCell(165, columnKind('Units refunded', cols.units_refunded)), '165')
  assert.equal(fmtCell(155, columnKind('Refund events', cols.refund_events)), '155')
  assert.equal(fmtCell(13043.64, columnKind('Total refund amount', cols.total_refund_amount)), '$13,043.64')
})


test('identifiers are shown as they are, without separators', () => {
  assert.equal(kind('customer_id', 9894855770331), 'id')
  assert.equal(kind('order_number', 1001), 'id')
  assert.equal(fmtNumber(9894855770331, 'id'), '9894855770331')
  assert.equal(fmtNumber(1001, 'id'), '1001')
  assert.equal(kind('product_id', 5), 'id')
})
