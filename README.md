# 🤖 삼성전자 모의투자 자동매매 봇 (Samsung Auto Trader)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![KIS Open API](https://img.shields.io/badge/KIS%20API-Mock%20Trading-success)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](#)

한국투자증권 Open API(모의투자)를 활용한 **삼성전자(005930) 자동매매 봇**입니다.

---

## 🧠 핵심 매매 전략 (Trading Strategy)

본 시스템은 **"지정가 기반 스프레드 확보 전략 (Market Making Variant)"** 을 기본 골조로 합니다.

1. **시세 포착**: 현재 시장가(Current Price)를 실시간으로 조회합니다.
2. **양방향 호가 제출**: 현재가를 기준으로 위아래 특정 호가(Spread Offset)에 매수와 매도 주문을 동시에(또는 순차적으로) 걸어둡니다. (예: 현재가 80,000원, 스프레드 2,000원 -> 매수 78,000원 / 매도 82,000원 제출)
3. **변동성 수익 창출**: 주가가 박스권에서 움직이거나 일시적인 변동성이 커질 때, 낮게 걸어둔 매수 주문이 체결되고 이후 반등 시 높게 걸어둔 매도 주문이 체결되며 **스프레드 차익(Spread Margin)**을 얻는 방식입니다.
4. **리스크 관리 (Position Sizing)**: 시장이 한 방향으로 강하게 추세를 탈 경우를 대비하여, 1회 주문 수량과 최대 보유 수량(Max Position Size), 일일 최대 주문 횟수(Max Daily Orders)를 제한합니다.

---

## 🏛️ 시스템 아키텍처 (System Architecture)

본 프로젝트는 유지보수성과 확장성을 고려하여 **객체지향 프로그래밍(OOP) 및 모듈화 설계**를 적용했습니다.

루트 디렉토리는 패키지 메타데이터(`pyproject.toml`)와 참고 자료(`reference_materials/`)를 포함하며, 실제 실행 로직은 `samsung_auto_trader/` 내부에 집중되어 있습니다.

### 구조도 (Directory & Modules)
```text
samsung_auto_trader/
├── main.py            # 진입점 (Entry Point), 예외 처리 기반 시스템 시작/종료
├── trader.py          # [Integration] 메인 트레이딩 루프 (AutoTrader 클래스) 및 상태 관리
├── config.py          # [Foundation] 환경변수 및 매매 파라미터(설정값) 통합 관리
├── logger.py          # [Foundation] 콘솔 및 일별 파일 듀얼 로깅 시스템
├── api_client.py      # [Foundation] KIS API 전용 HTTP 통신 래퍼 (에러/재시도 처리)
├── auth.py            # [Foundation] OAuth2.0 기반 토큰 발급, 갱신 및 Hashkey 암호화 로직
├── market_data.py     # [Core Business] 실시간 현재가(종목 시세) 조회
├── account.py         # [Core Business] 계좌 잔고, 보유 종목, 미체결 내역 조회
├── orders.py          # [Core Business] 신규 주문(매수/매도) 전송 및 기존 주문 취소
├── strategy.py        # [Core Business] 한국거래소(KRX) 틱 사이즈 계산 및 주문 유효성 검사 로직
```

### 트레이딩 루프(Trading Loop) 플로우
1. `장 시작 전 대기` → 2. `루프 시작` → 3. `시세/잔고/미체결 조회` → 4. `주문 가격 산출(Strategy)` → 5. `안전장치 검사` → 6. `조건 충족 시 주문 제출` → 7. `대기 (Polling Interval)` → 8. `장 마감 시 미체결 일괄 취소 및 종료`

---

## 🚀 사전 준비 및 설치 방법

