"""
main.py — 삼성전자 자동매매 시스템 진입점

사용법:
    python main.py
"""

import sys
import threading
import time

from trader import AutoTrader
import market_data
import account
import config


def _input_listener(trader: AutoTrader) -> None:
    """백그라운드에서 사용자 입력을 대기합니다."""
    while not trader.stop_event.is_set():
        try:
            user_input = input().strip()
            if user_input == "종료":
                print("\n🛑 [시스템 종료] 종료 명령을 수신했습니다. 현재 작업을 마무리하고 안전하게 종료합니다...")
                trader.stop_event.set()
                break
            elif user_input == "조회":
                print_status(trader)
            elif user_input == "도움":
                _print_runtime_help()
            elif user_input.startswith("스프레드"):
                parts = user_input.split()
                if len(parts) > 1 and parts[1].isdigit():
                    new_spread = int(parts[1])
                    trader.spread_offset = new_spread
                    print(f"  ✅ [설정 변경] 매매 스프레드가 {new_spread:,}원으로 변경되었습니다.")
                else:
                    print("  ⚠️ [입력 오류] 숫자만 입력해 주세요. (올바른 예시: 스프레드 1000)")
            elif user_input:
                print("  💡 [안내] 알 수 없는 명령어입니다. '조회', '스프레드 <숫자>', '종료', '도움' 중 하나를 입력해 주세요.")
        except EOFError:
            break


def _print_runtime_help() -> None:
    """실행 중 사용 가능한 명령어 안내를 출력합니다."""
    print("\n" + "-" * 60)
    print("  📋 [도움말] 실행 중 사용 가능한 명령어")
    print("-" * 60)
    print("  🔹 조회       : 현재 계좌 잔고 및 삼성전자 보유 현황을 보여줍니다.")
    print("  🔹 스프레드 <숫자> : 실행 중 목표 매매가 간격(스프레드)을 변경합니다. (예: 스프레드 1500)")
    print("  🔹 종료       : 장 마감 리포트를 출력하고 프로그램을 안전하게 종료합니다.")
    print("  🔹 도움       : 지금 보시는 이 도움말을 다시 출력합니다.")
    print("-" * 60 + "\n")


def print_status(trader: AutoTrader) -> None:
    """현재가 및 계좌 현황을 조회하여 상세하게 출력합니다."""
    print("\n🔎 [상태 조회] 증권사 서버에서 최신 계좌 정보를 불러오는 중입니다. 잠시만 기다려주세요...")
    try:
        balance = account.get_balance(trader.token_manager)
        orderable_data = account.get_orderable_cash(trader.token_manager)
        orderable_cash = orderable_data.get("cash", 0)
        max_buy_amt = orderable_data.get("max_amt", 0)
        
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
                
        # 만약 미보유 시에는 별도로 현재가만 한 번 더 조회합니다
        if current_price == 0:
            current_price = market_data.get_current_price(trader.token_manager)
                
        # 모의투자 앱과 동일하게 주문가능액 표시 (미수/신용 포함 최대 매수가능금액)
        total_orderable = max_buy_amt
        
        print("\n=====================================================================")
        print("                        📊 현재 계좌 및 포지션 상태")
        print("=====================================================================")
        print("[ 💰 계좌 잔고 ]")
        print(f"▪️ 예수금 총액: {cash:>10,}원 \t▪️ 익일정산액: {nxdy_excc:>10,}원 \t▪️ D+2정산액: {prvs_rcdl_excc:>10,}원")
        print(f"▪️ 금일매수액 : {thdt_buy:>10,}원 \t▪️ 금일매도액: {thdt_sll:>10,}원 \t▪️ 제비용금액 : {thdt_tlex:>10,}원")
        print(f"▪️ 주문가능액 : {total_orderable:>10,}원 \t▪️ 유가평가액: {scts_evlu:>10,}원 \t▪️ 총평가금액 : {tot_evlu:>10,}원")
        print("\n[ 📈 보유 종목 (삼성전자) ]")
        print(f"{'종목명':<8}\t{'보유수량':>6}\t{'매입평균가':>12}\t{'현재가':>10}\t{'평가금액':>12}\t{'평가손익':>12}")
        print("-" * 75)
        if held_qty > 0:
            print(f"{'삼성전자':<8}\t{held_qty:>6}주\t{avg_price:>12,.2f}원\t{current_price:>10,}원\t{eval_amt:>12,}원\t{profit:>12,}원")
        else:
            print(f"{'삼성전자':<8}\t{0:>6}주\t{0:>12.2f}원\t{current_price:>10,}원\t{0:>12,}원\t{0:>12,}원")
            
        print("\n[ ⚙️ 시스템 가동 상태 ]")
        print(f"▪️ 오늘 남은 주문 횟수: {max(0, config.MAX_DAILY_ORDERS - trader.daily_order_count)}회")
        print("=====================================================================\n")
    except Exception as e:
        print(f"\n❌ [조회 실패] 증권사 서버에서 계좌 정보를 불러오는 중 문제가 발생했습니다. (사유: {e})\n")


