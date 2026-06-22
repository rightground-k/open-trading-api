"""
api_client.py – Low-level HTTP wrapper for the KIS Open API.

Responsibilities:
  • Build common / auth headers for every request
  • GET and POST convenience methods
  • Retry with exponential back-off (1 s → 2 s → 4 s)
  • Inter-request throttle (0.5 s) to respect mock-trading rate limits
  • Structured logging of requests and responses
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

import config
from logger import setup_logger

logger = setup_logger("api_client")

# Retry timing: wait 2^attempt seconds  →  1s, 2s, 4s
_BASE_BACKOFF_SEC: float = 1.0
_MAX_RETRIES: int = 3
_REQUEST_TIMEOUT_SEC: int = 10
_THROTTLE_SEC: float = 0.5  # Minimum gap between consecutive API calls


class TokenExpiredError(Exception):
    """토큰 만료나 인증 오류 발생 시 던져지는 예외"""
    pass

class KISAPIClient:
    """Thin HTTP client tailored to the Korea Investment & Securities API.

    The client does **not** manage tokens itself – that is the job of
    ``TokenManager`` (auth.py).  It only knows how to build headers,
    send requests, and retry on transient failures.
    """

    def __init__(self) -> None:
        self.base_url: str = config.BASE_URL
        self.appkey: str = config.KIS_APPKEY
        self.appsecret: str = config.KIS_APPSECRET
        self._last_call_ts: float = 0.0  # Epoch timestamp of last API call
        logger.debug("KISAPIClient initialised (base_url=%s)", self.base_url)

    # ------------------------------------------------------------------
    # Header builders
    # ------------------------------------------------------------------

    def _build_headers(
        self,
        tr_id: str,
        additional_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Common headers **without** authorisation (used for token requests).

        Args:
            tr_id: Transaction ID for the KIS endpoint.
            additional_headers: Extra headers to merge in.

        Returns:
            Header dict suitable for ``requests``.
        """
        headers: Dict[str, str] = {
            "Content-Type": "application/json; charset=utf-8",
            "appkey": self.appkey,
            "appsecret": self.appsecret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        if additional_headers:
            headers.update(additional_headers)
        return headers

    def _build_auth_headers(
        self,
        tr_id: str,
        token: str,
        additional_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Headers **with** Bearer token (used for all authenticated calls).

        Args:
            tr_id: Transaction ID for the KIS endpoint.
            token: OAuth access token.
            additional_headers: Extra headers to merge in.

        Returns:
            Header dict including ``authorization: Bearer <token>``.
        """
        headers = self._build_headers(tr_id, additional_headers)
        headers["authorization"] = f"Bearer {token}"
        return headers

    # ------------------------------------------------------------------
    # Public request methods
    # ------------------------------------------------------------------

    def get(
        self,
        endpoint: str,
        tr_id: str,
        params: Dict[str, Any],
        additional_headers: Optional[Dict[str, str]] = None,
    ) -> dict:
        """Authenticated GET request (caller must supply token via *additional_headers*).

        Args:
            endpoint: API path (e.g. ``/uapi/domestic-stock/…``).
            tr_id: KIS transaction ID.
            params: Query-string parameters.
            additional_headers: Must contain ``authorization`` with Bearer token.

        Returns:
            Parsed JSON response body as a dict.
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._build_headers(tr_id, additional_headers)
        logger.debug("GET %s | tr_id=%s | params=%s", url, tr_id, params)
        return self._request_with_retry("GET", url, headers, params)

    def post(
        self,
        endpoint: str,
        tr_id: str,
        body: Dict[str, Any],
        additional_headers: Optional[Dict[str, str]] = None,
    ) -> dict:
        """POST request (may or may not include auth, depending on caller).

        Args:
            endpoint: API path.
            tr_id: KIS transaction ID.
            body: JSON request body.
            additional_headers: Optional extra headers (e.g. hashkey, authorization).

        Returns:
            Parsed JSON response body as a dict.
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._build_headers(tr_id, additional_headers)
        logger.debug("POST %s | tr_id=%s | body=%s", url, tr_id, body)
        return self._request_with_retry("POST", url, headers, body)

    # ------------------------------------------------------------------
    # Internal: retry loop
    # ------------------------------------------------------------------

    def _request_with_retry(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        params_or_body: Dict[str, Any],
        max_retries: int = _MAX_RETRIES,
    ) -> dict:
        """Execute an HTTP request with exponential-backoff retry.

        On each attempt the method:
          1. Waits for the throttle window (0.5 s since last call).
          2. Sends the request with a 10 s timeout.
          3. Validates the HTTP status and KIS-level ``rt_cd``.
          4. On failure, sleeps 2^attempt seconds before retrying.

        Args:
            method: ``"GET"`` or ``"POST"``.
            url: Fully-qualified URL.
            headers: Request headers.
            params_or_body: Query params (GET) or JSON body (POST).
            max_retries: Number of retry attempts (default 3).

        Returns:
            Parsed JSON dict on success.

        Raises:
            requests.exceptions.RequestException: After all retries exhausted.
        """
        last_exception: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                # --- Throttle ---
                self._throttle()

                # --- Send ---
                if method == "GET":
                    resp = requests.get(
                        url,
                        headers=headers,
                        params=params_or_body,
                        timeout=_REQUEST_TIMEOUT_SEC,
                    )
                else:
                    resp = requests.post(
                        url,
                        headers=headers,
                        json=params_or_body,
                        timeout=_REQUEST_TIMEOUT_SEC,
                    )

                self._last_call_ts = time.time()

                # 401 토큰 만료 에러 처리
                if resp.status_code == 401:
                    raise TokenExpiredError("⚠️ [인증 오류] 접근 토큰이 만료되었거나 유효하지 않습니다. (HTTP 401)")

                # --- HTTP-level check ---
                resp.raise_for_status()
                data: dict = resp.json()

                # --- KIS application-level check ---
                rt_cd = data.get("rt_cd")
                if rt_cd and rt_cd != "0":
                    msg_cd = data.get("msg_cd", "UNKNOWN")
                    msg1 = data.get("msg1", "No message")
                    
                    # 사용자에게 보여지는 직관적인 에러 메시지
                    logger.error(
                        "❌ [API 응답 오류] 요청 처리 중 문제가 발생했습니다. (사유: %s, 응답코드: %s)",
                        msg1, msg_cd,
                    )
                    # 상세 분석을 위한 디버그 로그 유지
                    logger.debug(
                        "상세 API 오류: method=%s url=%s rt_cd=%s msg_cd=%s",
                        method, url, rt_cd, msg_cd,
                    )
                    
                    if "만료" in msg1 or "유효하지 않은 토큰" in msg1 or msg_cd.startswith("EGW"):
                        raise TokenExpiredError(f"⚠️ [인증 오류] 증권사 인증 토큰이 만료되었습니다. 사유: {msg1}")
                    # Still return the data so the caller can decide what to do
                    return data

                logger.debug(
                    "Response %s %s [%d] – rt_cd=%s",
                    method, url, resp.status_code, rt_cd,
                )
                return data

            except requests.exceptions.RequestException as exc:
                last_exception = exc
                backoff = _BASE_BACKOFF_SEC * (2 ** (attempt - 1))
                
                # 재시도 시 직관적인 안내 메시지
                logger.warning(
                    "⚠️ [통신 지연] 증권사 서버와 연결이 원활하지 않습니다. %.1f초 후 재시도합니다... (%d/%d)",
                    backoff, attempt, max_retries,
                )
                logger.debug("상세 네트워크 에러: %s", exc)
                time.sleep(backoff)

        # All retries exhausted
        # 실패 완료 시 명확한 조치 가이드
        logger.error("❌ [통신 실패] 여러 번 시도했으나 증권사 서버 응답이 없습니다. 인터넷 연결이나 서버 상태를 확인해 주세요.")
        logger.debug("상세 에러 내역: %s %s", url, last_exception)
        raise last_exception  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Internal: rate-limit throttle
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        """Ensure at least ``_THROTTLE_SEC`` between consecutive API calls."""
        elapsed = time.time() - self._last_call_ts
        if elapsed < _THROTTLE_SEC:
            gap = _THROTTLE_SEC - elapsed
            logger.debug("Throttling %.3fs before next API call", gap)
            time.sleep(gap)