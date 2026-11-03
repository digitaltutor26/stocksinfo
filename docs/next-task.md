# 다음 구현 과제 명세서 (`docs/next-task.md`)

> **기준 문서**: [`docs/requirements.md`](./requirements.md) (FR-01, FR-04 미구현 구간 해소)  
> **구현 담당자(Codex) 안내**: 본 문서는 단일 구현 기준입니다. 아래 정의된 함수 시그니처, 딕셔너리 키 이름, 문자열 포맷, 완료 조건 및 테스트 케이스를 그대로 준수하여 구현하고, 구현 완료 후 결과를 `docs/implementation-result.md`에 기록하세요.

---

## 1. 선정 기능 및 배경

- **선정 기능**: **축 A(위치)·축 C(펀더멘털) 핵심 지표의 신호/리포트/LLM 페이로드 연결 및 미사용 시황 수집기 파이프라인 정리**
- **현재 상태 및 문제점**:
  1. `collectors/watchlist_stocks.py`(축 A)와 `collectors/fundamentals.py`(축 C)에서 52주 밴드 백분위(`week52_pct`), 200일선 이격도(`pct_vs_ma200`), 52주 고점 대비 낙폭(`drawdown_from_high_pct`), 3·6·12개월 수익률, 벤치마크 대비 6개월 상대강도(`relative_strength_6m_pct`), PER(`trailing_pe`), PBR(`price_to_book`), 목표주가(`target_mean_price`) 등을 이미 수집하고 있습니다.
  2. 그러나 `main.py`의 `_attach_related_news()`는 LLM(`interpret_signals`)에 `{"symbol", "severity", "type", "message", "related_news"}`만 전달하고 **수집된 위치·펀더멘털 데이터를 전부 누락**하고 있으며, `report.py`의 신호등 헤더에서도 해당 종목의 위치·밸류에이션 요약이 전혀 표시되지 않습니다.
  3. 또한 `main.collect_all()`이 이메일 리포트(`build_email`)에서 전혀 쓰이지 않는 `us_market`, `kr_market`, `news` 수집기를 매번 호출하여 불필요한 네트워크 대기와 에러 노이즈를 발생시키고 있습니다.

---

## 2. 구현 범위 (Scope)

### 2.1 `main.py` 수정 범위
1. **`collect_all(all_symbols: list) -> dict` 미사용 수집기 호출 제거**
   - `collect_all`에서 실제 브리핑(`build_email`)에 쓰이지 않는 `us_market.fetch`, `kr_market.fetch`, `news.fetch` 호출을 제거한다.
   - `economic_cal.fetch`는 항상 실행하고, `all_symbols`가 비어 있지 않을 때 `watchlist_stocks.fetch(all_symbols)`(`"watchlist"`)와 `fundamentals.fetch(all_symbols)`(`"fundamentals"`)를 실행한다.
   - `economic_cal` 결과(`dict`) 내부의 `"errors"` 리스트는 기존과 동일하게 `results["_errors"]`에 병합한다.
   - *(주의: `collectors/us_market.py`, `collectors/kr_market.py`, `collectors/news.py` 파일 자체와 해당 단위 테스트 파일은 삭제하지 않는다.)*
2. **신호 객체에 축 A(위치)·축 C(펀더멘털) 컨텍스트 첨부 (`_attach_related_news`)**
   - 시그니처:
     ```python
     def _attach_related_news(
         detected_signals: list,
         watchlist: dict,
         fundamentals_data: dict | None = None,
     ) -> list:
     ```
     *(기존 2개 인자 호출 `_attach_related_news(detected_signals, watchlist)`과도 하위 호환되도록 `fundamentals_data: dict | None = None` 기본값을 둔다.)*
   - 추출할 키 상수 정의:
     ```python
     POSITION_CONTEXT_KEYS = (
         "last_close",
         "week52_pct",
         "pct_vs_ma200",
         "drawdown_from_high_pct",
         "return_3m_pct",
         "return_6m_pct",
         "return_12m_pct",
         "relative_strength_6m_pct",
         "volume_ratio",
     )
     FUNDAMENTAL_CONTEXT_KEYS = (
         "trailing_pe",
         "forward_pe",
         "price_to_book",
         "target_mean_price",
         "recommendation",
         "next_earnings_date",
     )
     ```
   - 각 신호 `sig`에 대해:
     - `pos = (watchlist or {}).get(sig["symbol"]) or {}` (단, `"error" in pos`이면 빈 딕셔너리 `{}`로 취급)
     - `fund = (fundamentals_data or {}).get(sig["symbol"]) or {}` (단, `"error" in fund`이면 빈 딕셔너리 `{}`로 취급)
     - 반환되는 각 신호 dict에 다음 3개 필드를 포함시킨다:
       - `"related_news": (pos.get("news") or [])[:3]`
       - `"position": {k: pos.get(k) for k in POSITION_CONTEXT_KEYS if pos.get(k) is not None}`
       - `"fundamentals": {k: fund.get(k) for k in FUNDAMENTAL_CONTEXT_KEYS if fund.get(k) is not None}`
