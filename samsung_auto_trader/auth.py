"""
auth.py – OAuth token management and hashkey generation for the KIS API.

TokenManager handles:
  • Requesting a new access token via POST /oauth2/tokenP
  • Caching the token to disk (token_cache.json) to avoid redundant requests
  • Same-day cache validation (tokens are re-issued daily in mock trading)
  • Generating a hashkey for POST request bodies
  • Building complete auth header dicts for downstream modules
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import config
from api_client import KISAPIClient
from logger import setup_logger

logger = setup_logger("auth")


class TokenManager:
    """Manages the OAuth2 token lifecycle for the KIS Open API.

    Tokens are cached in ``token_cache.json`` and reused within the same
    calendar day.  A new token is requested automatically when the cache
    is missing, stale, or corrupted.
    """

    _TOKEN_ENDPOINT: str = "/oauth2/tokenP"
    _HASHKEY_ENDPOINT: str = "/uapi/hashkey"

    def __init__(self, api_client: KISAPIClient) -> None:
        self.api_client = api_client
        self._cached_token: Optional[str] = None
        logger.debug("TokenManager initialised")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_token(self) -> str:
        """Return a valid access token, using cache when possible.

        The lookup order is:
          1. In-memory cache (``self._cached_token``)
          2. On-disk cache (``token_cache.json`` – same day only)
          3. Fresh request to KIS ``/oauth2/tokenP``

        Returns:
            Bearer access-token string.
        """
        # 1) In-memory
        if self._cached_token:
            logger.debug("Using in-memory cached token")
            return self._cached_token

        # 2) On-disk
        disk_token = self._load_token_cache()
        if disk_token:
            logger.debug("Loaded token from disk cache")
            self._cached_token = disk_token
            return disk_token

        # 3) Fresh request
        logger.debug("Requesting new token from KIS API")
        new_token = self._request_new_token()
        self._cached_token = new_token
        return new_token

    def get_hashkey(self, body: dict) -> str:
        """Generate a hashkey for a POST request body.

        The KIS API requires a ``hashkey`` header on order-related POST
        requests.  This method calls ``/uapi/hashkey`` and returns the
        hash string.

        Args:
            body: The JSON body that will be sent in the target POST.

        Returns:
            The HASH value to include in the request headers.
        """
        token = self.get_token()
        headers = {
            "authorization": f"Bearer {token}",
        }
        data = self.api_client.post(
            self._HASHKEY_ENDPOINT,
            tr_id="",  # No specific tr_id for hashkey
            body=body,
            additional_headers=headers,
        )
        hashkey: str = data.get("HASH", "")
        if not hashkey:
            logger.warning("Hashkey response did not contain HASH field: %s", data)
        else:
            logger.debug("Generated hashkey: %s…", hashkey[:12])
        return hashkey

    def get_auth_headers(self, tr_id: str) -> dict:
        """Build a complete set of authenticated request headers.

        Includes: Content-Type, authorization (Bearer), appkey, appsecret,
        tr_id, and custtype.

        Args:
            tr_id: KIS transaction ID for the target endpoint.

        Returns:
            Dict ready to pass as ``headers`` to ``requests``.
        """
        token = self.get_token()
        return {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": config.KIS_APPKEY,
            "appsecret": config.KIS_APPSECRET,
            "tr_id": tr_id,
            "custtype": "P",
        }

    # ------------------------------------------------------------------
    # Token request
    # ------------------------------------------------------------------

    def _request_new_token(self) -> str:
        """Call ``/oauth2/tokenP`` to obtain a fresh access token.

        Returns:
            The ``access_token`` string.

        Raises:
            RuntimeError: If the API response is missing the token field.
        """
        body = {
            "grant_type": "client_credentials",
            "appkey": config.KIS_APPKEY,
            "appsecret": config.KIS_APPSECRET,
        }
        data = self.api_client.post(
            self._TOKEN_ENDPOINT,
            tr_id="",  # Token endpoint has no tr_id
            body=body,
        )

        token: Optional[str] = data.get("access_token")
        if not token:
            logger.error("Token response missing 'access_token': %s", data)
            raise RuntimeError("Failed to obtain access token from KIS API")

        expires = data.get("access_token_token_expired", "")
        logger.debug("New token acquired (expires: %s)", expires)

        self._save_token_cache(token, expires)
        return token

    # ------------------------------------------------------------------
    # Disk cache helpers
    # ------------------------------------------------------------------

    def _save_token_cache(self, token: str, expires: str) -> None:
        """Persist the token and metadata to ``token_cache.json``.

        Args:
            token: The access token.
            expires: Expiry string returned by the API.
        """
        cache_data = {
            "access_token": token,
            "expires": expires,
            "cached_date": datetime.now().strftime("%Y-%m-%d"),
        }
        try:
            with open(config.TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            logger.debug("Token cache saved to %s", config.TOKEN_CACHE_FILE)
        except OSError as exc:
            logger.warning("Could not write token cache: %s", exc)

    def _load_token_cache(self) -> Optional[str]:
        """Load a cached token from disk if it was saved today.

        Returns:
            The cached token string, or ``None`` if the cache is absent,
            corrupt, or from a previous day.
        """
        try:
            with open(config.TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                cache_data: dict = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("No usable token cache: %s", exc)
            return None

        cached_date = cache_data.get("cached_date", "")
        today = datetime.now().strftime("%Y-%m-%d")

        if cached_date != today:
            logger.debug(
                "Token cache is from %s (today is %s) – discarding",
                cached_date, today,
            )
            return None

        token = cache_data.get("access_token")
        if not token:
            logger.warning("Token cache file exists but has no access_token")
            return None

        return token