### 1. KIS 모의투자 API 키 발급
- [KIS Developers](https://apiportal.koreainvestment.com/) 접속 후 모의투자 서비스 신청
- **AppKey** 와 **AppSecret** 발급, [한국투자증권](https://www.truefriend.com/) 계좌 개설

### 2. 설치
```bash
cd /workspaces/open-trading-api/samsung_auto_trader
python -m pip install -r requirements.txt
```

이 저장소는 실제로 `samsung_auto_trader/` 내부가 실행 대상입니다. 루트 디렉터리에서 `python -m pip install -e .` 대신, 하위 패키지 디렉터리에서 필요한 의존성을 설치하고 실행하세요.

### 3. 환경변수 파일 생성 및 설정
```bash
cd /workspaces/open-trading-api/samsung_auto_trader
cp .env.example .env
```

`.env` 파일을 열어 본인의 인증 정보를 기입합니다.
```dotenv
# .env
KIS_ACCOUNT=50123456-01           # 계좌번호 전체 (형식: XXXXXXXX-XX)
KIS_ACCOUNT_PROD=01               # 계좌 상품코드 (보통 01)
KIS_APPKEY=your_mock_appkey       # 모의투자 AppKey (한국투자증권 개발자 포탈)
KIS_APPSECRET=your_mock_appsecret # 모의투자 AppSecret
```

> **보안 알림**: `.env` 파일은 `.gitignore`에 등록되어 있어 깃허브 등 저장소에 절대 커밋되지 않습니다.

### 4. 프로그램 실행
```bash
cd samsung_auto_trader
python main.py
```

프로그램을 실행하면 **메뉴 선택 화면**이 나타납니다:

```
============================================================
       🤖 삼성전자 자동매매 시스템 (모의투자 환경)
============================================================
  [1] 📊 내 계좌 현황 및 삼성전자 상태 조회
  [2] ▶️ 트레이딩 봇 시작
  [3] 🛑 프로그램 종료
============================================================
```

**[2] 트레이딩 봇 시작**을 선택하면 다음 단계로 진행됩니다:

1. **주문 모드 선택** - 지정가 주문(스프레드 설정) 또는 시장가 주문 선택
2. **스프레드 금액 입력** (지정가 모드 선택 시) - 기본값 2,000원 또는 사용자 정의 값
3. **트레이딩 루프 시작** - 이제 백그라운드에서 자동 매매가 진행됩니다.

### 실행 중 명령어

트레이딩 봇이 시작된 후 터미널에서 다음 명령어들을 입력할 수 있습니다:

| 명령어 | 설명 |
|---|---|
| `조회` | 현재 계좌 잔고, 삼성전자 보유 현황, 남은 주문 가능 횟수를 조회 |
| `스프레드 <숫자>` | 실행 중 매매 스프레드를 동적으로 변경 (예: `스프레드 1500`) |
| `도움` | 사용 가능한 명령어 목록 출력 |
| `종료` | 진행 중인 미체결 주문을 안전하게 취소하고 프로그램 종료 (Graceful Shutdown) |

### 🌐 GitHub Codespaces에서 실행

Codespaces에서도 동일하게 아래 명령으로 진행하면 됩니다.

```bash
cd /workspaces/open-trading-api/samsung_auto_trader
python -m pip install -r requirements.txt
cp .env.example .env
python main.py
```

> **팁**: 한 번 설치한 뒤에는 다음 접속 시 `python main.py`만 실행하면 됩니다. Codespaces 환경에서는 의존성이 캐시되어 재설치가 필요 없는 경우가 많습니다.

---

## 📱 텔레그램 (Telegram) 실시간 알림 연동
봇이 동작하면서 발생하는 주문 체결 내역이나 장 마감 리포트를 스마트폰으로 받아볼 수 있습니다.
1. 텔레그램에서 `BotFather`를 통해 봇을 생성하고 **Bot Token**을 발급받습니다.
2. 봇 채팅방에 메시지를 하나 보낸 후, `https://api.telegram.org/bot<TOKEN>/getUpdates` 에 접속하여 본인의 **Chat ID**를 확인합니다.
3. `.env` 파일에 발급받은 값을 입력합니다. (비워두면 알림 기능만 꺼지고 매매는 정상 작동합니다)
```dotenv
TELEGRAM_BOT_TOKEN=123456789:ABCDefghIJKL...
TELEGRAM_CHAT_ID=12345678
```

---

## 📊 설정 매개변수 (`config.py`)

| 설정 항목 | 기본값 | 설명 | .env 오버라이드 |
|---|---|---|---|
| `STOCK_CODE` | `005930` | 대상 종목 코드 (삼성전자) | ✗ (고정값) |
| `SPREAD_OFFSET` | `2000` | 현재가 대비 상하단 매수/매도 지정가 오프셋 폭 (원) | ✓ `SPREAD_OFFSET=1500` |
| `ORDER_QUANTITY` | `1` | 1회 주문 수량 (주) | ✓ `ORDER_QUANTITY=2` |
| `POLLING_INTERVAL_SEC` | `30` | 시장을 스캔하고 루프를 도는 간격 (초) | ✓ `POLLING_INTERVAL_SEC=60` |
| `MAX_DAILY_ORDERS` | `50` | 일일 최대 신규 주문 건수 (Overtrading 방지) | ✓ `MAX_DAILY_ORDERS=100` |
| `MAX_POSITION_SIZE` | `10` | 최대 허용 보유 주수 (Risk Limit) | ✓ `MAX_POSITION_SIZE=5` |
| `TRADING_START` | `09:10` | 매매 개시 시각 (KST) | ✗ (고정값) |
| `TRADING_END` | `15:18` | 신규 주문 진입 마감 시각 (타임드리프트 방어) | ✗ (고정값) |
| `TRADING_CLOSE` | `15:20` | 동시호가 진입 전 미체결 일괄 취소 및 프로그램 종료 | ✗ (고정값) |

---

## 📝 파일 로깅 시스템 (Logging)

실행 시 `logs/` 디렉토리가 생성되며, `trading_YYYYMMDD.log` 형태로 매일 새로운 로그 파일이 작성됩니다. 
콘솔에는 중요(INFO) 정보가 출력되며 파일에는 디버깅용(DEBUG) 상세 API 요청/응답 기록이 모두 저장되어 사후 분석(Post-mortem)이 가능합니다.

---

## 🔒 캐시 및 토큰 관리 (Token & Cache Management)

### 토큰 캐시 (`token_cache.json`)
- OAuth2.0 액세스 토큰을 자동으로 저장하여 매번 새로 발급받지 않습니다.
- 토큰 만료 시간 도달 시 자동으로 갱신됩니다.
- `.gitignore`에 등록되어 있으므로 절대 커밋되지 않습니다.

### 주문 캐시 (`order_cache.json`)
- 현재 활성화된 미체결 주문 목록을 메모리에 유지합니다.
- 중복 주문 방지 로직에서 현재 네트워크상의 동일 가격/방향 주문 존재 여부를 판단합니다.
- 프로그램 재시작 시 초기화됩니다.

---

## 🛡️ 안정성 및 에러 처리 메커니즘 (Detailed Safety Features)

### 1. API 레이트 리미트 대응 (TPS Management)
- 모든 API 호출 사이에 **0.5초 Sleep**을 강제 적용하여 KIS API의 초당 호출 제한(TPS)을 준수합니다.
- 과도한 요청으로 인한 차단을 방지합니다.

### 2. 지수 백오프 기반 재시도 (Exponential Backoff Retry)
- 네트워크 오류나 일시적인 API 서버 지연 발생 시 즉시 실패 처리하지 않고, 지수 백오프 전략을 사용합니다.
- 재시도 대기 시간: 1초 → 2초 → 4초 (최대 3회)
- 휘발성 오류로부터의 복구력을 높입니다.

### 3. 중복 주문 방지 로직 (Idempotency Check)
- 신규 주문 제출 전 현재 미체결 주문 목록을 조회합니다.
- 동일한 가격과 매매 방향(매수/매도)의 주문이 이미 존재하면 중복 제출을 차단합니다.
- 실수로 인한 과잉 주문을 효과적으로 방지합니다.

### 4. 사이클 격리 (Cycle Isolation)
- 메인 트레이딩 루프의 단일 사이클 내에서 에러 발생 시 프로그램이 뻗지 않고(Crash) 다음 사이클로 넘어갑니다.
- `try-except` 블록으로 각 사이클을 격리하여 부분 장애가 전체 시스템 장애로 확산되는 것을 방지합니다.

---

## 🔮 추후 발전 방향 (Future Work)

1. **멀티 종목 확장**: 현재는 단일 종목(삼성전자)에만 고정되어 있으나, 리스트 형태의 여러 종목을 동시에 감시하고 주문하는 형태로 확장할 수 있습니다.
2. **동적 오프셋 산출 (ATR 적용)**: 고정된 `SPREAD_OFFSET` 대신, Average True Range (ATR)나 볼린저 밴드 등 보조지표를 결합하여 변동성에 따라 주문 폭을 동적으로 조절하는 로직으로 발전시킬 수 있습니다.
3. **웹소켓(WebSocket) 도입**: 현재의 Polling 방식(REST API 30초 주기)을 넘어 KIS 웹소켓 API를 도입해 틱(Tick) 단위의 실시간 호가 반응성을 확보할 수 있습니다.

---

## ⚠️ 주의사항

* 본 프로젝트는 **모의투자(Mock Trading)** 전용으로 설계되었습니다. 실전 계좌에서 작동시키기 위해서는 `config.py`의 `BASE_URL` 및 일부 API Endpoint(`tr_id` 등)의 수정이 필요합니다.
* 프로그램 사용으로 인해 발생하는 모든 투자 결과의 책임은 사용자 본인에게 있습니다.
