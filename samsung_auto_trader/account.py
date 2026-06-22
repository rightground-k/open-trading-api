# -*- coding: utf-8 -*-
"""
account.py — Account balance, holdings, and pending-order queries.

Provides three functions:
  - get_balance()        → cash + holdings snapshot
  - get_orderable_cash() → exact orderable cash considering margins
  - get_pending_orders() → currently cancellable open orders
"""

from __future__ import annotations

from auth import TokenManager
from config import KIS_ACCOUNT, KIS_ACCOUNT_PROD
from logger import setup_logger

logger = setup_logger()


# ─────────────────────────────────────────────────────────────
# Balance & Holdings
# ─────────────────────────────────────────────────────────────

def get_balance(token_manager: TokenManager) -> dict:
    """Return the account's cash balance and stock holdings.

    Endpoint
    --------
    GET /uapi/domestic-stock/v1/trading/inquire-balance
    tr_id : VTTC8434R  (mock-trading balance inquiry)

    Returns
    -------
    dict
        {
            "cash": int,               # 예수금 총액
            "nxdy_excc": int,          # 익일 정산액
            "prvs_rcdl_excc": int,     # D+2 정산액
            "thdt_buy": int,           # 금일매수액
            "thdt_sll": int,           # 금일매도액
            "thdt_tlex": int,          # 제비용금액
            "scts_evlu": int,          # 유가평가액
            "tot_evlu": int,           # 총평가금액
            "holdings": [         # 보유 종목 리스트
                {
                    "code":          str,   # 종목코드
                    "name":          str,   # 종목명
                    "qty":           int,   # 보유수량
                    "avg_price":     float, # 매입평균가
                    "current_price": int,   # 현재가
                    "eval_amt":      int,   # 평가금액
                    "profit":        int,   # 평가손익
                },
                ...
            ],
        }
        Returns ``{"cash": 0, "holdings": []}`` on failure.
    """
    endpoint = "/uapi/domestic-stock/v1/trading/inquire-balance"
    tr_id = "VTTC8434R"

    params = {
        "CANO": KIS_ACCOUNT,              # 종합계좌번호 (8자리)
        "ACNT_PRDT_CD": KIS_ACCOUNT_PROD, # 계좌상품코드 (2자리)
        "AFHR_FLPR_YN": "N",              # 시간외단일가여부
        "OFL_YN": "",                     # 오프라인여부
        "INQR_DVSN": "02",               # 조회구분 (종목별)
        "UNPR_DVSN": "02",               # 단가구분 (01=기본단가, 02=세금제비용포함)
        "FUND_STTL_ICLD_YN": "N",        # 펀드결제분포함여부
        "FNCG_AMT_AUTO_RDPT_YN": "N",    # 융자금액자동상환여부
        "PRCS_DVSN": "00",               # 처리구분 (전일매매포함)
        "CTX_AREA_FK100": "",             # 연속조회검색조건
        "CTX_AREA_NK100": "",             # 연속조회키
    }

    empty_result: dict = {
        "cash": 0, "nxdy_excc": 0, "prvs_rcdl_excc": 0,
        "thdt_buy": 0, "thdt_sll": 0, "thdt_tlex": 0,
        "scts_evlu": 0, "tot_evlu": 0, "holdings": []
    }

    try:
        headers = token_manager.get_auth_headers(tr_id)
        data = token_manager.api_client.get(
            endpoint, tr_id, params, additional_headers=headers,
        )

        # ── Response validation ──────────────────────────────
        if data.get("rt_cd") != "0":
            msg_cd = data.get("msg_cd", "UNKNOWN")
            msg1 = data.get("msg1", "No message")
            logger.error(
                "[account] Balance API error — msg_cd=%s, msg1=%s",
                msg_cd, msg1,
            )
            return empty_result

        # ── Cash (from output2 — 계좌 요약) ──────────────────
        output2_list = data.get("output2", [])
        cash, nxdy_excc, prvs_rcdl_excc = 0, 0, 0
        thdt_buy, thdt_sll, thdt_tlex = 0, 0, 0
        scts_evlu, tot_evlu = 0, 0
        
        if output2_list:
            item = output2_list[0]
            cash = int(item.get("dnca_tot_amt") or "0")
            nxdy_excc = int(item.get("nxdy_excc_amt") or "0")
            prvs_rcdl_excc = int(item.get("prvs_rcdl_excc_amt") or "0")
            thdt_buy = int(item.get("thdt_buy_amt") or "0")
            thdt_sll = int(item.get("thdt_sll_amt") or "0")
            thdt_tlex = int(item.get("thdt_tlex_amt") or "0")
            scts_evlu = int(item.get("scts_evlu_amt") or "0")
            tot_evlu = int(item.get("tot_evlu_amt") or "0")

        # ── Holdings (from output1 — 종목별 보유) ─────────────
        holdings: list[dict] = []
        for item in data.get("output1", []):
            qty = int(item.get("hldg_qty", "0"))
            if qty <= 0:
                continue  # skip zero-quantity rows

            holdings.append(
                {
                    "code": item.get("pdno", ""),
                    "name": item.get("prdt_name", ""),
                    "qty": qty,
                    "avg_price": float(item.get("pchs_avg_pric") or "0"),
                    "current_price": int(item.get("prpr") or "0"),
                    "eval_amt": int(item.get("evlu_amt") or "0"),
                    "profit": int(item.get("evlu_pfls_amt") or "0"),
                }
            )

        logger.debug(
            "[account] Balance — cash=%s KRW, holdings=%d position(s)",
            f"{cash:,}", len(holdings),
        )
        for h in holdings:
            logger.debug(
                "  ├─ %s (%s): %d shares @ avg %s, P&L %s",
                h["code"], h["name"], h["qty"],
                f"{h['avg_price']:,.0f}", f"{h['profit']:,}",
            )

        return {
            "cash": cash,
            "nxdy_excc": nxdy_excc,
            "prvs_rcdl_excc": prvs_rcdl_excc,
            "thdt_buy": thdt_buy,
            "thdt_sll": thdt_sll,
            "thdt_tlex": thdt_tlex,
            "scts_evlu": scts_evlu,
            "tot_evlu": tot_evlu,
            "holdings": holdings
        }

    except (KeyError, TypeError, ValueError) as exc:
        logger.error("[account] Failed to parse balance response: %s", exc)
        return empty_result
    except Exception as exc:
        logger.error(
            "[account] Unexpected error fetching balance: %s", exc,
            exc_info=True,
        )
        return empty_result