3. **`build_email(watchlist: dict, fundamentals_data: dict, econ_cal: dict) -> str` 연결**
   - `enriched_signals = _attach_related_news(detected_signals, watchlist, fundamentals_data)`로 호출한다.
   - `report.build_report(detected_signals, watchlist_symbols, today_str, calendar_events, detail_text, watchlist=watchlist, fundamentals=fundamentals_data)`로 `watchlist`와 `fundamentals_data`를 전달한다.

### 2.2 `report.py` 수정 범위
1. **종목별 위치·밸류에이션 한 줄 요약 포맷터 추가 (`format_position_summary`)**
   - 시그니처:
     ```python
     def format_position_summary(pos: dict | None, fund: dict | None = None) -> str:
     ```
   - 동작 규칙:
     - `pos`가 `None`이거나 `"error" in pos`이면 빈 딕셔너리 `{}`로 처리하고, `fund`가 `None`이거나 `"error" in fund`이면 빈 딕셔너리 `{}`로 처리한다.
     - 아래 순서대로 값이 `None`이 아닌 항목만 리스트에 담아 `" · "`로 연결하여 반환한다 (모든 항목이 `None`이면 `""` 반환):
       1. `pos.get("week52_pct") is not None` → `f"52주 밴드 {pos['week52_pct']:.1f}%"`
       2. `pos.get("pct_vs_ma200") is not None` → `f"200일선 {pos['pct_vs_ma200']:+.1f}%"`
       3. `pos.get("relative_strength_6m_pct") is not None` → `f"6M 상대강도 {pos['relative_strength_6m_pct']:+.1f}%p"`
       4. `fund.get("trailing_pe") is not None` → `f"PER {fund['trailing_pe']:.1f}배"`
     - 출력 예시: `"52주 밴드 88.0% · 200일선 +14.2% · 6M 상대강도 +9.1%p · PER 28.5배"`
2. **`build_header` 및 `build_report`에서 위치·밸류에이션 요약 줄 출력**
   - 시그니처 (기존 호출과 100% 하위 호환 유지):
     ```python
     def build_header(
         signals: list[dict],
         watchlist_symbols: list[str],
         today: str,
         watchlist: dict | None = None,
         fundamentals: dict | None = None,
     ) -> str:
     ```
     ```python
     def build_report(
         signals: list[dict],
         watchlist_symbols: list[str],
         today: str,
         calendar_events: list[str],
         detail_text: str = "",
         watchlist: dict | None = None,
         fundamentals: dict | None = None,
     ) -> str:
     ```
   - `build_header`에서 `🔴 확인 필요` 및 `🟡 관찰`의 각 신호 줄(`  {s['symbol']:<8}{s['message']}`)을 출력한 직후, `watchlist` 또는 `fundamentals`에 해당 종목 데이터가 존재하여 `summary = format_position_summary((watchlist or {}).get(s["symbol"]), (fundamentals or {}).get(s["symbol"]))`가 빈 문자열이 아니면 바로 다음 줄에 아래 형식으로 추가한다:
     ```
         └ 52주 밴드 88.0% · 200일선 +14.2% · 6M 상대강도 +9.1%p · PER 28.5배
     ```
     *(앞 공백 4칸 + `└ ` + `summary`)*
   - `watchlist`와 `fundamentals`가 모두 `None`(또는 빈 dict)으로 호출된 경우에는 기존 출력과 완전히 동일해야 한다.

### 2.3 `summarizer/openrouter_client.py` 수정 범위
- `SYSTEM_PROMPT`의 규칙 목록에 다음 지침을 반영한다:
  - 전달된 신호 데이터의 `position`(52주 밴드 백분위, 200일선 이격도, 고점 대비 낙폭, 수익률, 6개월 상대강도 등) 및 `fundamentals`(PER, PBR, 목표주가 등)에 포함된 수치를 적극 인용하여 해당 신호의 중장기적 맥락을 설명하되, 데이터에 없는 숫자는 절대 계산하거나 지어내지 않는다.

