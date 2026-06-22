# -*- coding: utf-8 -*-
"""
orders.py — Order placement and cancellation.

Provides:
  - place_buy_order()          → submit a limit buy
  - place_sell_order()         → submit a limit sell
  - cancel_order()             → cancel a single order by odno
  - cancel_all_pending_orders()→ cancel every open order
"""

from __future__ import annotations

import time

from account import get_pending_orders
from auth import TokenManager
from config import KIS_ACCOUNT, KIS_ACCOUNT_PROD, STOCK_CODE
from logger import setup_logger

logger = setup_logger()

# Minimum delay between consecutive order API calls (seconds).
# The mock-trading server enforces strict rate limits.
_ORDER_COOLDOWN = 0.5


# ─────────────────────────────────────────────────────────────
# Internal helper
# ─────────────────────────────────────────────────────────────

def _place_order(
    token_manager: TokenManager,
    tr_id: str,
    price: int,
    quantity: int,
    side_label: str,
    ord_dvsn: str = "00",
) -> dict:
    """Shared implementation for buy / sell orders.

    Args:
        token_manager: Authenticated token manager.
        tr_id:         Transaction ID (VTTC0012U=buy, VTTC0011U=sell).
        price:         Limit price in KRW. Ignored (set to 0) for market orders.
        quantity:      Number of shares.
        side_label:    Human-readable label ("BUY" / "SELL") for logging.
        ord_dvsn:      "00"=지정가(limit), "01"=시장가(market).

    Returns:
        {"odno": str, "success": bool}
    """
    endpoint = "/uapi/domestic-stock/v1/trading/order-cash"

    # 시장가 주문 시 가격은 0으로 설정
    order_price = 0 if ord_dvsn == "01" else price

    body = {
        "CANO": KIS_ACCOUNT,
        "ACNT_PRDT_CD": KIS_ACCOUNT_PROD,
        "PDNO": STOCK_CODE,
        "ORD_DVSN": ord_dvsn,
        "ORD_QTY": str(quantity),
        "ORD_UNPR": str(order_price),
        "EXCG_ID_DVSN_CD": "KRX",
    }

    fail_result: dict = {"odno": "", "success": False}

    try:
        logger.debug(
            "[orders] Placing %s order — %s @ %s KRW × %d",
            side_label, STOCK_CODE, f"{price:,}", quantity,
        )

        headers = token_manager.get_auth_headers(tr_id)
        data = token_manager.api_client.post(
            endpoint, tr_id, body, additional_headers=headers,
        )

        # ── Response validation ──────────────────────────────
        if data.get("rt_cd") != "0":
            msg_cd = data.get("msg_cd", "UNKNOWN")
            msg1 = data.get("msg1", "No message")
            logger.error(
                "[orders] %s order REJECTED — msg_cd=%s, msg1=%s",
                side_label, msg_cd, msg1,
            )
            return fail_result

        output = data.get("output", {})
        odno = output.get("ODNO", "")

        logger.debug(
            "[orders] %s order ACCEPTED — odno=%s", side_label, odno,
        )
        return {"odno": odno, "success": True}

    except Exception as exc:
        logger.error(
            "[orders] %s order FAILED — %s", side_label, exc,
            exc_info=True,
        )
        return fail_result


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def place_buy_order(
    token_manager: TokenManager,
    price: int,
    quantity: int,
    ord_dvsn: str = "00",
) -> dict:
    """Place a BUY order for STOCK_CODE.

    tr_id: VTTC0012U (모의투자 매수)

    Args:
        token_manager: Authenticated token manager.
        price:         Limit buy price (KRW). Ignored for market orders.
        quantity:      Number of shares to buy.
        ord_dvsn:      "00"=지정가, "01"=시장가.

    Returns:
        {"odno": str, "success": bool}
    """
    return _place_order(token_manager, "VTTC0012U", price, quantity, "BUY", ord_dvsn)


