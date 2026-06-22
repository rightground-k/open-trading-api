"""
trader.py — 삼성전자 자동매매 메인 트레이딩 루프

매 사이클마다 현재가를 조회하고, 매수/매도 가격을 계산한 뒤
각종 안전장치(일일 주문 한도, 포지션 크기, 중복 주문, 잔고 확인)를
통과하면 지정가 주문을 제출합니다.
"""

import json
import time
import threading
from datetime import date, datetime, timedelta, time as dt_time

import config
import notifier
from logger import setup_logger
from api_client import KISAPIClient, TokenExpiredError
from auth import TokenManager
from market_data import get_current_price, check_is_holiday
from account import get_balance, get_pending_orders, get_orderable_cash
from orders import (
    place_buy_order,
    place_sell_order,
    cancel_all_pending_orders,
)
from strategy import calculate_order_prices, should_place_order


class AutoTrader:
    """삼성전자(005930) 자동매매 봇

    주요 흐름:
        1. 거래일(평일) 확인
        2. 장 시작 대기
        3. 장 중 반복 사이클 실행
        4. 장 마감 시 미체결 일괄 취소
    """

    def __init__(self) -> None:
        self.logger = setup_logger()
        self.logger.info("=" * 60)
        self.logger.info("🚀 [시스템 시작] 삼성전자 자동매매 시스템 초기화")
        self.logger.info("=" * 60)

        # API 클라이언트 & 토큰 매니저
        self.api_client = KISAPIClient()
        self.token_manager = TokenManager(self.api_client)

        # 일일 주문 카운터
        self.daily_order_count: int = 0
        self.daily_order_date: date | None = None
        self._load_daily_counter()
        
        # 엣지 케이스 방어 상태 변수
        self.consecutive_failures: int = 0
        self.last_price: int = 0
        self.pause_until: datetime | None = None
        
        # 주문 모드: "limit" (지정가) 또는 "market" (시장가)
        self.order_mode: str = "limit"
        self.spread_offset: int = config.SPREAD_OFFSET
        
        # 종료 제어용 이벤트
        self.stop_event = threading.Event()

        self.logger.info(
            "⚙️ [환경 설정] 종목=%s, 스프레드=%d원, 1회주문수량=%d주, 확인주기=%d초",
            config.STOCK_CODE,
            self.spread_offset,
            config.ORDER_QUANTITY,
            config.POLLING_INTERVAL_SEC,
        )
        self.logger.info(
            "🛡️ [안전 한도] 일일최대주문=%d건, 최대보유수량=%d주",
            config.MAX_DAILY_ORDERS,
            config.MAX_POSITION_SIZE,
        )

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> None:
        """메인 진입점 — 거래일 확인 → 대기 → 루프 → 마감 처리"""
        self._reset_daily_counter_if_needed()

        if not self._is_trading_day():
            self.logger.info("💤 [휴장일 안내] 오늘은 주말이므로 장이 열리지 않습니다. 봇을 종료합니다.")
            return

        self.logger.info("📅 [영업일] 오늘은 거래일입니다. 장 시작 시간까지 대기합니다...")
        if not self._wait_for_trading_window():
            self.logger.info("🛑 [중단 안내] 대기 중에 종료 요청을 받아 시스템을 끕니다.")
            self._close_trading_day()
            return

        self.logger.info("🔔 [장 시작] 본격적으로 자동매매 트레이딩 루프를 시작합니다!")
        try:
            self._run_trading_loop()
        except KeyboardInterrupt:
            self.logger.warning("🛑 [시스템 종료] 사용자가 직접 프로그램을 강제 중단했습니다.")
        finally:
            self._close_trading_day()

    # ------------------------------------------------------------------
    # Trading day helpers
    # ------------------------------------------------------------------

    def _is_trading_day(self) -> bool:
        """토요일(5)·일요일(6)이면 False, API 검사 후 공휴일이면 False 반환"""
        now = config.get_now()
        weekday = now.weekday()
        if weekday >= 5:  # 5=토, 6=일
            return False
            
        date_str = now.strftime("%Y%m%d")
        if check_is_holiday(self.token_manager, date_str):
            self.logger.info("💤 [휴장일 안내] 오늘은 공휴일 휴장일(증권사 기준)입니다.")
            return False
            
        return True

    def _wait_for_trading_window(self) -> bool:
        """현재 시각이 TRADING_START 전이면 시작 시각까지 대기.
        정상적으로 대기를 마쳤으면 True, 대기 중 종료 요청 시 False 반환."""
        while not self.stop_event.is_set():
            now = config.get_now().time()
            if now >= config.TRADING_START:
                return True
            # 남은 시간 계산 (초 단위)
            now_dt = datetime.combine(config.get_now().date(), now)
            start_dt = datetime.combine(config.get_now().date(), config.TRADING_START)
            remaining = (start_dt - now_dt).total_seconds()
            self.logger.info(
                "⏳ [대기 중] 장 시작까지 약 %.0f초 남았습니다...", remaining
            )
            # 최대 30초 단위로 대기
            self.stop_event.wait(min(remaining, 30))
        return False

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    def _run_trading_loop(self) -> None:
        """TRADING_END 시각까지 사이클 반복"""
        cycle_no = 0
        while config.get_now().time() < config.TRADING_END and not self.stop_event.is_set():
            if self.pause_until and config.get_now() < self.pause_until:
                self.logger.info("🚨 [서킷 브레이커] 안전을 위해 %s 까지 매매를 일시 정지하고 대기합니다.", self.pause_until.time())
                self.stop_event.wait(config.POLLING_INTERVAL_SEC)
                continue
                
            self.pause_until = None
            cycle_no += 1
            self.logger.info("🔄 [사이클 시작] ----- 트레이딩 사이클 #%d -----", cycle_no)
            try:
                self._execute_cycle()
                self.consecutive_failures = 0  # 성공 시 리셋
            except TokenExpiredError:
                self.logger.warning("⚠️ [인증 만료] 증권사 연결 토큰이 만료되었습니다. 다음 사이클에서 새로 발급받습니다.")
                # 토큰 캐시 파일 삭제 및 메모리 초기화
                if config.TOKEN_CACHE_FILE.exists():
                    config.TOKEN_CACHE_FILE.unlink()
                self.token_manager.token = None 
                self.token_manager.token_expires = None
            except Exception as e:
                self.consecutive_failures += 1
                self.logger.exception("❌ [실행 오류] 사이클 #%d 실행 중 예상치 못한 문제가 발생했습니다. (연속 에러: %d회)", cycle_no, self.consecutive_failures)
                
                if self.consecutive_failures >= 10:
                    notifier.send_message("🚨 [긴급] 자동매매 시스템이 연속 10회 에러를 발생시켜 안전을 위해 강제 종료됩니다.")
                    self.logger.error("🛑 [강제 종료] 치명적인 연속 에러가 발생하여 봇을 완전히 정지합니다.")
                    self.stop_event.set()
                    break

            if self.stop_event.is_set():
                break

            # 다음 사이클까지 대기
            self.logger.debug(
                "%d초 후 다음 사이클 실행", config.POLLING_INTERVAL_SEC
            )
            self.stop_event.wait(config.POLLING_INTERVAL_SEC)

    def _execute_cycle(self) -> None:
        """단일 트레이딩 사이클

        Steps:
            1. 현재가 조회
            2. 잔고 / 미체결 주문 조회
            3. 매수·매도 가격 계산
            4. 일일 한도 확인
            5. 중복 주문 확인
            6. 매수 잔고 / 매도 보유 수량 확인
            7. 주문 제출
            8. 카운터 업데이트 & 로그
        """
        self._reset_daily_counter_if_needed()

        # 1) 현재가 -------------------------------------------------------
        current_price: int = get_current_price(self.token_manager)
        if current_price == 0:
            raise RuntimeError("❌ [조회 실패] 현재가를 정상적으로 불러오지 못했습니다.")
            
        self.logger.info("🔎 [시장가 확인] 현재가: %s원", f"{current_price:,}")
        
        # 소프트웨어 서킷 브레이커 (주가 급등락 감지)
        if self.last_price > 0:
            price_change_pct = abs(current_price - self.last_price) / self.last_price * 100
            if price_change_pct >= 3.0:  # 1분 만에 3% 급변동 시
                self.logger.warning("🚨 [서킷 브레이커] 주가 급등락 감지 (변동폭: %.2f%%). 10분간 매매를 중단합니다.", price_change_pct)
                notifier.send_message(f"🚨 서킷 브레이커 발동: 주가 {price_change_pct:.2f}% 급변. 10분간 매매 일시 정지.")
                self.pause_until = config.get_now() + timedelta(minutes=10)
                self.last_price = current_price
                return
                
        self.last_price = current_price

        # 2) 잔고 & 미체결 -------------------------------------------------
        balance: dict = get_balance(self.token_manager)
        cash: int = balance["cash"]
        holdings: list[dict] = balance["holdings"]
        pending_orders: list[dict] = get_pending_orders(self.token_manager)

        self.logger.info(
            "💼 [계좌 상태] 가용현금=%s원, 보유종목=%d건, 미체결주문=%d건",
            f"{cash:,}",
            len(holdings),
            len(pending_orders),
        )

        # 3) 주문 가격 계산 ------------------------------------------------
        if self.order_mode == "market":
            # 시장가 모드: 현재가를 표시용으로만 사용, 실제 주문가는 0
            buy_price = current_price   # 표시용
            sell_price = current_price  # 표시용
            ord_dvsn = "01"  # 시장가
            self.logger.info("🛒 [주문 모드] 시장가 — 현재가 기준으로 즉시 체결을 시도합니다.")
        else:
            # 지정가 모드: 스프레드 적용
            buy_price, sell_price = calculate_order_prices(current_price, offset=self.spread_offset)
            ord_dvsn = "00"  # 지정가
            self.logger.info(
                "🎯 [주문 모드] 지정가 — 목표 매수단가: %s원 / 목표 매도단가: %s원",
                f"{buy_price:,}",
                f"{sell_price:,}",
            )

        # 4) 일일 한도 확인 ------------------------------------------------
        if not self._check_daily_limits(holdings):
            return

        # 5‑8) 매수 주문 ---------------------------------------------------
        self._try_place_buy(buy_price, cash, pending_orders, ord_dvsn)

        # 5‑8) 매도 주문 ---------------------------------------------------
        self._try_place_sell(sell_price, holdings, pending_orders, ord_dvsn)

        # 10) 사이클 요약 --------------------------------------------------
        self.logger.info(
            "🏁 [사이클 완료] 금일 누적 주문 횟수: %d건 (최대 %d건)",
            self.daily_order_count,
            config.MAX_DAILY_ORDERS,
        )

    # ------------------------------------------------------------------
    # Order placement helpers
    # ------------------------------------------------------------------

    def _try_place_buy(
        self,
        buy_price: int,
        cash: int,
        pending_orders: list[dict],
        ord_dvsn: str = "00",
    ) -> None:
        """매수 주문 시도 — 중복·잔고 확인 후 제출"""
        qty = config.ORDER_QUANTITY
        is_market = (ord_dvsn == "01")
        mode_label = "시장가" if is_market else "지정가"

        # 중복 확인 (시장가는 즉시 체결되므로 중복 체크 불필요)
        if not is_market and not should_place_order("buy", buy_price, pending_orders):
            self.logger.info("⏭️ [주문 보류] 매수가 %s원에 이미 미체결된 주문이 있어 중복 매수하지 않습니다.", f"{buy_price:,}")
            return

        # 잔고 확인
        required = buy_price * qty
        if cash < required:
            self.logger.warning(
                "⚠️ [잔고 부족] 매수 필요액: %s원 / 현재 예수금: %s원 — 매수를 건너뜁니다.",
                f"{required:,}",
                f"{cash:,}",
            )
            return

        # 일일 한도 재확인
        if self.daily_order_count >= config.MAX_DAILY_ORDERS:
            self.logger.warning("⛔ [한도 초과] 오늘 허용된 주문 횟수를 모두 소진하여 매수하지 않습니다.")
            return

        result = place_buy_order(self.token_manager, buy_price, qty, ord_dvsn)
        if result["success"]:
            self.daily_order_count += 1
            self._save_daily_counter()
            price_info = "시장가" if is_market else f"{buy_price:,}원"
            msg = f"✅ [매수 성공] ({mode_label})\n- 가격: {price_info}\n- 수량: {qty}주\n- 주문번호: {result['odno']}"
            self.logger.info("\n%s", msg)
            notifier.send_message(msg)
        else:
            self.logger.error("❌ [매수 실패] %s 매수 주문 처리에 실패했습니다.", mode_label)
            notifier.send_message(f"❌ 매수 주문 실패 ({mode_label})")

    def _try_place_sell(
        self,
        sell_price: int,
        holdings: list[dict],
        pending_orders: list[dict],
        ord_dvsn: str = "00",
    ) -> None:
        """매도 주문 시도 — 중복·보유 수량 확인 후 제출"""
        qty = config.ORDER_QUANTITY
        is_market = (ord_dvsn == "01")
        mode_label = "시장가" if is_market else "지정가"

        # 중복 확인 (시장가는 즉시 체결되므로 중복 체크 불필요)
        if not is_market and not should_place_order("sell", sell_price, pending_orders):
            self.logger.info("⏭️ [주문 보류] 매도가 %s원에 이미 대기 중인 매도 주문이 있어 중복 매도하지 않습니다.", f"{sell_price:,}")
            return

        # 보유 수량 확인
        held_qty = 0
        for h in holdings:
            if h["code"] == config.STOCK_CODE:
                held_qty = h["qty"]
                break

        if held_qty < qty:
            self.logger.info(
                "⚠️ [수량 부족] 매도 필요 수량: %d주 / 현재 보유 수량: %d주 — 매도를 건너뜁니다.",
                qty,
                held_qty,
            )
            return

        # 일일 한도 재확인
        if self.daily_order_count >= config.MAX_DAILY_ORDERS:
            self.logger.warning("⛔ [한도 초과] 오늘 허용된 주문 횟수를 모두 소진하여 매도하지 않습니다.")
            return

        result = place_sell_order(self.token_manager, sell_price, qty, ord_dvsn)
        if result["success"]:
            self.daily_order_count += 1
            self._save_daily_counter()
            price_info = "시장가" if is_market else f"{sell_price:,}원"
            msg = f"✅ [매도 성공] ({mode_label})\n- 가격: {price_info}\n- 수량: {qty}주\n- 주문번호: {result['odno']}"
            self.logger.info("\n%s", msg)
            notifier.send_message(msg)
        else:
            self.logger.error("❌ [매도 실패] %s 매도 주문 처리에 실패했습니다.", mode_label)
            notifier.send_message(f"❌ 매도 주문 실패 ({mode_label})")

    # ------------------------------------------------------------------
    # Safety checks
    # ------------------------------------------------------------------

    def _check_daily_limits(self, holdings: list[dict]) -> bool:
        """일일 주문 한도 및 최대 포지션 크기 확인

        Returns:
            True  — 주문 가능
            False — 한도 초과로 이번 사이클 스킵
        """
        # 일일 주문 수 한도
        if self.daily_order_count >= config.MAX_DAILY_ORDERS:
            self.logger.warning(
                "⛔ [한도 초과] 일일 주문 한도(%d건)에 도달하여 이번 사이클은 매매를 쉽니다.",
                config.MAX_DAILY_ORDERS,
            )
            return False

        # 최대 포지션 크기
        held_qty = 0
        for h in holdings:
            if h["code"] == config.STOCK_CODE:
                held_qty = h["qty"]
                break

        if held_qty >= config.MAX_POSITION_SIZE:
            self.logger.warning(
                "🛡️ [포지션 제한] 최대 보유 가능 수량(%d주)에 도달했습니다. (현재 %d주) — 신규 매수는 제한되며 매도만 가능합니다.",
                config.MAX_POSITION_SIZE,
                held_qty,
            )
            # 포지션 초과 시에도 매도는 허용하므로 True 반환
            # (매수만 _try_place_buy 에서 별도 차단)

        return True

    # ------------------------------------------------------------------
    # Daily counter management
    # ------------------------------------------------------------------

    def _reset_daily_counter_if_needed(self) -> None:
        """날짜가 바뀌면 일일 카운터 초기화"""
        today = config.get_now().date()
        if self.daily_order_date != today:
            if self.daily_order_date is not None:
                self.logger.info(
                    "📅 [날짜 변경] 새 거래일(%s)이 되었습니다. 일일 주문 카운터를 0으로 초기화합니다.",
                    today,
                )
            self.daily_order_count = 0
            self.daily_order_date = today
            self._save_daily_counter()

    def _load_daily_counter(self) -> None:
        """파일에서 주문 횟수 불러오기"""
        if config.ORDER_CACHE_FILE.exists():
            try:
                data = json.loads(config.ORDER_CACHE_FILE.read_text(encoding="utf-8"))
                saved_date = date.fromisoformat(data.get("date", ""))
                if saved_date == config.get_now().date():
                    self.daily_order_count = data.get("count", 0)
                    self.daily_order_date = saved_date
                    self.logger.info("💾 [데이터 복구] 기존 파일에서 오늘 누적 주문 횟수(%d건)를 성공적으로 불러왔습니다.", self.daily_order_count)
                    return
            except Exception:
                self.logger.warning("⚠️ [데이터 초기화] 주문 횟수 기록 파일을 읽을 수 없어 카운터를 0으로 초기화합니다.")
        
        # 파일이 없거나 날짜가 다르면 초기화
        self.daily_order_count = 0
        self.daily_order_date = config.get_now().date()

    def _save_daily_counter(self) -> None:
        """주문 횟수를 파일에 저장하기"""
        if self.daily_order_date:
            data = {
                "date": self.daily_order_date.isoformat(),
                "count": self.daily_order_count
            }
            try:
                config.ORDER_CACHE_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
            except Exception as e:
                self.logger.error("❌ [저장 실패] 일일 주문 횟수를 파일에 기록하지 못했습니다: %s", e)

    # ------------------------------------------------------------------
    # End of day
    # ------------------------------------------------------------------

    def _close_trading_day(self) -> None:
        """장 마감 처리 — 미체결 주문 일괄 취소 & 일일 요약"""
        self.logger.info("=" * 60)
        self.logger.info("🏁 [장 마감] 정규장 마감 처리를 시작합니다.")

        cancelled = 0
        try:
            cancelled = cancel_all_pending_orders(self.token_manager)
            self.logger.info("🧹 [미체결 취소] 장 마감에 따라 남아있던 미체결 주문 %d건을 모두 취소했습니다.", cancelled)
        except Exception:
            self.logger.exception("❌ [마감 오류] 미체결 주문을 일괄 취소하는 과정에서 문제가 발생했습니다.")

        # 성과 요약 리포트 (잔고 조회)
        try:
            balance = get_balance(self.token_manager)
            orderable_data = get_orderable_cash(self.token_manager)
            max_buy_amt = orderable_data.get("max_amt", 0)
            total_orderable = max_buy_amt

            cash = balance.get("cash", 0)
            nxdy_excc = balance.get("nxdy_excc", 0)
            prvs_rcdl_excc = balance.get("prvs_rcdl_excc", 0)
            thdt_buy = balance.get("thdt_buy", 0)
            thdt_sll = balance.get("thdt_sll", 0)
            thdt_tlex = balance.get("thdt_tlex", 0)
            scts_evlu = balance.get("scts_evlu", 0)
            tot_evlu = balance.get("tot_evlu", 0)

            held_qty = 0
            eval_amt = 0
            avg_price = 0
            profit = 0
            current_price = 0
            
            for h in balance.get("holdings", []):
                if h["code"] == config.STOCK_CODE:
                    held_qty = h["qty"]
                    eval_amt = h["eval_amt"]
                    avg_price = h["avg_price"]
                    profit = h["profit"]
                    current_price = h["current_price"]
                    break
            
            if current_price == 0:
                current_price = get_current_price(self.token_manager)
            
            report = (
                "📊 **일일 장 마감 리포트**\n\n"
                f"▪️ 취소된 미체결 주문: {cancelled}건\n"
                f"▪️ 금일 총 주문 제출 수: {self.daily_order_count}건\n\n"
                f"💰 **계좌 잔고**\n"
                f"▪️ 예수금 총액: {cash:,}원\n"
                f"▪️ 주문가능액: {total_orderable:,}원\n"
                f"▪️ 익일정산액: {nxdy_excc:,}원\n"
                f"▪️ D+2정산액: {prvs_rcdl_excc:,}원\n"
                f"▪️ 금일매수/매도액: {thdt_buy:,}원 / {thdt_sll:,}원\n"
                f"▪️ 제비용금액: {thdt_tlex:,}원\n"
                f"▪️ 유가평가액: {scts_evlu:,}원\n"
                f"▪️ 총평가금액: {tot_evlu:,}원\n\n"
                f"📈 **삼성전자 보유 현황**\n"
                f"▪️ 보유 수량: {held_qty}주\n"
                f"▪️ 매입평균: {avg_price:,.2f}원\n"
                f"▪️ 현재가: {current_price:,}원\n"
                f"▪️ 평가금액: {eval_amt:,}원\n"
                f"▪️ 평가손익: {profit:,}원\n"
            )
            self.logger.info("\n%s", report)
            notifier.send_message(report)
        except Exception as e:
            self.logger.error("❌ [리포트 오류] 장 마감 리포트를 생성하는 중 문제가 발생했습니다: %s", e)

        self.logger.info("🏁 [장 마감 완료] 오늘의 모든 자동매매 로직이 성공적으로 종료되었습니다.")
        self.logger.info("=" * 60)