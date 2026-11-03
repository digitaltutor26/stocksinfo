# StocksInfo 통합 요구사항 명세서 (`docs/requirements.md`)

> **기준 저장소**: `https://github.com/digitaltutor26/stocksinfo`  
> **문서 목적**: 흩어져 있던 기존 개편 설계 내용과 현행 소스코드의 요구사항을 **단일 기준(Single Source of Truth)**으로 통합하여, 설계·구현·검토 단계에서 방향성 충돌이나 해석의 모호함이 발생하지 않도록 정의한다.

---

## 1. 서비스 개요 및 핵심 설계 원칙

- **서비스명**: StocksInfo (중장기 보유 투자자용 신호 기반 모닝 브리핑 서비스)
- **대상 사용자**: 중장기 보유 투자자 (이메일 소비 시간 2~3분, 무료 데이터 소스만 사용)
- **핵심 설계 원칙**:
  1. **일간 시황 노이즈 배제**: 전체 시장 지수의 단순 1일 등락률이나 일반 시황 뉴스 요약은 브리핑에 포함하지 않는다. 오직 **내 관심종목(`watchlist.json`)**의 위치·변화·펀더멘털·일정에만 집중한다.
  2. **4개 정보 축 (Axis A ~ D) 기반 브리핑**:
     - **축 A (위치, Position)**: 종목이 과거 시계열 대비 현재 어디쯤 와 있는가 (52주 밴드 백분위, 200일선 이격도, 52주 고점 대비 낙폭, 3·6·12개월 수익률, 벤치마크 대비 6개월 상대강도)
     - **축 B (변화, Delta)**: 어제/과거 대비 오늘 유의미한 변화(신호)가 발생했는가 (SQLite 일별 스냅샷 비교 및 규칙 엔진 판정)
     - **축 C (펀더멘털, Fundamentals)**: 밸류에이션(PER, PBR), 애널리스트 목표주가·투자의견, 배당수익률·배당락일, 차기 실적발표일
     - **축 D (캘린더, Calendar)**: 관심종목의 실적발표·배당락 일정(D-7 이내) 및 주요 거시 일정
  3. **결정론적 규칙 엔진 우선, LLM은 해석만 담당**:
     - 모든 수치 계산과 신호 판정은 Python 코드(`signals.py`, `report.py`)가 수행한다.
     - LLM(`summarizer/openrouter_client.py`)은 코드가 탐지한 신호와 정량 맥락(`position`, `fundamentals`, `related_news`)을 전달받아 **"왜 중요한가 / 무엇을 확인해야 하는가"**만 해설하며, 새로운 숫자를 창작하거나 단기 매매가(진입가·손절가)를 제시하지 않는다.
     - 탐지된 신호가 **0건**인 날에는 LLM을 호출하지 않고 `"오늘은 관심종목에 특이사항이 없습니다."` 단문 리포트를 발송한다.

---

## 2. 시스템 아키텍처 및 모듈 역할

```
stocksinfo/
├── main.py                        # 파이프라인 오케스트레이션 (수집 → 신호 판정 → 스냅샷 저장 → 맥락 결합 → 리포트 생성 → 발송)
├── config.py                      # 환경변수 로드 및 필수 키 검증 (OPENROUTER_API_KEY, EMAIL_*, FRED_API_KEY)
├── store.py                       # 관심종목(watchlist.json) 및 수신자(recipients.json) JSON 파일 입출력
├── history.py                     # SQLite(stocksinfo.db) 일별 스냅샷(daily_snapshot) 저장 및 시계열 조회
├── signals.py                     # 축 B 규칙 엔진 (위치 및 펀더멘털 기반 이상 신호 6종 판정)
├── report.py                      # 신호등(🔴/🟡/⚪) 헤더, 종목별 위치·밸류에이션 한 줄 요약, 주간 캘린더, 상세 해설 조립
├── collectors/
│   ├── watchlist_stocks.py        # 축 A: 관심종목 2년 시세 기반 위치 지표, 거래량 배수, 상대강도, 종목별 뉴스 수집
│   ├── fundamentals.py            # 축 C: PER/PBR, 배당수익률/배당락일, 목표주가 컨센서스, 차기 실적발표일 수집
│   ├── economic_cal.py            # 축 D: 주간 주요 거시 일정 + FRED API 발표 일정 수집
│   ├── us_market.py               # (보조 모듈) 미국 지수/섹터 ETF 수집 — 메인 브리핑 파이프라인에서는 호출하지 않음
│   ├── kr_market.py               # (보조 모듈) 한국 지수/ETF 수집 — 메인 브리핑 파이프라인에서는 호출하지 않음
│   └── news.py                    # (보조 모듈) 일반 증시 RSS 수집 — 메인 브리핑 파이프라인에서는 호출하지 않음
├── summarizer/
│   └── openrouter_client.py       # OpenRouter 무료 LLM 모델 폴백 체인 기반 신호 해설 생성 (interpret_signals)
├── delivery/
│   └── email_sender.py            # Gmail SMTP 기반 멀티파트(Plain Text + HTML) 이메일 및 에러 알림 발송
├── web/
│   ├── app.py                     # FastAPI 기반 관심종목·수신자 관리, 즉시 발송, GitHub 푸시 대시보드
│   └── templates/index.html       # TailwindCSS 기반 관리 UI 템플릿
└── tests/                         # 단위/통합 테스트 스위트
```

