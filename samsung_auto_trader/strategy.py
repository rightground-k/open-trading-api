# -*- coding: utf-8 -*-
"""
strategy.py — Pure trading strategy logic (no API calls).

Handles:
  - Korean stock market tick size rules
  - Order price calculation with spread offsets
  - Duplicate order detection
"""

from config import SPREAD_OFFSET, STOCK_CODE

# ──────────────────────────────────────────────────────────────
# Korean stock tick size table
# Each tuple: (max_price_inclusive, tick_size)
# Prices are in KRW. The table is searched sequentially;
# the first entry whose max_price >= current price is used.
# Reference: KRX tick size rules (as of 2023-01-02)
# ──────────────────────────────────────────────────────────────
TICK_SIZE_TABLE: list[tuple[int, int]] = [
    (2_000, 1),
    (5_000, 5),
    (20_000, 10),
    (50_000, 50),
    (200_000, 100),
    (500_000, 500),
    (float("inf"), 1_000),  # type: ignore[arg-type]
]


def get_tick_size(price: int) -> int:
    """Return the tick size (minimum price unit) for a given price level.

    Args:
        price: The reference price in KRW (must be > 0).

    Returns:
        The tick size applicable to *price*.

    Raises:
        ValueError: If *price* is not positive.
    """
    if price <= 0:
        raise ValueError(f"Price must be positive, got {price}")

    for max_price, tick in TICK_SIZE_TABLE:
        if price <= max_price:
            return tick

    # Should never reach here because the last entry uses inf,
    # but return the largest tick as a safety fallback.
    return TICK_SIZE_TABLE[-1][1]


def round_to_tick(price: int) -> int:
    """Round *price* DOWN to the nearest valid tick boundary.

    This ensures the returned price is always a valid order price
    accepted by the exchange.

    Args:
        price: Raw price in KRW.

    Returns:
        The tick-aligned price (always <= *price*).

    Raises:
        ValueError: If *price* is not positive.
    """
    if price <= 0:
        raise ValueError(f"Price must be positive, got {price}")

    tick = get_tick_size(price)
    return (price // tick) * tick


def calculate_order_prices(
    current_price: int,
    offset: int = SPREAD_OFFSET,
) -> tuple[int, int]:
    """Calculate buy and sell limit-order prices from the current market price.

    buy_price  = current_price − offset  (we want to buy cheap)
    sell_price = current_price + offset  (we want to sell dear)

    Both prices are rounded to the nearest valid tick.

    Args:
        current_price: The latest traded / quoted price.
        offset:        The spread offset in KRW (default from config).

    Returns:
        (buy_price, sell_price) — both tick-validated.

    Raises:
        ValueError: If *current_price* is not positive or offset
                    produces a non-positive buy price.
    """
    if current_price <= 0:
        raise ValueError(f"current_price must be positive, got {current_price}")

    raw_buy = current_price - offset
    raw_sell = current_price + offset

    if raw_buy <= 0:
        raise ValueError(
            f"Offset {offset} is too large for current_price {current_price}; "
            f"buy price would be {raw_buy}"
        )

    buy_price = round_to_tick(raw_buy)
    sell_price = round_to_tick(raw_sell)

    return buy_price, sell_price


def should_place_order(
    side: str,
    target_price: int,
    pending_orders: list[dict],
) -> bool:
    """Check whether a new order should be placed, avoiding duplicates.

    An order is considered a duplicate if there is already a pending order
    with the same *side*, *price*, and stock code (STOCK_CODE).

    Args:
        side:           "buy" or "sell".
        target_price:   The intended order price.
        pending_orders: List of currently pending orders, each with keys
                        ``'price'``, ``'side'``, ``'code'``.

    Returns:
        ``True`` if no matching order exists (safe to place);
        ``False`` if a duplicate is found (skip).
    """
    for order in pending_orders:
        if (
            order.get("side") == side
            and order.get("price") == target_price
            and order.get("code") == STOCK_CODE
        ):
            return False  # duplicate detected

    return True
