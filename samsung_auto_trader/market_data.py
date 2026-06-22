# -*- coding: utf-8 -*-
"""
market_data.py — Real-time market data queries.

Fetches the latest price for the configured stock (STOCK_CODE)
from the KIS Open API (mock trading environment).
"""

from __future__ import annotations

from auth import TokenManager
from config import STOCK_CODE
from logger import setup_logger

logger = setup_logger("market_data")


def get_current_price(token_manager: TokenManager) -> int:
    """Fetch the current (last traded) price of STOCK_CODE.

    Endpoint
    --------
    GET /uapi/domestic-stock/v1/quotations/inquire-price
    tr_id : FHKST01010100

    Returns
    -------
    int
        The current price in KRW.  Returns ``0`` if the API call fails
        so that the caller can decide whether to retry or skip the cycle.
    """
    endpoint = "/uapi/domestic-stock/v1/quotations/inquire-price"
    tr_id = "FHKST01010100"

    params = {
        "FID_COND_MRKT_DIV_CODE": "J",   # 주식 시장
        "FID_INPUT_ISCD": STOCK_CODE,     # 종목코드 (005930)
    }

    try:
        # Build auth headers and execute GET request
        headers = token_manager.get_auth_headers(tr_id)
        data = token_manager.api_client.get(
            endpoint, tr_id, params, additional_headers=headers,
        )

        # ── Response validation ──
        if data.get("rt_cd") != "0":
            msg1 = data.get("msg1", "알 수 없는 오류")
            logger.error("❌ [조회 실패] 현재가 정보를 불러오지 못했습니다. (사유: %s)", msg1)
            return 0

        output = data.get("output")
        if not output:
            logger.error("❌ [데이터 누락] 증권사 응답에 현재가 데이터가 없습니다.")
            return 0

        # "stck_prpr" (주식 현재가)
        current_price_str = output.get("stck_prpr") or "0"
        current_price = int(current_price_str)
        return current_price

    except (KeyError, TypeError, ValueError) as exc:
        logger.error("❌ [데이터 오류] 증권사에서 받은 현재가 정보 형식이 올바르지 않아 읽을 수 없습니다.")
        logger.debug("상세 파싱 에러: %s", exc)
        return 0
    except Exception as exc:
        logger.error("💥 [시스템 오류] 현재가를 불러오는 중 예상치 못한 문제가 발생했습니다.")
        logger.debug("상세 시스템 에러: %s", exc, exc_info=True)
        return 0

def check_is_holiday(token_manager: TokenManager, date_str: str) -> bool:
    """Check if the given date (YYYYMMDD) is a market holiday.
    
    Returns True if holiday, False if business day.
    Defaults to False if API fails to avoid blocking the bot.
    """
    endpoint = "/uapi/domestic-stock/v1/quotations/chk-holiday"
    tr_id = "CTCA0903R"

    params = {
        "BASS_DT": date_str,
        "CTX_AREA_NK": "",
        "CTX_AREA_FK": ""
    }

    try:
        headers = token_manager.get_auth_headers(tr_id)
        data = token_manager.api_client.get(
            endpoint, tr_id, params, additional_headers=headers,
        )

        if data.get("rt_cd") != "0":
            msg1 = data.get("msg1", "응답 오류")
            logger.warning("⚠️ [휴장일 조회 실패] 증권사에서 휴장일 정보를 불러오지 못했습니다. (사유: %s) — 기본적으로 영업일로 간주하고 진행합니다.", msg1)
            return False

        outputs = data.get("output", [])
        for item in outputs:
            if item.get("bass_dt") == date_str:
                # bzdy_yn == 'Y' (영업일), 'N' (휴장일)
                # opnd_yn == 'Y' (개장일), 'N' (휴장일)
                is_business_day = item.get("bzdy_yn", "Y")
                return is_business_day == "N"

        return False

    except Exception as exc:
        logger.error("💥 [시스템 오류] 휴장일 정보를 확인하는 중 문제가 발생했습니다. — 안전을 위해 영업일로 간주하고 진행합니다.")
        logger.debug("상세 휴장일 조회 에러 내역: %s", exc, exc_info=True)
        return False