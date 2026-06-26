"""
config.py – Central configuration for Samsung Auto Trader.

Loads credentials from .env via python-dotenv and exposes all tuneable
parameters as module-level constants.  Missing KIS credentials cause an
immediate ValueError so the process never starts in a broken state.
"""

import datetime
import os
from pathlib import Path

from dotenv import load_dotenv
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

# ---------------------------------------------------------------------------
# Timezone Configuration (Always use KST regardless of server/Codespace)
# ---------------------------------------------------------------------------
KST = ZoneInfo("Asia/Seoul")

def get_now() -> datetime.datetime:
    """Return the current KST (Korean Standard Time) datetime."""
    return datetime.datetime.now(KST)

# ---------------------------------------------------------------------------
# Bootstrap: load .env from the package directory or project root
# ---------------------------------------------------------------------------
_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_DIR.parent

if (_PACKAGE_DIR / ".env").exists():
    _ENV_PATH = _PACKAGE_DIR / ".env"
else:
    _ENV_PATH = _PROJECT_ROOT / ".env"

load_dotenv(_ENV_PATH)

# ---------------------------------------------------------------------------
# KIS Open API base URL (mock/virtual trading server)
# ---------------------------------------------------------------------------
BASE_URL: str = "https://openapivts.koreainvestment.com:29443"

# ---------------------------------------------------------------------------
# Target stock
# ---------------------------------------------------------------------------
STOCK_CODE: str = "005930"  # Samsung Electronics

# ---------------------------------------------------------------------------
# Trading strategy parameters (overridable via .env)
# ---------------------------------------------------------------------------
SPREAD_OFFSET: int = int(os.getenv("SPREAD_OFFSET", "2000"))
ORDER_QUANTITY: int = int(os.getenv("ORDER_QUANTITY", "1"))
POLLING_INTERVAL_SEC: int = int(os.getenv("POLLING_INTERVAL_SEC", "30"))
MAX_DAILY_ORDERS: int = int(os.getenv("MAX_DAILY_ORDERS", "50"))
MAX_POSITION_SIZE: int = int(os.getenv("MAX_POSITION_SIZE", "10"))

# ---------------------------------------------------------------------------
# Trading hours (KST)
# ---------------------------------------------------------------------------
TRADING_START: datetime.time = datetime.time(9, 10)
TRADING_END: datetime.time = datetime.time(15, 18)    # 타임 드리프트 방어를 위해 일찍 마감
TRADING_CLOSE: datetime.time = datetime.time(15, 20)  # 동시호가 진입 시 미체결 일괄 취소

# ---------------------------------------------------------------------------
# KIS API credentials (required – will raise at import time if absent)
# ---------------------------------------------------------------------------

def _require_env(key: str) -> str:
    """Return the value of an env-var or raise ValueError."""
    value = os.getenv(key)
    if not value:
        raise ValueError(
            f"Environment variable '{key}' is required but not set. "
            f"Add it to {_ENV_PATH}"
        )
    return value


KIS_APPKEY: str = _require_env("KIS_APPKEY")
KIS_APPSECRET: str = _require_env("KIS_APPSECRET")
KIS_ACCOUNT: str = _require_env("KIS_ACCOUNT")          # e.g. "50123456-01"
KIS_ACCOUNT_PROD: str = _require_env("KIS_ACCOUNT_PROD")  # product code portion

# ---------------------------------------------------------------------------
# Telegram Notification (Optional)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# Whether to consult the KIS holiday API. Set to 'false' in .env to skip API
# and use local holidays logic (recommended for mock environments).
USE_HOLIDAY_API: bool = os.getenv("USE_HOLIDAY_API", "true").lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Cache file paths (inside the package directory)
# ---------------------------------------------------------------------------
TOKEN_CACHE_FILE: Path = Path(__file__).resolve().parent / "token_cache.json"
ORDER_CACHE_FILE: Path = Path(__file__).resolve().parent / "order_cache.json"
# Optional local holiday list (JSON array of YYYYMMDD strings). If present,
# `market_data.check_is_holiday` will consult this file when the KIS API is
# unavailable (or returns an unsupported TR error in the mock environment).
HOLIDAYS_FILE: Path = Path(__file__).resolve().parent / "holidays.json"
# Whether to trust the KIS account API's evaluation fields (`evlu_amt`,
# `evlu_pfls_amt`). Set to 'false' to compute evaluation locally from
# `current_price * qty` (useful for comparing behavior with the mobile app).
USE_API_EVAL: bool = os.getenv("USE_API_EVAL", "true").lower() in ("1", "true", "yes")
