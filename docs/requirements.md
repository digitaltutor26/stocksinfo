# StocksInfo 요구사항 명세서 (현행 시스템 기준)

> **기준 저장소**: `https://github.com/digitaltutor26/stocksinfo` (최신 커밋 `bad4d1b` 기준)  
> **작성 목적**: 별도의 요구사항 명세서가 부재함에 따라, 현행 소스코드 및 개편 설계 문서(`REDESIGN.md`)를 역분석하여 현재 구현된 기능 요구사항과 시스템 상태를 명세함.

---

## 1. 서비스 개요

- **서비스명**: StocksInfo (중장기 보유 투자자용 신호 기반 모닝 브리핑 서비스)
- **핵심 가치**: 매일 단순 지수 등락률을 요약하는 대신, **"관심종목이 현재 어디쯤 위치해 있는지(위치)"**와 **"어제/과거 대비 무엇이 달라졌는지(변화 신호)"**를 규칙 엔진(Python)으로 먼저 판정한 뒤, 신호가 발생했을 때만 LLM 해설을 붙여 2~3분 내 읽을 수 있는 이메일 브리핑을 발송한다.
- **운용 방식**:
  - GitHub Actions 스케줄러(매일 07:30 KST / `30 22 * * *` UTC) 및 수동 실행(`workflow_dispatch`)
  - 로컬/서버 FastAPI 웹 대시보드(`web/app.py`)를 통한 관심종목·수신자 관리, 즉시 발송 테스트, GitHub 동기화

---

## 2. 현행 시스템 아키텍처 및 모듈 구성

```
stocksinfo/
├── main.py                        # 전체 파이프라인 오케스트레이션 (수집 → 신호 판정 → 스냅샷 저장 → 리포트 생성 → 발송)
├── config.py                      # 환경변수 로드 및 필수 키 검증 (OPENROUTER_API_KEY, EMAIL_*, FRED_API_KEY)
├── store.py                       # 관심종목(watchlist.json) 및 수신자(recipients.json) JSON 파일 입출력
├── history.py                     # SQLite(stocksinfo.db) 일별 스냅샷(daily_snapshot) 저장 및 조회
├── signals.py                     # 축 B 규칙 엔진 (위치 및 펀더멘털 기반 이상 신호 6종 판정)
├── report.py                      # 신호등(🔴/🟡/⚪) 헤더, 주간 캘린더, 무신호 단문 리포트 포맷터
├── collectors/
│   ├── watchlist_stocks.py        # 축 A: 관심종목 2년 시세 기반 52주 백분위, 200일선 돌파, 수익률, 거래량 배수, 종목 뉴스 수집
│   ├── fundamentals.py            # 축 C: PER/PBR, 배당수익률/배당락일, 목표주가 컨센서스, 차기 실적발표일 수집
│   ├── economic_cal.py            # 축 D: 주간 반복 미국 거시 일정 + FRED API 실시간 발표 일정 수집
│   ├── us_market.py               # 미국 주요 지수(S&P500, NASDAQ 등) 및 섹터 ETF 일간 등락 수집
│   ├── kr_market.py               # 한국 주요 지수(KOSPI, KOSDAQ, 원/달러) 및 ETF 일간 등락 수집
│   └── news.py                    # 주요 증시 RSS 피드(Investing.com KR, Google News KR/US) 뉴스 수집
├── summarizer/
│   └── openrouter_client.py       # OpenRouter 무료 LLM 모델 폴백 체인 기반 신호 해설 생성 (interpret_signals)
├── delivery/
│   └── email_sender.py            # Gmail SMTP 기반 멀티파트(Plain Text + HTML) 이메일 및 에러 알림 발송
├── web/
│   ├── app.py                     # FastAPI 기반 관리 대시보드 백엔드
│   └── templates/index.html       # TailwindCSS 기반 관리 UI 템플릿
└── tests/                         # 단위/통합 테스트 스위트 (총 58개 테스트 케이스)
```

---

## 3. 기능 요구사항 (현행 구현 완료 항목)