# ─────────────────────────────────────────────────────────────
# Orderable Cash
# ─────────────────────────────────────────────────────────────

def get_orderable_cash(token_manager: TokenManager) -> dict:
    """Return the exact orderable cash and max margin buy amount.

    Endpoint
    --------
    GET /uapi/domestic-stock/v1/trading/inquire-psbl-order
    tr_id : VTTC8908R  (매수가능조회)

    Returns
    -------
    dict
        {
            "cash": int,      # ord_psbl_cash (현금주문가능금액)
            "max_amt": int    # max_buy_amt (최대매수금액 - 미수/신용 포함)
        }
    """
    from config import STOCK_CODE  # import locally to avoid circular dep if any
    endpoint = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
    tr_id = "VTTC8908R"

    params = {
        "CANO": KIS_ACCOUNT,
        "ACNT_PRDT_CD": KIS_ACCOUNT_PROD,
        "PDNO": "",  # 종목코드 생략 시 계좌 전체 기준 최대주문가능액 산출
        "ORD_UNPR": "",
        "ORD_DVSN": "00",
        "CMA_EVLU_AMT_ICLD_YN": "N",
        "OVRS_ICLD_YN": "N",
    }

    empty_res = {"cash": 0, "max_amt": 0}

    try:
        headers = token_manager.get_auth_headers(tr_id)
        data = token_manager.api_client.get(
            endpoint, tr_id, params, additional_headers=headers,
        )

        if data.get("rt_cd") != "0":
            msg_cd = data.get("msg_cd", "UNKNOWN")
            msg1 = data.get("msg1", "No message")
            logger.error(
                "[account] Orderable cash API error — rt_cd=%s, msg_cd=%s, msg1=%s",
                data.get("rt_cd"), msg_cd, msg1,
            )
            return empty_res

        output = data.get("output") or data.get("output1") or []
        if isinstance(output, dict):
            output_item = output
        elif isinstance(output, list) and output:
            output_item = output[0]
        else:
            logger.debug(
                "[account] Orderable cash response missing output: %s",
                data,
            )
            return empty_res

        return {
            "cash": int(output_item.get("ord_psbl_cash") or "0"),
            "max_amt": int(output_item.get("max_buy_amt") or "0")
        }

    except Exception as exc:
        logger.error("[account] Failed to fetch orderable cash: %s", exc)
        return empty_res


