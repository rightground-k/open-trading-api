# -*- coding: utf-8 -*-
"""
market_data.py — Real-time market data queries.

Fetches the latest price for the configured stock (STOCK_CODE)
from the KIS Open API (mock trading environment).
"""

from __future__ import annotations

from auth import TokenManager
from config import STOCK_CODE, HOLIDAYS_FILE, USE_HOLIDAY_API
from logger import setup_logger

import datetime
import json
from pathlib import Path

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

    def _is_local_holiday(date_str: str) -> bool:
        """Local holiday fallback.

        Logic:
          - Weekends (Sat/Sun) are holidays
          - If `holidays` package is available, use Korea holidays
          - Otherwise, if a `HOLIDAYS_FILE` exists, load it (expects list of YYYYMMDD)
        """
        try:
            d = datetime.datetime.strptime(date_str, "%Y%m%d").date()
        except Exception:
            logger.debug("Invalid date string provided to local holiday checker: %s", date_str)
            return False

        # Weekends
        if d.weekday() >= 5:
            return True

        # Try python-holidays if available
        try:
            import holidays

            kr = holidays.KR()
            return d in kr
        except Exception:
            pass

        # Try local holidays.json file
        try:
            p = Path(HOLIDAYS_FILE)
            if p.exists():
                arr = json.loads(p.read_text(encoding="utf-8"))
                return date_str in set(arr)
        except Exception:
            pass

        return False

    try:
        # If configured to skip the KIS holiday API, use local fallback directly.
        if not USE_HOLIDAY_API:
            logger.info("USE_HOLIDAY_API=false — 휴장일 API 호출을 건너뛰고 로컬 대체 로직을 사용합니다.")
            return _is_local_holiday(date_str)

        headers = token_manager.get_auth_headers(tr_id)
        data = token_manager.api_client.get(
            endpoint, tr_id, params, additional_headers=headers,
        )

        # If KIS indicates the TR is not supported in mock environment,
        # fall back to local holiday calculation (weekend / local file / holidays lib).
        if data.get("rt_cd") != "0":
            msg_cd = data.get("msg_cd", "UNKNOWN")
            msg1 = data.get("msg1", "No message")
            logger.warning("⚠️ [휴장일 조회 실패] msg_cd=%s msg1=%s — 로컬 대체 로직으로 판단합니다.", msg_cd, msg1)
            # EGW02006 == "모의투자 TR 이 아닙니다." (mock server doesn't support this TR)
            return _is_local_holiday(date_str)

        output = data.get("output")
        if isinstance(output, dict):
            outputs = [output]
        elif isinstance(output, list):
            outputs = output
        else:
            logger.warning("⚠️ [휴장일 조회] 예상치 못한 휴장일 응답 형식입니다: %s — 로컬 대체 로직 적용", type(output).__name__)
            return _is_local_holiday(date_str)

        for item in outputs:
            if not isinstance(item, dict):
                continue
            if item.get("bass_dt") == date_str:
                is_business_day = item.get("bzdy_yn", "Y")
                return is_business_day == "N"

        # No matching date in output -> fall back
        return _is_local_holiday(date_str)

    except Exception as exc:
        logger.error("💥 [시스템 오류] 휴장일 정보를 확인하는 중 문제가 발생했습니다. — 로컬 대체 로직으로 진행합니다.")
        logger.debug("상세 휴장일 조회 에러 내역: %s", exc, exc_info=True)
        return _is_local_holiday(date_str)