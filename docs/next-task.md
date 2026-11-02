# 다음 구현 과제 명세서 (`docs/next-task.md`)

> **기준 저장소**: `https://github.com/digitaltutor26/stocksinfo` (커밋 `bad4d1b` 기준)  
> **관련 문서**: 현행 시스템 전체 요구사항 명세는 [`docs/requirements.md`](./requirements.md), 개편 로드맵은 [`REDESIGN.md`](../REDESIGN.md) 참조.

---

## 1. 현행 요구사항 명세 및 현재 상태 요약

별도의 요구사항 명세서가 존재하지 않아 현행 소스코드를 역분석한 결과(상세 내용은 [`docs/requirements.md`](./requirements.md) 참조), 시스템의 현재 구현 상태는 다음과 같습니다.

### 1.1 구현 완료된 기능 (Phase 1 ~ Phase 3)
| 구분 | 모듈 | 현재 구현 상태 |
|---|---|---|
| **축 A (위치 지표)** | `collectors/watchlist_stocks.py` | 2년치 일봉 기반 52주 최고/최저/백분위(`week52_pct`), 고점 대비 낙폭(`drawdown_from_high_pct`), 52주 신고가/신저가 경신 여부, 200일선 이격도 및 골든/데드크로스(`ma200_cross`), 3·6·12개월 수익률, 벤치마크 대비 6개월 상대강도(`relative_strength_6m_pct`), 20일 거래량 배수(`volume_ratio`), 종목 뉴스 수집 완료 |
| **축 B (기억 및 변화 신호)** | `history.py`, `signals.py` | SQLite(`stocksinfo.db`) `daily_snapshot` 테이블에 일별 `(date, symbol, last_close, trailing_pe, target_mean_price, volume)` 저장 완료. 200일선 돌파, 52주 신고가/신저가, 거래량 급증(≥2.0배), 실적발표 임박(D-7), PER 밴드 이탈(±1σ, 최소 20샘플), 목표주가 주간 변화(±3%) 총 6종 규칙 판정 완료 |
| **축 C (펀더멘털)** | `collectors/fundamentals.py` | PER(trailing/forward), PBR, 배당수익률, 배당락일, 부채비율, 잉여현금흐름, 애널리스트 목표주가(평균/상단/하단) 및 차기 실적발표일 수집 완료 |
| **축 D (캘린더 & 리포트)** | `main.py`, `report.py`, `summarizer/openrouter_client.py` | 무신호 시 LLM 호출 생략(`신호 0건` 단문 리포트), 신호 발생 시에만 OpenRouter LLM 해설 호출, 신호등(🔴/🟡/⚪) 레이아웃 및 주간 일정 조립 완료 |
| **관리 웹 대시보드** | `web/app.py`, `web/templates/index.html` | 미국/한국 관심종목 추가·삭제, 이메일 수신자 추가·삭제, 즉시 전송(`/run-now`), GitHub 동기화(`/push`) 구현 완료 |
| **테스트 스위트** | `tests/` | 수집기, 신호 엔진, 히스토리 DB, 리포트, 이메일, 웹 대시보드 단위 테스트 총 58건 통과 중 |

### 1.2 미구현 과제 및 이번 구현 기능 선정
- **선정 기능**: **웹 대시보드 종목별 스냅샷 히스토리 및 최신 지표 요약 뷰 (`REDESIGN.md` Phase 4)**
- **선정 이유**:
  1. `REDESIGN.md`의 로드맵 중 Phase 1~3은 이미 코드에 반영되었으나, **Phase 4("웹 대시보드에 차트·히스토리 뷰")**가 아직 구현되지 않았습니다.
  2. 현재 `stocksinfo.db`(`history.py`)에 매일 종목별 스냅샷이 저장되고 있음에도 웹 대시보드(`web/app.py`)에서는 단순 종목 코드 태그만 보일 뿐, 저장된 최근 종가·PER·목표주가·거래량이나 **PER 밸류에이션 밴드 신호 활성화에 필요한 스냅샷 누적 건수(`PER_BAND_MIN_SAMPLES = 20`)**를 확인할 방법이 없습니다.
  3. 외부 유료 API나 추가 환경변수 없이 기존 `history.py`, `web/app.py`, `web/templates/index.html`만으로 완결성 있게 구현 및 검증할 수 있는 가장 우선순위 높은 기능입니다.

