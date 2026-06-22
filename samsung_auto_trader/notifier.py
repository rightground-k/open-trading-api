"""
notifier.py — Telegram 알림 모듈

.env에 설정된 TELEGRAM_BOT_TOKEN 및 TELEGRAM_CHAT_ID를 사용하여
사용자에게 푸시 알림을 발송합니다.
"""

import requests

import config
from logger import setup_logger

logger = setup_logger()

def send_message(text: str) -> None:
    """텔레그램으로 메시지를 전송합니다."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        # 설정이 없으면 조용히 무시 (선택적 기능이므로)
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
    except Exception as e:
        # 알림 발송 실패가 시스템 전체 장애로 이어지지 않도록 예외 처리만 함
        logger.error("텔레그램 알림 발송 실패: %s", e)