---

## 3. 기능 요구사항 명세 (Functional Requirements)

### FR-01. 데이터 수집 (`collectors/`, `main.collect_all`)
1. **파이프라인 수집 대상 (`main.collect_all`)**
   - 메인 파이프라인은 실제 브리핑 생성(`build_email`)에 사용되는 3개 수집기만 병렬 실행한다:
     - `economic_cal.fetch()` (항상 실행)
     - `watchlist_stocks.fetch(all_symbols)` (`all_symbols`가 비어 있지 않을 때 실행)
     - `fundamentals.fetch(all_symbols)` (`all_symbols`가 비어 있지 않을 때 실행)
   - 브리핑에 사용되지 않는 일반 시황 수집기(`us_market`, `kr_market`, `news`)는 `main.collect_all()`에서 호출하지 않는다.
   - 개별 수집기 예외 및 `economic_cal`의 내부 `errors`는 `results["_errors"]` 리스트에 취합한다.
2. **축 A: 관심종목 위치 지표 수집 (`collectors/watchlist_stocks.py`)**
   - `yfinance`를 통해 종목별 최근 2년(`period="2y"`) 일봉 데이터를 조회하여 다음 지표를 산출한다:
     - 기본 시세: `prev_close`, `last_close`, `change_pct`, `volume`, `news`(종목 뉴스 최대 5건)
     - 52주 위치: `week52_high`, `week52_low`, `week52_pct`(0~100%), `drawdown_from_high_pct`(52주 고점 대비 낙폭 %), `is_new_52w_high`, `is_new_52w_low`
     - 장기 추세: `ma200`, `pct_vs_ma200`(200일선 이격도 %), `ma200_cross`(`"golden"` | `"death"` | `None`), `ma200_cross_months_since_prior`(직전 추세 지속 개월 수)
     - 중장기 수익률 및 상대강도: `return_3m_pct`(63거래일), `return_6m_pct`(126거래일), `return_12m_pct`(252거래일), `relative_strength_6m_pct`(미국 `^GSPC`, 한국 `^KS11` 대비 6개월 초과수익률 %p)
     - 거래량 지표: `volume_avg_20d`, `volume_ratio`(20일 평균 대비 배수)
3. **축 C: 펀더멘털 및 일정 수집 (`collectors/fundamentals.py`)**
   - `yfinance` `Ticker.info` 및 `Ticker.calendar`에서 다음 지표를 수집한다:
     - 밸류에이션·재무: `trailing_pe`, `forward_pe`, `price_to_book`, `dividend_yield`, `debt_to_equity`, `free_cashflow`
     - 컨센서스: `target_mean_price`, `target_high_price`, `target_low_price`, `recommendation`, `num_analyst_opinions`
     - 일정: `next_earnings_date`(YYYY-MM-DD), `ex_dividend_date`(YYYY-MM-DD)

### FR-02. 일별 스냅샷 영속화 (`history.py`)
1. SQLite DB(`stocksinfo.db`)의 `daily_snapshot` 테이블에 `(date, symbol)` 복합 기본키로 일별 데이터를 `UPSERT`한다.
2. 저장 필드: `date`, `symbol`, `last_close`, `trailing_pe`, `target_mean_price`, `volume`
3. 수집 에러(`"error" in pos`)가 발생한 종목은 스냅샷 저장에서 제외한다.

### FR-03. 규칙 기반 신호 탐지 (`signals.py`)
Python 규칙 엔진(`signals.evaluate`)은 종목별로 다음 6가지 조건을 검사하여 신호 리스트(`symbol`, `severity`, `type`, `message`)를 반환한다.
1. **200일선 돌파 (`ma200_cross`)**: 상향 돌파(`golden`) 시 `yellow`, 하향 이탈(`death`) 시 `red` (`ma200_cross_months_since_prior`가 있으면 `(N개월 만)` 병기)
2. **52주 신고가/신저가 (`week52_high` / `week52_low`)**: 신고가 경신 시 `yellow`, 신저가 경신 시 `red`
3. **거래량 급증 (`volume_spike`)**: `volume_ratio >= 2.0` 시 `yellow` (`"거래량 20일 평균 대비 {ratio}배"`)
4. **실적발표 임박 (`earnings_soon`)**: `next_earnings_date`가 오늘 기준 `0 <= days_left <= 7`일 때 `yellow` (`"실적발표 D-{days_left}"`)
5. **PER 자체 밴드 이탈 (`valuation_band`)**: 최근 730일(2년) 내 저장된 `daily_snapshot` 중 유효한 `trailing_pe` 샘플이 최소 20개(`PER_BAND_MIN_SAMPLES = 20`) 이상이고, 당일 `trailing_pe`가 평균 대비 ±1표준편차(`std`)를 벗어날 때 `yellow` (`"PER {trailing_pe:.1f}배 — 자체 밴드 {상단|하단} 이탈 (평균 {mean:.1f}배)"`)
6. **애널리스트 목표주가 주간 변화 (`target_price_change`)**: 오늘로부터 6일 이전(`_days_ago(today, 6)`)의 가장 최근 스냅샷 `target_mean_price` 대비 ±3.0%(`TARGET_PRICE_CHANGE_THRESHOLD_PCT`) 이상 변동 시 `yellow` (`"애널리스트 목표주가 주간 {상향|하향} {abs(change_pct):.1f}%"`)