---

## 3. 수정할 파일 (Files to Modify)

| 파일 경로 | 수정 구분 | 주요 변경 내용 |
|---|---|---|
| `main.py` | 수정 | `collect_all`에서 미사용 수집기(`us_market`, `kr_market`, `news`) 호출 제거, `_attach_related_news`에 `position`·`fundamentals` 컨텍스트 추가, `build_email`에서 `report.build_report`로 `watchlist`·`fundamentals_data` 전달 |
| `report.py` | 수정 | `format_position_summary(pos, fund)` 추가, `build_header` 및 `build_report`에 선택 인자 `watchlist`, `fundamentals` 추가 및 `    └ {summary}` 라인 렌더링 |
| `summarizer/openrouter_client.py` | 수정 | `SYSTEM_PROMPT`에 `position` 및 `fundamentals` 컨텍스트 인용 규칙 명시 |
| `tests/test_main.py` | 수정/추가 | `collect_all` 테스트를 정리된 수집기 기준에 맞게 갱신하고, LLM 페이로드에 `position`·`fundamentals`가 포함되는지 및 에러 종목 방어 테스트 추가 |
| `tests/test_report.py` | 추가 | `format_position_summary` 단위 테스트 및 `build_header`/`build_report`의 위치 요약 줄 포함·생략 테스트 추가 |
| `docs/implementation-result.md` | 신규 생성 | 구현 완료 후 변경 파일, 구현 내용 요약, `pytest` 실행 결과를 정리하여 작성 |

---

## 4. 완료 조건 (Definition of Done)

1. `main.collect_all(all_symbols)` 호출 시 `us_market.fetch`, `kr_market.fetch`, `news.fetch`가 호출되지 않고, `economic_cal.fetch`와 (`all_symbols` 존재 시) `watchlist_stocks.fetch`, `fundamentals.fetch`만 실행되어야 한다.
2. `main._attach_related_news(detected_signals, watchlist, fundamentals_data)` 호출 결과 각 신호 딕셔너리에 `"related_news"`, `"position"`, `"fundamentals"` 키가 포함되어야 하며, 값이 `None`인 세부 지표는 `"position"` / `"fundamentals"` 딕셔너리에서 제외되어야 한다.
3. `report.format_position_summary(pos, fund)`가 `week52_pct`, `pct_vs_ma200`, `relative_strength_6m_pct`, `trailing_pe` 중 존재하는 값만 `" · "`로 연결한 문자열을 반환해야 한다.
4. `report.build_header` 및 `report.build_report` 호출 시 `watchlist`·`fundamentals`가 주어지면 신호 줄 아래에 `    └ ...` 요약 줄이 출력되고, 주어지지 않으면(`None` 또는 유효 지표 없음) 기존과 동일하게 요약 줄 없이 출력되어야 한다.
5. `python -m pytest tests/ -q` 실행 시 전체 테스트 스위트가 실패 없이 100% 통과해야 한다.
6. 구현 결과 보고서가 `docs/implementation-result.md`에 작성되어야 한다.

---

## 5. 테스트할 정상 상황과 예외 상황

### 5.1 정상 상황 (Normal Cases)
1. **신호 발생 시 LLM 페이로드에 `position` 및 `fundamentals` 컨텍스트 첨부 확인 (`test_build_email_attaches_position_and_fundamentals_to_llm_payload`)**
   - **Given**: `NVDA`에 200일선 상향 돌파 신호가 발생하고, `watchlist["NVDA"]`에 `week52_pct=88.0`, `pct_vs_ma200=14.2`, `relative_strength_6m_pct=9.1`이 있으며, `fundamentals["NVDA"]`에 `trailing_pe=28.5`, `target_mean_price=150.0`이 있음.
   - **When**: `main.build_email(watchlist, fundamentals, {})` 실행.
   - **Then**: `interpret_signals`에 전달된 첫 번째 신호 객체의 `sig["position"]`에 `week52_pct == 88.0`, `pct_vs_ma200 == 14.2`, `relative_strength_6m_pct == 9.1`이 포함되고, `sig["fundamentals"]`에 `trailing_pe == 28.5`, `target_mean_price == 150.0`이 포함됨.