---

## 2. 구현 범위 (Scope)

### 2.1 포함 범위 (In-Scope)
1. **히스토리 요약 및 최근 내역 조회 함수 추가 (`history.py`)**
   - `get_recent_snapshots(symbol: str, limit: int = 30) -> list[dict]`:
     - 특정 종목의 최근 `limit`개 일별 스냅샷을 날짜 내림차순(최신순)으로 반환한다.
   - `get_watchlist_summary(symbols: list[str]) -> list[dict]`:
     - 관심종목 리스트를 받아 각 종목의 **최신 스냅샷 데이터**(`latest_date`, `last_close`, `trailing_pe`, `target_mean_price`, `volume`), **직전 스냅샷 대비 종가 변동률**(`change_pct`), **총 누적 스냅샷 수**(`snapshot_count`), **PER 유효 샘플 수**(`pe_sample_count`)를 계산해 리스트로 반환한다.
     - 스냅샷이 아직 1건도 없는 신규 종목도 누락하지 않고 기본값(`latest_date: None`, `snapshot_count: 0`, `pe_sample_count: 0` 등)으로 포함하여 반환한다.
2. **웹 대시보드 히스토리 연동 및 종목 상세 히스토리 API/뷰 추가 (`web/app.py`)**
   - `GET /` (메인 대시보드):
     - 기존 관심종목(`us_stocks`, `kr_stocks`) 및 수신자 목록 외에 `history.get_watchlist_summary(all_symbols)` 결과를 템플릿 컨텍스트(`stock_summaries`)로 전달한다.
   - `GET /history/{symbol}` (종목별 스냅샷 히스토리 JSON 조회 엔드포인트):
     - 특정 종목(`symbol`)의 최근 스냅샷 내역(`get_recent_snapshots(symbol, limit=30)`)과 요약 정보를 JSON(`{"symbol": symbol, "count": ..., "snapshots": [...]}`)으로 반환한다.
     - 대시보드 UI에서 종목 클릭 시 모달 또는 상세 테이블로 최근 시계열 데이터를 확인하거나 API로 검증할 수 있게 한다.
3. **대시보드 UI에 스냅샷 요약 테이블 및 히스토리 확인 섹션 추가 (`web/templates/index.html`)**
   - 하단에 **"📈 관심종목 스냅샷 히스토리 요약"** 섹션을 추가하여 종목별로 다음 항목을 표시한다:
     - 종목 심볼 (`symbol`)
     - 최근 수집일 (`latest_date` / 데이터 없으면 `"미수집"`)
     - 최근 종가 (`last_close`) 및 직전 스냅샷 대비 등락률 (`change_pct`)
     - Trailing PER (`trailing_pe`) 및 애널리스트 평균 목표주가 (`target_mean_price`)
     - 최근 거래량 (`volume`)
     - PER 밴드 신호 준비 상태 (`pe_sample_count / 20` — 20건 이상이면 `"활성"`, 미만이면 `"수집 중 (N/20)"` 배지 표시)

### 2.2 제외 범위 (Out-of-Scope)
- 데이터 수집기(`collectors/*`)나 신호 판정 규칙(`signals.py`), 이메일 발송(`delivery/*`) 로직 변경은 포함하지 않는다.
- 외부 차트 라이브러리(무거운 프론트엔드 번들) 도입 없이 기존 TailwindCSS 테이블/배지 UI 및 경량 구성을 유지한다.

---

## 3. 수정할 파일 (Files to Modify)