def place_sell_order(
    token_manager: TokenManager,
    price: int,
    quantity: int,
    ord_dvsn: str = "00",
) -> dict:
    """Place a SELL order for STOCK_CODE.

    tr_id: VTTC0011U (모의투자 매도)

    Args:
        token_manager: Authenticated token manager.
        price:         Limit sell price (KRW). Ignored for market orders.
        quantity:      Number of shares to sell.
        ord_dvsn:      "00"=지정가, "01"=시장가.

    Returns:
        {"odno": str, "success": bool}
    """
    return _place_order(token_manager, "VTTC0011U", price, quantity, "SELL", ord_dvsn)


def cancel_order(
    token_manager: TokenManager,
    odno: str,
    order_qty: int,
) -> bool:
    """Cancel a specific pending order.

    tr_id: VTTC0013U (모의투자 주문 정정/취소)
    RVSE_CNCL_DVSN_CD = "02" → 취소 (cancel, not amend)
    QTY_ALL_ORD_YN    = "Y"  → 전량 취소

    Args:
        token_manager: Authenticated token manager.
        odno:          The order number to cancel.
        order_qty:     Original order quantity (logged, but QTY_ALL_ORD_YN='Y'
                       means the full remaining qty is cancelled).

    Returns:
        ``True`` if the cancellation was accepted, ``False`` otherwise.
    """
    endpoint = "/uapi/domestic-stock/v1/trading/order-rvsecncl"
    tr_id = "VTTC0013U"

    body = {
        "CANO": KIS_ACCOUNT,
        "ACNT_PRDT_CD": KIS_ACCOUNT_PROD,
        "KRX_FWDG_ORD_ORGNO": "",       # 한국거래소전송주문조직번호 (공백)
        "ORGN_ODNO": odno,               # 원주문번호
        "ORD_DVSN": "00",               # 지정가
        "RVSE_CNCL_DVSN_CD": "02",      # 02 = 취소
        "ORD_QTY": "0",                 # QTY_ALL_ORD_YN=Y이므로 0
        "ORD_UNPR": "0",                # 취소 시 가격 무의미
        "QTY_ALL_ORD_YN": "Y",          # 전량 취소
        "EXCG_ID_DVSN_CD": "KRX",
    }

    try:
        logger.debug("[orders] Cancelling order odno=%s (qty=%d)", odno, order_qty)

        headers = token_manager.get_auth_headers(tr_id)
        data = token_manager.api_client.post(
            endpoint, tr_id, body, additional_headers=headers,
        )

        if data.get("rt_cd") != "0":
            msg_cd = data.get("msg_cd", "UNKNOWN")
            msg1 = data.get("msg1", "No message")
            logger.error(
                "[orders] Cancel REJECTED odno=%s — msg_cd=%s, msg1=%s",
                odno, msg_cd, msg1,
            )
            return False

        logger.debug("[orders] Cancel ACCEPTED odno=%s", odno)
        return True

    except Exception as exc:
        logger.error(
            "[orders] Cancel FAILED odno=%s — %s", odno, exc,
            exc_info=True,
        )
        return False


def cancel_all_pending_orders(token_manager: TokenManager) -> int:
    """Cancel every currently pending (cancellable) order.

    Fetches the pending-order list via :func:`account.get_pending_orders`
    and cancels each one individually, respecting rate limits.

    Args:
        token_manager: Authenticated token manager.

    Returns:
        The number of orders successfully cancelled.
    """
    pending = get_pending_orders(token_manager)

    if not pending:
        logger.debug("[orders] No pending orders to cancel.")
        return 0

    logger.debug(
        "[orders] Attempting to cancel %d pending order(s)…", len(pending),
    )

    cancelled = 0
    for order in pending:
        success = cancel_order(
            token_manager,
            odno=order["odno"],
            order_qty=order["qty"],
        )
        if success:
            cancelled += 1

        # Respect rate limits between cancellation calls
        time.sleep(_ORDER_COOLDOWN)

    logger.debug(
        "[orders] Cancelled %d / %d pending order(s).",
        cancelled, len(pending),
    )
    return cancelled
