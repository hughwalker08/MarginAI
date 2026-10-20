# {store_name} — database schema (for the query-writing LLM)

{store_name} is a retail store that sells online and through physical locations (see the locations list in the
store context). All money is **{currency}, {tax_name}-inclusive**. All timestamps are `timestamptz` stored in UTC.
The business operates in **{timezone}** time: for anything about "today", "weekends", "evenings", "this month"
etc., convert first, e.g. `created_at AT TIME ZONE '{timezone}'`. The date range of the data is in the store context.

## Rules that matter for correct answers
- **Revenue** means `orders.total` (or line totals) for orders where `financial_status <> 'voided'`.
  Voided orders never completed and must be excluded from revenue, order counts and units sold.
- **Refunds** are separate rows; net revenue = revenue minus `refunds.amount`. Only count refunds on orders that are not voided (join refunds to orders and apply the same `financial_status <> 'voided'` filter): voided orders are already left out of revenue, so including their refunds would mix two definitions. Count a refund on the
  date it was made (`refunds.created_at`), not the original order date, unless the question asks otherwise.
- **Line revenue** = `unit_price * quantity - line_discount` (line-level, after discounts, {tax_name}-inclusive).
- **Profit / margin** needs `variants.cost` (ex-{tax_name} cost per unit). Revenue is {tax_name}-inclusive, so divide by {tax_divisor}
  to compare with cost. Some variants have NULL `cost`; exclude them from margin and say so.
- `order_lines.unit_price` is the price paid at the time of sale. It can differ from `variants.price`
  (current price) whenever a price has changed since the sale. Use `unit_price` for historical revenue.
- **Customers are messy**: many orders have no customer (`customer_id` NULL: guest checkout, often in-store),
  and the same person can appear more than once as separate `customer_id`s. Be explicit when counting
  "unique customers" and mention the caveat.
- `products.product_type` has inconsistent capitalisation (e.g. `Dress` and `dress`). Use `lower(product_type)`.

## Tables

### locations
Where a sale happened. `location_id`, `name`, `type` (`online` | `pos`).

### products
One row per style. `product_id`, `title`, `product_type`
(free text; capitalisation may vary, see the catalogue in the store context), `vendor`, `status`, `created_at`.
`status = 'custom'` marks something sold without a catalogue product (a custom sale typed in at the till, or a product since deleted): its title is what appeared on the receipt. Leave these out of product rankings unless the question is about custom sales, and say so when you do.

### variants
One row per size/colour of a product (the SKU). `variant_id`, `product_id`, `sku`, `size`,
`color`, `price` (current {tax_name}-inclusive price), `cost` (ex-{tax_name} unit cost, may be NULL).

### customers
`customer_id`, `first_name`, `last_name`, `email` (may be NULL), `city`/`state` (may be NULL),
`accepts_marketing`, `created_at` (signup time; many signed up before the data period).

### discounts
Promotions. `discount_id`, `code`, `title`, `kind` (`percentage` | `fixed_amount` | `free_shipping`),
`value` (percent or dollars; NULL for free shipping), `is_automatic` (true = store-wide sale applied automatically,
false = code the customer types), `starts_on`, `ends_on` (NULL = ongoing).
The actual sales and codes are listed in the store context.

### orders
One row per order. `order_id`, `order_number`, `customer_id` (NULL = guest), `location_id`,
`sales_channel` (`online` | `pos`; always consistent with the location type), `discount_id` (NULL = none; at most one per order),
`created_at`, `financial_status` (`paid` | `partially_refunded` | `refunded` | `voided`),
`subtotal` (before discounts and shipping), `discount_total`, `shipping_total` (shipping charged to the customer; usually 0 in-store),
`tax_total` ({tax_name} included in `total`), `total` = subtotal − discount_total + shipping_total,
`shipping_state` (delivery state or province for online orders; may be NULL).

### order_lines
One row per product variant in an order. `order_line_id`, `order_id`, `variant_id`, `quantity`,
`unit_price` ({tax_name}-inclusive, per unit), `line_discount` (total discount for the whole line, not per unit).

### refunds
One row per refund event. `refund_id`, `order_id`, `created_at`, `reason`
(short text, may be NULL), `restocked`, `amount` (total refunded, {tax_name}-inclusive).

### refund_lines
The lines refunded. `refund_line_id`, `refund_id`, `order_line_id`, `quantity` (units refunded), `amount`.

## Relationships
orders → order_lines → variants → products; orders → customers, locations, discounts;
refunds → orders; refund_lines → refunds and order_lines.