### FR-01. 데이터 수집 (Collectors)
1. **관심종목 위치 지표 수집 (`collectors/watchlist_stocks.py`)**
   - `yfinance`를 통해 종목별 최근 2년(`period="2y"`) 일봉 데이터를 수집한다.
   - **산출 지표**:
     - 전일 종가(`prev_close`), 당일 종가(`last_close`), 일간 등락률(`change_pct`), 거래량(`volume`)
     - 52주 최고가/최저가(`week52_high`, `week52_low`), 52주 밴드 내 백분위(`week52_pct`), 52주 고점 대비 낙폭(`drawdown_from_high_pct`)
     - 당일 신규 52주 신고가/신저가 경신 여부(`is_new_52w_high`, `is_new_52w_low` — 당일 제외 직전 52주 윈도우와 비교)
     - 200일 이동평균선(`ma200`), 200일선 이격도(`pct_vs_ma200`), 200일선 돌파 방향(`ma200_cross`: `golden` / `death` / `None`) 및 직전 추세 유지 개월 수(`ma200_cross_months_since_prior`)
     - 3개월(63거래일)·6개월(126거래일)·12개월(252거래일) 누적 수익률(`return_3m_pct`, `return_6m_pct`, `return_12m_pct`)
     - 벤치마크(미국 `^GSPC`, 한국 `^KS11`) 대비 6개월 상대강도(`relative_strength_6m_pct`)
     - 20일 평균 거래량(`volume_avg_20d`) 및 당일 거래량 배수(`volume_ratio`)
     - 종목별 최신 뉴스 최대 5건(`news`: `title`, `url`)
2. **펀더멘털 및 일정 수집 (`collectors/fundamentals.py`)**
   - `yfinance` `Ticker.info` 및 `Ticker.calendar`에서 밸류에이션·컨센서스·일정 정보를 수집한다.
   - **산출 지표**: `trailing_pe`, `forward_pe`, `price_to_book`, `dividend_yield`, `ex_dividend_date`, `debt_to_equity`, `free_cashflow`, `target_mean_price`, `target_high_price`, `target_low_price`, `recommendation`, `num_analyst_opinions`, `next_earnings_date`
3. **경제 캘린더 및 시장/뉴스 수집 (`economic_cal.py`, `news.py`, `us_market.py`, `kr_market.py`)**
   - 요일별 주요 미국 경제지표 일정 및 `FRED_API_KEY` 설정 시 FRED Release Dates API 일정을 수집한다.
   - 병렬 수집기(`main.collect_all`)는 `ThreadPoolExecutor(max_workers=6)`로 30초 타임아웃 내 모든 수집기를 실행하고, 개별 실패를 `_errors` 배열로 집계한다.

### FR-02. 일별 스냅샷 영속화 (`history.py`)
1. SQLite 데이터베이스(`stocksinfo.db`)의 `daily_snapshot` 테이블에 `(date, symbol)` 복합 기본키로 일별 스냅샷을 저장(`UPSERT`)한다.
2. 저장 컬럼: `date`, `symbol`, `last_close`, `trailing_pe`, `target_mean_price`, `volume`
3. 조회 인터페이스:
   - `get_snapshot(symbol, date)`: 특정 일자 스냅샷 단건 조회
   - `get_snapshots_since(symbol, since_date)`: 특정 일자 이후 스냅샷 시계열 오름차순 조회
   - `get_latest_snapshot_before(symbol, before_date)`: 특정 일자 이전 가장 최근 스냅샷 조회

### FR-03. 규칙 기반 신호 탐지 (`signals.py`)
LLM 호출 전 Python 규칙 엔진이 다음 6가지 조건을 판정하여 신호 리스트(`symbol`, `severity`, `type`, `message`)를 생성한다.
1. **200일선 돌파 (`ma200_cross`)**: 상향 돌파(`golden`) 시 `yellow`, 하향 이탈(`death`) 시 `red` (직전 유지 개월 수 표기)
2. **52주 신고가/신저가 (`week52_high` / `week52_low`)**: 신고가 경신 시 `yellow`, 신저가 경신 시 `red`
3. **거래량 급증 (`volume_spike`)**: 20일 평균 대비 거래량 2.0배(`VOLUME_SPIKE_RATIO`) 이상 시 `yellow`
4. **실적발표 임박 (`earnings_soon`)**: 차기 실적발표일이 오늘 기준 D-0 ~ D-7 이내일 때 `yellow`
5. **PER 밸류에이션 밴드 이탈 (`valuation_band`)**: 최근 2년(730일) 내 저장된 스냅샷의 `trailing_pe` 샘플이 최소 20개(`PER_BAND_MIN_SAMPLES`) 이상이고, 당일 PER이 평균 대비 ±1표준편차(`std`)를 벗어날 때 `yellow`
6. **애널리스트 목표주가 주간 변화 (`target_price_change`)**: 6일 이전 최근 스냅샷의 `target_mean_price` 대비 ±3.0%(`TARGET_PRICE_CHANGE_THRESHOLD_PCT`) 이상 변동 시 `yellow`