2. **브리핑 리포트 헤더에 위치·밸류에이션 한 줄 요약 렌더링 확인 (`test_build_report_includes_position_summary_line`)**
   - **Given**: `NVDA` 신호 1건과 `watchlist={"NVDA": {"week52_pct": 88.0, "pct_vs_ma200": 14.2, "relative_strength_6m_pct": -3.5}}`, `fundamentals={"NVDA": {"trailing_pe": 28.5}}`가 주어짐.
   - **When**: `report.build_report(signals, ["NVDA"], "2026-08-02", [], detail_text="해설", watchlist=watchlist, fundamentals=fundamentals)` 호출.
   - **Then**: 반환된 리포트 문자열에 `"    └ 52주 밴드 88.0% · 200일선 +14.2% · 6M 상대강도 -3.5%p · PER 28.5배"`가 포함됨.
3. **`collect_all`이 필요한 수집기만 실행하는지 확인 (`test_collect_all_runs_only_active_collectors`)**
   - **Given**: `all_symbols = ["NVDA"]`.
   - **When**: `main.collect_all(["NVDA"])` 호출.
   - **Then**: `watchlist`, `fundamentals`, `economic_cal` 결과만 수집되고 `us_market`, `kr_market`, `news` 키는 결과에 존재하지 않음.
4. **`format_position_summary`의 전체 지표 포맷팅 확인 (`test_format_position_summary_all_fields`)**
   - **Given**: `pos = {"week52_pct": 22.5, "pct_vs_ma200": -12.34, "relative_strength_6m_pct": 4.56}`, `fund = {"trailing_pe": 19.84}`.
   - **When**: `report.format_position_summary(pos, fund)` 호출.
   - **Then**: `"52주 밴드 22.5% · 200일선 -12.3% · 6M 상대강도 +4.6%p · PER 19.8배"` 반환.

### 5.2 예외 및 경계 상황 (Exception & Edge Cases)
1. **일부 지표가 `None`인 경우(상장 200일 미만 종목 또는 적자 기업으로 PER `None`) (`test_format_position_summary_omits_none_fields`)**
   - **Given**: `pos = {"week52_pct": 50.0, "pct_vs_ma200": None, "relative_strength_6m_pct": None}`, `fund = {"trailing_pe": None}`.
   - **When**: `report.format_position_summary(pos, fund)` 호출.
   - **Then**: `None`인 항목은 건너뛰고 `"52주 밴드 50.0%"`만 반환하며 `TypeError`가 발생하지 않음.
2. **위치·펀더멘털 데이터가 모두 비어 있거나 `"error"`가 있는 경우 (`test_format_position_summary_returns_empty_on_error_or_empty`)**
   - **Given**: `pos = {"error": "timeout"}` 또는 `pos = {}`, `fund = {"error": "404"}`.
   - **When**: `report.format_position_summary(pos, fund)` 및 `report.build_header(signals, ["NVDA"], "2026-08-02", watchlist={"NVDA": pos}, fundamentals={"NVDA": fund})` 호출.
   - **Then**: `format_position_summary`는 `""`를 반환하고, `build_header` 출력에 빈 `"└"` 줄이 찍히지 않음.
3. **펀더멘털 수집에 실패(`{"error": "boom"}`)한 종목에서 위치 신호가 발생한 경우 (`test_attach_related_news_handles_errored_fundamentals`)**
   - **Given**: `watchlist["NVDA"]`는 정상이어서 `ma200_cross` 신호가 발생했으나, `fundamentals["NVDA"] = {"error": "boom"}`인 상태.
   - **When**: `main._attach_related_news(signals, watchlist, fundamentals)` 호출.
   - **Then**: 예외 없이 `sig["position"]`은 정상 채워지고, `sig["fundamentals"]`는 빈 딕셔너리 `{}`가 됨.
4. **`collect_all`에서 `economic_cal` 내부 에러 및 수집기 예외 처리 (`test_collect_all_merges_economic_cal_errors_and_handles_exception`)**
   - **Given**: `economic_cal.fetch`가 `{"events": [], "errors": ["FRED: 400"]}`를 반환하거나, `watchlist_stocks.fetch`에서 예외가 발생함.
   - **When**: `main.collect_all(["NVDA"])` 호출.
   - **Then**: `result["_errors"]`에 `"FRED: 400"` 및 `"watchlist: ..."` 에러 메시지가 정상 기록되고 프로세스가 중단되지 않음.
5. **관심종목이 비어 있을 때(`all_symbols = []`) `collect_all` 동작 (`test_collect_all_with_empty_symbols`)**
   - **Given**: `all_symbols = []`.
   - **When**: `main.collect_all([])` 호출.
   - **Then**: `watchlist_stocks.fetch`와 `fundamentals.fetch`는 호출되지 않고 `economic_cal.fetch`만 실행됨.