def main() -> None:
    """AutoTrader를 생성하고 메뉴를 표시합니다."""
    try:
        print("🚀 [시스템 시작] 자동매매 시스템을 초기화하는 중입니다...")
        trader = AutoTrader()
        
        while True:
            print("\n" + "=" * 60)
            print("       🤖 삼성전자 자동매매 시스템 (모의투자 환경)")
            print("=" * 60)
            print("  [1] 📊 내 계좌 현황 및 삼성전자 상태 조회")
            print("  [2] ▶️ 트레이딩 봇 시작")
            print("  [3] 🛑 프로그램 종료")
            print("=" * 60)
            choice = input("원하시는 메뉴의 번호를 입력하세요: ").strip()
            
            if choice == "1":
                print_status(trader)
                time.sleep(1)  # 사용자가 읽을 시간 제공
            elif choice == "2":
                # 주문 모드 선택
                print("\n" + "-" * 60)
                print("  🎯 어떤 방식으로 매매를 진행할까요?")
                print("-" * 60)
                print("  [1] 지정가 주문 (현재가에서 일정 금액을 뺀/더한 가격에 예약)")
                print(f"      → 🟢 매수 목표가: 현재가 - {config.SPREAD_OFFSET:,}원")
                print(f"      → 🔴 매도 목표가: 현재가 + {config.SPREAD_OFFSET:,}원")
                print("\n  [2] 시장가 주문 (가격 상관없이 무조건 즉시 체결)")
                print("      → ⚡ 조건 만족 시 즉시 매수/매도 실행")
                print("-" * 60)
                mode_choice = input("  선택 (1 또는 2): ").strip()
                
                if mode_choice == "2":
                    trader.order_mode = "market"
                    print("\n  ✅ [설정 완료] '시장가 모드'로 트레이딩을 시작합니다.")
                else:
                    trader.order_mode = "limit"
                    spread_input = input(f"  원하시는 스프레드 금액을 입력하세요 (엔터 시 기본값 {config.SPREAD_OFFSET}원 적용): ").strip()
                    if spread_input.isdigit():
                        trader.spread_offset = int(spread_input)
                    elif spread_input != "":
                        print(f"  ⚠️ [입력 안내] 입력값이 올바르지 않아 기본값인 {config.SPREAD_OFFSET}원으로 자동 설정합니다.")
                        trader.spread_offset = config.SPREAD_OFFSET
                    print(f"\n  ✅ [설정 완료] '지정가 모드'로 트레이딩을 시작합니다. (스프레드 간격: {trader.spread_offset:,}원)")
                break
            elif choice == "3":
                print("\n👋 프로그램을 안전하게 종료합니다. 이용해 주셔서 감사합니다!")
                sys.exit(0)
            else:
                print("\n⚠️ [입력 오류] 메뉴에 없는 번호입니다. 1, 2, 3 중에서 하나를 선택해 주세요.")

        # 트레이딩 루프 진입 (메뉴 2번 선택 시)
        listener_thread = threading.Thread(
            target=_input_listener, args=(trader,), daemon=True
        )
        listener_thread.start()
        
        mode_label = "시장가" if trader.order_mode == "market" else "지정가"
        print("\n" + "=" * 60)
        print(f"  🚀 트레이딩 봇이 백그라운드에서 실행 중입니다! (모드: {mode_label})")
        print("-" * 60)
        print("  명령어를 입력하여 언제든 봇을 제어할 수 있습니다:")
        print("  🔹 '조회' — 실시간 계좌 잔고 확인")
        print("  🔹 '종료' — 장 마감 리포트 출력 후 봇 완전 정지")
        print("  🔹 '도움' — 전체 명령어 안내 보기")
        print("=" * 60 + "\n")
        
        trader.run()
        
    except KeyboardInterrupt:
        print("\n\n사용자에 의해 강제 종료되었습니다.")
    except Exception as e:
        print(f"\n\n치명적인 오류 발생: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()