### FR-04. 신호 맥락 결합, LLM 해설 및 리포트 포맷 (`main.py`, `report.py`, `summarizer/openrouter_client.py`)
1. **신호 0건인 날 (`report.build_no_signal_report`)**:
   - LLM(`interpret_signals`)을 호출하지 않는다.
   - `"📊 {today}   신호 0건"`, `"오늘은 관심종목에 특이사항이 없습니다."`, 정상 범위 종목 나열(`⚪ ...`), 주간 캘린더(`📅 이번 주 ...`), 면책조항만 출력한다.
2. **신호 발생 시 맥락 결합 (`main._enrich_signals` / `_attach_related_news`)**:
   - 신호가 발생한 종목에 대해 LLM이 정확한 숫자를 근거로 해설할 수 있도록 각 신호 객체에 다음 3가지 맥락 정보를 첨부한다:
     - `related_news`: 종목 최신 뉴스 최대 3건
     - `position`: 축 A 핵심 위치 지표 (`last_close`, `week52_pct`, `pct_vs_ma200`, `drawdown_from_high_pct`, `return_3m_pct`, `return_6m_pct`, `return_12m_pct`, `relative_strength_6m_pct`, `volume_ratio`)
     - `fundamentals`: 축 C 핵심 펀더멘털 지표 (`trailing_pe`, `forward_pe`, `price_to_book`, `target_mean_price`, `recommendation`, `next_earnings_date`)
3. **브리핑 헤더 내 위치·밸류에이션 요약 표시 (`report.format_position_summary`, `report.build_header`)**:
   - 신호등 헤더(`🔴 확인 필요`, `🟡 관찰`)에서 각 신호 메시지 하단에 해당 종목의 축 A·축 C 핵심 위치 요약 줄(`    └ 52주 밴드 {week52_pct}% · 200일선 {pct_vs_ma200:+.1f}% · 6M 상대강도 {relative_strength_6m_pct:+.1f}%p · PER {trailing_pe:.1f}배`)을 결정론적으로 함께 출력한다 (존재하는 지표만 출력).

### FR-05. 이메일 발송 및 관리 웹 대시보드 (`delivery/email_sender.py`, `web/app.py`)
1. `recipients.json`의 이메일 목록(없으면 `.env`의 `EMAIL_RECEIVER`)으로 Gmail SMTP를 통해 리포트를 발송한다.
2. FastAPI 웹 대시보드(`web/app.py`)를 통해 미국/한국 관심종목 추가·삭제, 수신자 추가·삭제, 즉시 실행(`/run-now`), GitHub 저장(`/push`) 기능을 제공한다.

---

## 4. 현재 구현 상태 및 미구현 항목 점검

| 요구사항 ID | 항목 | 현재 코드 상태 | 비고 |
|---|---|---|---|
| **FR-01 (축 A/C/D 수집)** | `watchlist_stocks.py`, `fundamentals.py`, `economic_cal.py` | **부분 완료** | 수집기 자체는 구현되었으나, `main.collect_all()`이 미사용 수집기(`us_market`, `kr_market`, `news`)를 여전히 호출 중 |
| **FR-02 (스냅샷 저장)** | `history.py` (`daily_snapshot`) | **구현 완료** | SQLite 저장·조회 정상 동작 |
| **FR-03 (신호 탐지)** | `signals.py` (6종 규칙) | **구현 완료** | 6종 규칙 판정 정상 동작 |
| **FR-04 (맥락 결합 및 리포트 표시)** | `main.py`, `report.py`, `openrouter_client.py` | **미구현 (이번 구현 대상)** | 수집한 축 A(위치)·축 C(펀더멘털) 지표가 LLM 페이로드(`_attach_related_news`)와 리포트 헤더(`report.py`)에 연결되지 않고 누락됨 |
| **FR-05 (발송 및 대시보드)** | `email_sender.py`, `web/app.py` | **구현 완료** | 정상 동작 |
