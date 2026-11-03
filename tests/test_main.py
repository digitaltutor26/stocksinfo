import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr("history.DB_FILE", tmp_path / "test.db")


def _pos(**overrides):
    base = {
        "last_close": 100.0, "volume": 1_000_000, "news": [],
        "ma200_cross": None, "ma200_cross_months_since_prior": None,
        "is_new_52w_high": False, "is_new_52w_low": False,
        "volume_ratio": 1.0,
    }
    base.update(overrides)
    return base


def test_build_email_no_signals_skips_llm():
    import main

    watchlist = {"NVDA": _pos()}
    with patch("main.interpret_signals") as mock_interpret:
        body = main.build_email(watchlist, {}, {})

    mock_interpret.assert_not_called()
    assert "신호 0건" in body


def test_build_email_with_signal_calls_llm_and_saves_snapshot():
    import main
    import history

    watchlist = {"NVDA": _pos(ma200_cross="golden", ma200_cross_months_since_prior=2.0)}
    fundamentals = {"NVDA": {"trailing_pe": 30.0, "target_mean_price": 150.0}}

    with patch("main.interpret_signals", return_value="해설") as mock_interpret:
        body = main.build_email(watchlist, fundamentals, {})

    mock_interpret.assert_called_once()
    assert "200일선 상향 돌파" in body
    assert "해설" in body

    snap = history.get_snapshot("NVDA", __import__("datetime").date.today().isoformat())
    assert snap["last_close"] == 100.0
    assert snap["trailing_pe"] == 30.0


def test_build_email_attaches_related_news_to_llm_payload():
    import main

    watchlist = {"NVDA": _pos(
        ma200_cross="golden", ma200_cross_months_since_prior=1.0,
        news=[{"title": "NVDA rallies", "url": "http://test.com"}],
    )}

    captured = {}

    def fake_interpret(signals):
        captured["signals"] = signals
        return "해설"

    with patch("main.interpret_signals", side_effect=fake_interpret):
        main.build_email(watchlist, {}, {})

    assert captured["signals"][0]["related_news"][0]["title"] == "NVDA rallies"


def test_build_email_skips_errored_watchlist_symbols_in_snapshot():
    import main
    import history

    watchlist = {"NVDA": {"error": "boom"}}
    with patch("main.interpret_signals"):
        main.build_email(watchlist, {}, {})

    today_str = __import__("datetime").date.today().isoformat()
    assert history.get_snapshot("NVDA", today_str) is None


def test_ticker_calendar_events_within_lookahead():
    import main
    from datetime import date, timedelta

    today = date(2026, 8, 2)  # Sunday
    soon = (today + timedelta(days=3)).isoformat()
    far = (today + timedelta(days=30)).isoformat()

    fundamentals = {
        "NVDA": {"next_earnings_date": soon, "ex_dividend_date": None},
        "AAPL": {"next_earnings_date": far, "ex_dividend_date": None},
    }
    events = main._ticker_calendar_events(fundamentals, today)
    assert any("NVDA 실적" in e for e in events)
    assert not any("AAPL" in e for e in events)


def test_ticker_calendar_events_skips_errored_symbols():
    import main
    from datetime import date

    events = main._ticker_calendar_events({"NVDA": {"error": "boom"}}, date(2026, 8, 2))
    assert events == []


def test_collect_all_runs_only_active_collectors():
    import main
    from collectors import us_market, kr_market, news

    with patch.object(us_market, "fetch") as us, \
         patch.object(kr_market, "fetch") as kr, \
         patch.object(news, "fetch") as general_news, \
         patch("main.economic_cal.fetch", return_value={}) as econ, \
         patch("main.watchlist_stocks.fetch", return_value={"NVDA": {}}) as positions, \
         patch("main.fundamentals.fetch", return_value={}) as funds:
        result = main.collect_all(["NVDA"])
    assert set(result) == {"watchlist", "fundamentals", "economic_cal", "_errors", "_collected_at"}
    assert result["watchlist"] == {"NVDA": {}}
    assert result["_errors"] == []
    econ.assert_called_once_with()
    positions.assert_called_once_with(["NVDA"])
    funds.assert_called_once_with(["NVDA"])
    for unused in (us, kr, general_news):
        unused.assert_not_called()


def test_collect_all_with_empty_symbols():
    import main
    with patch("main.economic_cal.fetch", return_value={}) as econ, \
         patch("main.watchlist_stocks.fetch") as positions, \
         patch("main.fundamentals.fetch") as funds:
        result = main.collect_all([])
    econ.assert_called_once_with()
    positions.assert_not_called()
    funds.assert_not_called()
    assert set(result) == {"economic_cal", "_errors", "_collected_at"}