| 파일 경로 | 수정 구분 | 주요 변경 내용 |
|---|---|---|
| `history.py` | 기능 추가 | `get_recent_snapshots(symbol, limit=30)` 및 `get_watchlist_summary(symbols)` 함수 추가 |
| `web/app.py` | 기능 수정/추가 | `GET /` 라우트에 `stock_summaries` 컨텍스트 추가, `GET /history/{symbol}` JSON 엔드포인트 추가 |
| `web/templates/index.html` | UI 수정 | 관심종목별 최신 스냅샷 지표(종가, PER, 목표주가, 거래량, PER 밴드 샘플 진행률) 요약 테이블 렌더링 |
| `tests/test_history.py` | 테스트 추가 | `get_recent_snapshots`, `get_watchlist_summary`의 정상/경계/예외 케이스 단위 테스트 추가 |
| `tests/web/test_app.py` | 테스트 추가 | 대시보드 스냅샷 요약 렌더링 및 `/history/{symbol}` 엔드포인트 정상/예외 케이스 통합 테스트 추가 |

---

## 4. 완료 조건 (Definition of Done)

1. `history.get_recent_snapshots(symbol, limit)` 호출 시 해당 종목의 스냅샷이 최신 날짜순(`date DESC`)으로 최대 `limit`건 반환되어야 한다.
2. `history.get_watchlist_summary(symbols)` 호출 시 전달된 `symbols` 순서를 유지하며 각 종목의 `symbol`, `latest_date`, `last_close`, `change_pct`, `trailing_pe`, `target_mean_price`, `volume`, `snapshot_count`, `pe_sample_count` 키를 포함한 딕셔너리 리스트를 반환해야 한다.
3. 스냅샷이 2건 이상 존재하고 `last_close`가 유효한 경우, 최신 스냅샷과 직전 스냅샷 간 종가 등락률(`change_pct`, 소수점 둘째 자리 반올림)이 정확히 계산되어야 한다.
4. `GET /` 요청 시 응답 HTML에 등록된 관심종목의 최신 스냅샷 요약 정보(종가, PER, 목표주가, 스냅샷 누적 상태 또는 데이터 없을 시 `"미수집"` 안내)가 정상 렌더링되어야 한다.
5. `GET /history/{symbol}` 요청 시 HTTP 200과 함께 `{"symbol": ..., "count": ..., "snapshots": [...]}` 구조의 JSON을 반환해야 한다.
6. 기존 58개 테스트 케이스와 신규 추가된 테스트 케이스가 `python -m pytest tests/ -q` 실행 시 모두 통과(Pass)해야 한다.

---

## 5. 테스트할 정상 상황과 예외 상황

### 5.1 정상 상황 (Normal Cases)
1. **다수 일자 스냅샷이 축적된 종목의 요약 조회 (`test_get_watchlist_summary_with_history`)**
   - **Given**: `NVDA`에 대해 `2026-08-01`(종가 100.0, PER 30.0)과 `2026-08-02`(종가 105.0, PER 31.5, 목표주가 140.0, 거래량 50000) 스냅샷 2건이 저장되어 있음.
   - **When**: `history.get_watchlist_summary(["NVDA"])` 호출.
   - **Then**: `latest_date == "2026-08-02"`, `last_close == 105.0`, `change_pct == 5.0`, `trailing_pe == 31.5`, `target_mean_price == 140.0`, `snapshot_count == 2`, `pe_sample_count == 2`가 반환됨.
2. **최근 스냅샷 `limit` 제한 및 정렬 확인 (`test_get_recent_snapshots_respects_limit_and_desc_order`)**
   - **Given**: 특정 종목에 5일치 스냅샷(`2026-08-01` ~ `2026-08-05`)이 저장되어 있음.
   - **When**: `history.get_recent_snapshots("NVDA", limit=3)` 호출.
   - **Then**: 가장 최근 3일(`["2026-08-05", "2026-08-04", "2026-08-03"]`) 순서로 3건만 반환됨.