### FR-04. LLM 신호 해석 및 리포트 생성 (`openrouter_client.py`, `report.py`, `main.py`)
1. **무신호 시 LLM 생략**: 탐지된 신호가 0건이면 OpenRouter API를 호출하지 않고 `"오늘은 관심종목에 특이사항이 없습니다."` 단문 리포트를 즉시 반환한다.
2. **신호 발생 시 LLM 해설**: 신호가 발생한 종목에 한해 관련 뉴스 최대 3건(`related_news`)을 첨부하여 OpenRouter 무료 모델 폴백 체인(`nemotron-3-super`, `gemma-4-31b`, `gpt-oss-20b`)으로 종목별 2~3문장 해설을 생성한다.
3. **신호등 레이아웃**: `🔴 확인 필요`, `🟡 관찰`, `⚪ 정상 범위`, `📅 이번 주` 캘린더, `─── 상세` 해설, 면책조항 순서로 텍스트를 조립한다.

### FR-05. 이메일 발송 및 웹 대시보드 (`delivery/email_sender.py`, `web/app.py`)
1. `recipients.json`에 등록된 이메일 목록(비어 있을 경우 `.env`의 `EMAIL_RECEIVER`)으로 Gmail SMTP(포트 587, STARTTLS)를 통해 멀티파트 이메일을 발송한다.
2. 치명적 예외 발생 시 `send_error()`로 오류 트레이스백을 발송한다.
3. FastAPI 웹 대시보드(`web/app.py`)에서 미국/한국 관심종목 추가·삭제, 수신자 이메일 추가·삭제, 즉시 실행(`/run-now`), GitHub 반영(`/push`) 기능을 제공한다.

---

## 4. 현행 시스템의 한계 및 미구현 구간 (Gap 분석)

`REDESIGN.md` 로드맵과 현행 소스코드를 대조한 결과, Phase 1~3(축 A/B/C/D 파이프라인 전환 및 SQLite 히스토리 도입)은 구현 완료되었으나 다음 격차가 존재한다.

1. **웹 대시보드 내 히스토리·상태 가시성 부재 (`REDESIGN.md` Phase 4 미구현)**
   - `stocksinfo.db`에 매일 스냅샷(`last_close`, `trailing_pe`, `target_mean_price`, `volume`)이 축적되고 있으나, 웹 대시보드(`web/app.py`, `web/templates/index.html`)는 단순 종목 코드 배지(`NVDA`, `AAPL`)만 나열할 뿐 저장된 스냅샷 히스토리나 최근 수집 지표를 전혀 보여주지 않는다.
   - 특히 `signals.py`의 PER 밴드 신호는 최소 20일 이상의 스냅샷(`PER_BAND_MIN_SAMPLES = 20`)이 쌓여야 활성화되는데, 사용자가 현재 종목별로 스냅샷이 몇 건 축적되었는지, 최근 종가·PER·목표주가 추이가 어떠한지 확인할 수 없다.
2. **LLM 해설 요청 시 위치·펀더멘털 맥락 미전달 (`main.py` `_attach_related_news`)**
   - `watchlist_stocks.py`와 `fundamentals.py`에서 52주 백분위, 200일선 이격도, 고점 대비 낙폭, 3/6/12개월 수익률, 상대강도, PER/PBR 등 풍부한 데이터를 수집하고도, 정작 `main.py`에서 `interpret_signals()`에 전달할 때는 `{"symbol", "severity", "type", "message", "related_news"}`만 넘기고 있어 LLM이 신호의 정량적 맥락(예: 현재 52주 밴드 몇 % 지점인지, 벤치마크 대비 상대강도가 얼마인지)을 함께 설명하지 못한다.
3. **레거시 수집기(`us_market`, `kr_market`, `news`)의 불필요한 호출**
   - `main.collect_all()`이 매 실행마다 `us_market`, `kr_market`, `news`를 스레드풀에서 호출하지만, `main.build_email()`은 `watchlist`, `fundamentals`, `economic_cal`만 사용한다.