def test_collect_all_merges_economic_cal_errors_and_handles_exception():
    import main
    with patch("main.economic_cal.fetch", return_value={"events": [], "errors": ["FRED: 400"]}), \
         patch("main.watchlist_stocks.fetch", side_effect=RuntimeError("boom")), \
         patch("main.fundamentals.fetch", return_value={}):
        result = main.collect_all(["NVDA"])
    assert set(result["_errors"]) == {"FRED: 400", "watchlist: boom"}
    assert result["watchlist"] is None


def test_build_email_attaches_position_and_fundamentals_to_llm_payload():
    import main
    watchlist = {"NVDA": _pos(ma200_cross="golden", week52_pct=88.0,
                              pct_vs_ma200=14.2, relative_strength_6m_pct=9.1)}
    funds = {"NVDA": {"trailing_pe": 28.5, "target_mean_price": 150.0}}
    with patch("main.interpret_signals", return_value="해설") as interpret:
        body = main.build_email(watchlist, funds, {})
    sig = interpret.call_args.args[0][0]
    assert sig["position"]["week52_pct"] == 88.0
    assert sig["position"]["pct_vs_ma200"] == 14.2
    assert sig["position"]["relative_strength_6m_pct"] == 9.1
    assert sig["fundamentals"] == funds["NVDA"]
    assert "    └ 52주 밴드 88.0% · 200일선 +14.2% · 6M 상대강도 +9.1%p · PER 28.5배" in body


def test_attach_related_news_filters_keys_and_preserves_inputs():
    import main
    sig = {"symbol": "NVDA", "severity": "yellow", "type": "x", "message": "signal"}
    pos = {key: 0 for key in main.POSITION_CONTEXT_KEYS}
    pos.update(news=[{"title": str(i)} for i in range(5)], extra=123, return_3m_pct=None)
    fund = {key: 0 for key in main.FUNDAMENTAL_CONTEXT_KEYS}
    fund.update(forward_pe=None, extra=123)
    enriched = main._attach_related_news([sig], {"NVDA": pos}, {"NVDA": fund})[0]
    assert enriched["related_news"] == pos["news"][:3]
    assert enriched["position"] == {k: pos[k] for k in main.POSITION_CONTEXT_KEYS if pos[k] is not None}
    assert enriched["fundamentals"] == {k: fund[k] for k in main.FUNDAMENTAL_CONTEXT_KEYS if fund[k] is not None}
    assert "position" not in sig
    assert len(pos["news"]) == 5


@pytest.mark.parametrize("pos", [None, {}, {"error": "boom", "last_close": 100, "news": [1]}])
def test_attach_related_news_handles_missing_or_errored_positions(pos):
    import main
    result = main._attach_related_news([{"symbol": "NVDA"}], {"NVDA": pos})
    assert result == [{"symbol": "NVDA", "position": {}, "fundamentals": {}, "related_news": []}]


def test_attach_related_news_handles_errored_fundamentals():
    import main
    result = main._attach_related_news(
        [{"symbol": "NVDA"}], {"NVDA": {"last_close": 100}},
        {"NVDA": {"error": "boom", "trailing_pe": 30}},
    )
    assert result[0]["position"] == {"last_close": 100}
    assert result[0]["fundamentals"] == {}


def test_build_email_keeps_report_when_all_llm_models_fail(caplog):
    import main
    watchlist = {"NVDA": _pos(ma200_cross="golden", week52_pct=88.0)}
    with patch("main.interpret_signals", side_effect=RuntimeError("모든 모델 실패: 404")):
        body = main.build_email(watchlist, {"NVDA": {"trailing_pe": 28.5}},
                                {"events": [{"name": "주요 거시 일정"}]})
    assert "200일선 상향 돌파" in body
    assert "52주 밴드 88.0% · PER 28.5배" in body
    assert "주요 거시 일정" in body
    assert "AI 해설을 일시적으로 제공하지 못했습니다." in body
    assert "투자 참고용" in body
    assert "404" not in body
    assert "모든 모델 실패: 404" in caplog.text


def test_main_sends_briefing_instead_of_error_email_when_llm_unavailable():
    import main
    data = {"watchlist": {"NVDA": _pos(ma200_cross="golden")},
            "fundamentals": {}, "economic_cal": {}}
    with patch("config.validate"), \
         patch("main.load_watchlist", return_value={"us": ["NVDA"], "kr": []}), \
         patch("main.collect_all", return_value=data), \
         patch("main.interpret_signals", side_effect=RuntimeError("모든 모델 실패: 404")), \
         patch("main.load_recipients", return_value={"emails": ["receiver@test.com"]}), \
         patch("main.send") as send, patch("main.send_error") as send_error:
        main.main()
    send.assert_called_once()
    assert send.call_args.kwargs == {"to": "receiver@test.com"}
    assert "200일선 상향 돌파" in send.call_args.args[0]
    assert "AI 해설을 일시적으로 제공하지 못했습니다." in send.call_args.args[0]
    send_error.assert_not_called()
