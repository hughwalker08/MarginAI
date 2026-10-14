# Willow & Finch — database schema (for the query-writing LLM)

Willow & Finch is a Sydney clothing boutique with an online store and two physical shops
(Surry Hills, Newtown). All money is **AUD, GST-inclusive** (GST is 1/11 of a GST-inclusive amount).
All timestamps are `timestamptz` stored in UTC. The business operates in **Australia/Sydney** time:
for anything about "today", "weekends", "evenings", "this month" etc., convert first, e.g.
`created_at AT TIME ZONE 'Australia/Sydney'`. Data covers 2025-10-01 to 2026-09-30.

## Rules that matter for correct answers
- **Revenue** means `orders.total` (or line totals) for orders where `financial_status <> 'voided'`.
  Voided orders never completed and must be excluded from revenue, order counts and units sold.
- **Refunds** are separate rows; net revenue = revenue minus `refunds.amount`. Count a refund on the
  date it was made (`refunds.created_at`), not the original order date, unless the question asks otherwise.
- **Line revenue** = `unit_price * quantity - line_discount` (line-level, after discounts, GST-inclusive).
- **Profit / margin** needs `variants.cost` (ex-GST cost per unit). Revenue is GST-inclusive, so divide by 1.1
  to compare with cost. Some variants have NULL `cost`; exclude them from margin and say so.
- `order_lines.unit_price` is the price paid at the time of sale. It can differ from `variants.price`
  (current price) because some prices rose on 2026-03-01. Use `unit_price` for historical revenue.
- **Customers are messy**: ~22% of orders have no customer (guest checkout, mostly in-store), some customers
  have no email, and some people appear twice as separate `customer_id`s (same name, different/missing email).
  Be explicit when counting "unique customers" and mention the caveat.
- `products.product_type` has inconsistent capitalisation (e.g. `Dress` and `dress`). Use `lower(product_type)`.

## Tables

### locations
Where a sale happened. `location_id`, `name`, `type` (`online` | `pos`).

### products
One row per style (42 products). `product_id`, `title`, `product_type`
(dress, top, knitwear, outerwear, pants, skirt, swimwear, accessories — case varies), `vendor`, `status`, `created_at`.

### variants
One row per size/colour of a product (the SKU). `variant_id`, `product_id`, `sku`, `size` (XS–XL or `One Size`),
`color`, `price` (current GST-inclusive price), `cost` (ex-GST unit cost, may be NULL).

### customers
`customer_id`, `first_name`, `last_name`, `email` (may be NULL), `city`/`state` (may be NULL; Australian states),
`accepts_marketing`, `created_at` (signup time; many signed up before the data period).

### discounts
Promotions. `discount_id`, `code`, `title`, `kind` (`percentage` | `fixed_amount` | `free_shipping`),
`value` (percent or dollars; NULL for free shipping), `is_automatic` (true = store-wide sale applied automatically,
false = code the customer types), `starts_on`, `ends_on` (NULL = ongoing).
Sales: BLACKFRIDAY, BOXINGDAY, MIDSEASON, EOFY, SPRINGREFRESH. Codes: WELCOME10, VIP15, SAVE20, FREESHIP, EXPIRED5 (never used).

### orders
One row per order. `order_id`, `order_number`, `customer_id` (NULL = guest), `location_id`,
`sales_channel` (`online` | `pos`; always consistent with the location type), `discount_id` (NULL = none; at most one per order),
`created_at`, `financial_status` (`paid` | `partially_refunded` | `refunded` | `voided`),
`subtotal` (before discounts and shipping), `discount_total`, `shipping_total` (online only; free over $150 after discounts),
`tax_total` (GST included in `total`), `total` = subtotal − discount_total + shipping_total,
`shipping_state` (delivery state for online orders; NSW for in-store).

### order_lines
One row per product variant in an order. `order_line_id`, `order_id`, `variant_id`, `quantity`,
`unit_price` (GST-inclusive, per unit), `line_discount` (total discount for the whole line, not per unit).

### refunds
One row per refund event. `refund_id`, `order_id`, `created_at`, `reason`
(Wrong size, Changed mind, Faulty or damaged, Not as described, Arrived late), `restocked`, `amount` (total refunded, GST-inclusive).

### refund_lines
The lines refunded. `refund_line_id`, `refund_id`, `order_line_id`, `quantity` (units refunded), `amount`.

## Relationships
orders → order_lines → variants → products; orders → customers, locations, discounts;
refunds → orders; refund_lines → refunds and order_lines.

## Patterns in the data (useful context, not rules)
Weekend and lunchtime peaks in-store, evening peaks online. Seasonality is Southern Hemisphere:
swimwear/dresses peak in summer (Dec–Feb), knitwear/outerwear in winter (May–Aug). Sale periods lift volume and discount rates.