3. **웹 대시보드 메인 화면에 스냅샷 요약 표시 (`test_dashboard_renders_snapshot_summary`)**
   - **Given**: `watchlist.json`에 `NVDA`가 등록되어 있고, DB에 `NVDA` 스냅샷(종가 `123.45`, PER `35.2`)이 저장되어 있음.
   - **When**: `GET /` 요청.
   - **Then**: HTTP 200 응답 본문에 `123.45`, `35.2`, 수집 상태(`1/20`)가 포함되어 렌더링됨.
4. **종목별 히스토리 API 조회 (`test_history_endpoint_returns_snapshots`)**
   - **Given**: DB에 `AAPL` 스냅샷 2건이 저장되어 있음.
   - **When**: `GET /history/aapl` (소문자 입력 포함) 요청.
   - **Then**: 대문자로 정규화된 `"symbol": "AAPL"`, `"count": 2`, `"snapshots"` 배열(길이 2)이 JSON으로 반환됨.

### 5.2 예외 및 경계 상황 (Exception & Edge Cases)
1. **스냅샷이 전혀 없는 신규 등록 종목 (`test_get_watchlist_summary_for_symbol_without_snapshots`)**
   - **Given**: 관심종목에 `MSFT`를 방금 추가하여 `daily_snapshot` 테이블에 레코드가 0건임.
   - **When**: `history.get_watchlist_summary(["MSFT"])` 및 `GET /` 호출.
   - **Then**: 에러 없이 `latest_date: None`, `last_close: None`, `change_pct: None`, `snapshot_count: 0`, `pe_sample_count: 0`을 반환하고, 대시보드 HTML에는 `"미수집"`(또는 `-`)으로 안전하게 표시됨.
2. **스냅샷이 1건뿐이거나 직전 종가가 `None`/`0`인 경우 (`test_get_watchlist_summary_single_snapshot_or_null_close`)**
   - **Given**: 스냅샷이 1건만 존재하거나, 직전 스냅샷의 `last_close`가 `None` 또는 `0`임 (`ZeroDivisionError` 위험).
   - **When**: `history.get_watchlist_summary(["NVDA"])` 호출.
   - **Then**: `ZeroDivisionError`나 `TypeError`가 발생하지 않고 `change_pct`가 `None`으로 반환됨.
3. **일부 컬럼(`trailing_pe`, `target_mean_price`)이 `None`인 스냅샷 (ETF 또는 적자 기업) (`test_pe_sample_count_excludes_null_pe`)**
   - **Given**: 5건의 스냅샷 중 3건만 `trailing_pe`가 숫자로 존재하고 2건은 `None`임.
   - **When**: `history.get_watchlist_summary(["069500.KS"])` 호출.
   - **Then**: `snapshot_count == 5`이고, `pe_sample_count == 3`으로 정확히 집계됨.
4. **빈 관심종목 리스트 전달 (`test_get_watchlist_summary_empty_list`)**
   - **Given**: 미국/한국 관심종목이 모두 비어 있음(`symbols = []`).
   - **When**: `history.get_watchlist_summary([])` 호출.
   - **Then**: DB 오류 없이 빈 리스트 `[]`를 반환함.
5. **존재하지 않는 종목에 대한 `/history/{symbol}` 호출 (`test_history_endpoint_unknown_symbol`)**
   - **Given**: DB에 기록이 없는 `UNKNOWN` 종목 조회.
   - **When**: `GET /history/UNKNOWN` 요청.
   - **Then**: 500 에러가 아닌 HTTP 200과 `{"symbol": "UNKNOWN", "count": 0, "snapshots": []}`를 반환함.
6. **잘못된 `limit` 파라미터 방어 (`test_get_recent_snapshots_invalid_limit`)**
   - **Given**: `limit <= 0`으로 `get_recent_snapshots("NVDA", limit=0)` 호출.
   - **When**: 함수 실행.
   - **Then**: 빈 리스트 `[]`를 반환하며 예외가 발생하지 않음.