# ─────────────────────────────────────────────────────────────
# Pending (cancellable) Orders
# ─────────────────────────────────────────────────────────────

def get_pending_orders(token_manager: TokenManager) -> list[dict]:
    """Return a list of currently cancellable pending orders.

    Endpoint
    --------
    GET /uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl
    tr_id : TTTC0084R  (정정/취소 가능 주문 조회)

    Returns
    -------
    list[dict]
        Each dict contains:
            odno      — 주문번호 (str)
            orgn_odno — 원주문번호 (str)
            code      — 종목코드 (str)
            name      — 종목명 (str)
            qty       — 주문수량 (int)
            price     — 주문단가 (int)
            side      — 'buy' or 'sell'
            psbl_qty  — 취소가능수량 (int)

        Only orders with ``psbl_qty > 0`` are included.
        Returns ``[]`` on failure.
    """
    endpoint = "/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl"
    tr_id = "TTTC0084R"

    params = {
        "CANO": KIS_ACCOUNT,
        "ACNT_PRDT_CD": KIS_ACCOUNT_PROD,
        "INQR_DVSN_1": "0",   # 조회구분1 (전체)
        "INQR_DVSN_2": "0",   # 조회구분2 (전체)
        "CTX_AREA_FK100": "",  # 연속조회검색조건
        "CTX_AREA_NK100": "",  # 연속조회키
    }

    try:
        headers = token_manager.get_auth_headers(tr_id)
        data = token_manager.api_client.get(
            endpoint, tr_id, params, additional_headers=headers,
        )

        # ── Response validation ──────────────────────────────
        if data.get("rt_cd") != "0":
            msg_cd = data.get("msg_cd", "UNKNOWN")
            msg1 = data.get("msg1", "No message")
            logger.error(
                "[account] Pending-orders API error — msg_cd=%s, msg1=%s",
                msg_cd, msg1,
            )
            return []

        # ── Parse order list ─────────────────────────────────
        orders: list[dict] = []
        for item in data.get("output", []):
            psbl_qty = int(item.get("psbl_qty") or "0")
            if psbl_qty <= 0:
                continue  # not actually cancellable

            # sll_buy_dvsn_cd: "01"=매도(sell), "02"=매수(buy)
            side_code = item.get("sll_buy_dvsn_cd", "")
            side = "buy" if side_code == "02" else "sell"

            orders.append(
                {
                    "odno": item.get("odno", ""),
                    "orgn_odno": item.get("orgn_odno", ""),
                    "code": item.get("pdno", ""),
                    "name": item.get("prdt_name", ""),
                    "qty": int(item.get("ord_qty") or "0"),
                    "price": int(item.get("ord_unpr") or "0"),
                    "side": side,
                    "psbl_qty": psbl_qty,
                }
            )

        logger.info(
            "[account] Pending orders: %d cancellable order(s)", len(orders),
        )
        for o in orders:
            logger.info(
                "  ├─ %s %s %s @ %s (qty=%d, psbl=%d)",
                o["odno"], o["side"].upper(), o["code"],
                f"{o['price']:,}", o["qty"], o["psbl_qty"],
            )

        return orders

    except (KeyError, TypeError, ValueError) as exc:
        logger.error(
            "[account] Failed to parse pending-orders response: %s", exc,
        )
        return []
    except Exception as exc:
        logger.error("❌ [오류] 미체결 주문 내역을 가져오는데 실패했습니다. (증권사 서버 지연)")
        logger.debug("상세 에러: %s", exc, exc_info=True)
        return []
