from __future__ import annotations

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

import history
import report
import signals as signal_engine
from collectors import economic_cal, fundamentals
from collectors import watchlist_stocks
from delivery.email_sender import send, send_error
from store import load_recipients, load_watchlist
from summarizer.openrouter_client import interpret_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]
CALENDAR_LOOKAHEAD_DAYS = 7
POSITION_CONTEXT_KEYS = (
    "last_close", "week52_pct", "pct_vs_ma200", "drawdown_from_high_pct",
    "return_3m_pct", "return_6m_pct", "return_12m_pct",
    "relative_strength_6m_pct", "volume_ratio",
)
FUNDAMENTAL_CONTEXT_KEYS = (
    "trailing_pe", "forward_pe", "price_to_book", "target_mean_price",
    "recommendation", "next_earnings_date",
)


def collect_all(all_symbols: list) -> dict:
    collectors = {
        "economic_cal": economic_cal.fetch,
    }

    results = {}
    errors = []

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fn): name for name, fn in collectors.items()}
        if all_symbols:
            futures[pool.submit(watchlist_stocks.fetch, all_symbols)] = "watchlist"
            futures[pool.submit(fundamentals.fetch, all_symbols)] = "fundamentals"

        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result(timeout=30)
                log.info(f"[OK] {name}")
            except Exception as e:
                log.error(f"[FAIL] {name}: {e}")
                errors.append(f"{name}: {e}")
                results[name] = None

    collector_result = results.get("economic_cal")
    if isinstance(collector_result, dict):
        errors.extend(collector_result.get("errors", []))

    results["_errors"] = errors
    results["_collected_at"] = datetime.utcnow().isoformat()
    return results


def _weekday_kr(d: date) -> str:
    return WEEKDAY_KR[d.weekday()]


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def _ticker_calendar_events(fundamentals_data: dict, today: date) -> list:
    events = []
    for symbol, fund in (fundamentals_data or {}).items():
        if not fund or "error" in fund:
            continue

        edate = _parse_date(fund.get("next_earnings_date"))
        if edate and 0 <= (edate - today).days <= CALENDAR_LOOKAHEAD_DAYS:
            events.append(f"{symbol} 실적({_weekday_kr(edate)})")

        exdiv = _parse_date(fund.get("ex_dividend_date"))
        if exdiv and 0 <= (exdiv - today).days <= CALENDAR_LOOKAHEAD_DAYS:
            events.append(f"{symbol} 배당락({_weekday_kr(exdiv)})")

    return events


def _save_snapshots(watchlist: dict, fundamentals_data: dict, today_str: str):
    for symbol, pos in (watchlist or {}).items():
        if not pos or "error" in pos:
            continue
        fund = (fundamentals_data or {}).get(symbol) or {}
        history.save_snapshot(today_str, symbol, {
            "last_close": pos.get("last_close"),
            "trailing_pe": fund.get("trailing_pe"),
            "target_mean_price": fund.get("target_mean_price"),
            "volume": pos.get("volume"),
        })


def _attach_related_news(
    detected_signals: list,
    watchlist: dict,
    fundamentals_data: dict | None = None,
) -> list:
    enriched = []
    for sig in detected_signals:
        pos = (watchlist or {}).get(sig["symbol"]) or {}
        if "error" in pos:
            pos = {}
        fund = (fundamentals_data or {}).get(sig["symbol"]) or {}
        if "error" in fund:
            fund = {}
        enriched.append({
            **sig,
            "related_news": (pos.get("news") or [])[:3],
            "position": {k: pos.get(k) for k in POSITION_CONTEXT_KEYS if pos.get(k) is not None},
            "fundamentals": {k: fund.get(k) for k in FUNDAMENTAL_CONTEXT_KEYS if fund.get(k) is not None},
        })
    return enriched


def build_email(watchlist: dict, fundamentals_data: dict, econ_cal: dict) -> str:
    today = date.today()
    today_str = today.isoformat()

    detected_signals = signal_engine.evaluate(watchlist, fundamentals_data, today_str)
    _save_snapshots(watchlist, fundamentals_data, today_str)

    watchlist_symbols = list((watchlist or {}).keys())
    calendar_events = _ticker_calendar_events(fundamentals_data, today)
    calendar_events += [ev["name"] for ev in (econ_cal or {}).get("events", []) if ev.get("name")]

    if not detected_signals:
        return report.build_no_signal_report(watchlist_symbols, today_str, calendar_events)

    enriched_signals = _attach_related_news(detected_signals, watchlist, fundamentals_data)
    try:
        detail_text = interpret_signals(enriched_signals)
    except Exception:
        log.warning("AI interpretation failed; sending deterministic report", exc_info=True)
        detail_text = "AI 해설을 일시적으로 제공하지 못했습니다. 리포트의 신호와 수치는 규칙 엔진이 생성한 결과입니다."
    return report.build_report(
        detected_signals, watchlist_symbols, today_str, calendar_events, detail_text,
        watchlist=watchlist, fundamentals=fundamentals_data,
    )


def main():
    from config import validate
    validate()
    log.info("StocksInfo morning report starting...")
    try:
        wl = load_watchlist()
        all_symbols = wl.get("us", []) + wl.get("kr", [])

        data = collect_all(all_symbols)

        if data.get("_errors"):
            log.warning(f"Partial data — errors: {data['_errors']}")

        email_body = build_email(
            data.get("watchlist") or {},
            data.get("fundamentals") or {},
            data.get("economic_cal") or {},
        )

        # 수신자 목록에서 발송 (없으면 .env의 EMAIL_RECEIVER로 fallback)
        recipients = load_recipients()
        emails = recipients.get("emails", [])
        if not emails:
            from config import EMAIL_RECEIVER
            emails = [EMAIL_RECEIVER]

        for email in emails:
            send(email_body, to=email)
            log.info(f"Delivered to {email}")

    except Exception:
        err = traceback.format_exc()
        log.error(f"Fatal error:\n{err}")
        try:
            send_error(err)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
