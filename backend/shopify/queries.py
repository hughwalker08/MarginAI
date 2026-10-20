"""GraphQL for the sync. Bulk operations run these on Shopify's side and hand back one JSONL file."""

def products(updated_since: str | None = None) -> str:
    flt = f'(query: "updated_at:>={updated_since}")' if updated_since else ""
    return f"""
{{
  products{flt} {{
    edges {{ node {{
      id title productType vendor status createdAt
      variants {{ edges {{ node {{
        id sku price
        selectedOptions {{ name value }}
        inventoryItem {{ unitCost {{ amount }} }}
      }} }} }}
    }} }}
  }}
}}
"""


LOCATIONS = "{ locations(first: 250) { edges { node { id name isActive } } } }"

SHOP = "{ shop { name currencyCode ianaTimezone taxesIncluded } }"


def orders(updated_since: str | None = None, addresses: bool = False, names: bool = False) -> str:
    """Orders with their lines, discounts and refunds. `updated_since` (ISO time) makes it incremental.
    Shipping addresses (province only) are opt-in: they count as protected customer data."""
    flt = f'(query: "updated_at:>={updated_since}")' if updated_since else ""
    addr = "shippingAddress { provinceCode }" if addresses else ""
    cust = "customer { id firstName lastName }" if names else "customer { id }"
    return f"""
{{
  orders{flt} {{
    edges {{ node {{
      id name createdAt cancelledAt test displayFinancialStatus sourceName
      retailLocation {{ id }}
      {cust}
      {addr}
      subtotalPriceSet {{ shopMoney {{ amount }} }}
      totalDiscountsSet {{ shopMoney {{ amount }} }}
      totalShippingPriceSet {{ shopMoney {{ amount }} }}
      totalTaxSet {{ shopMoney {{ amount }} }}
      totalPriceSet {{ shopMoney {{ amount }} }}
      discountApplications {{ edges {{ node {{
        __typename allocationMethod targetType
        ... on DiscountCodeApplication {{ code }}
        ... on AutomaticDiscountApplication {{ title }}
        ... on ScriptDiscountApplication {{ title }}
        ... on ManualDiscountApplication {{ title }}
        value {{ __typename ... on PricingPercentageValue {{ percentage }} ... on MoneyV2 {{ amount }} }}
      }} }} }}
      lineItems {{ edges {{ node {{
        id quantity title
        originalUnitPriceSet {{ shopMoney {{ amount }} }}
        totalDiscountSet {{ shopMoney {{ amount }} }}
        variant {{ id }}
      }} }} }}
      refunds {{
        id createdAt note
        totalRefundedSet {{ shopMoney {{ amount }} }}
      }}
    }} }}
  }}
}}
"""


# Bulk operations cannot nest a connection inside a list (refunds is a list, refundLineItems a connection), so the
# refund line items of orders that have refunds are fetched afterwards, in small batches.
REFUND_LINES = """
query($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Order {
      id
      refunds {
        id
        refundLineItems(first: 100) { nodes {
          id quantity restockType
          subtotalSet { shopMoney { amount } }
          lineItem { id }
        } }
      }
    }
  }
}
"""
