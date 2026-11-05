import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr("history.DB_FILE", tmp_path / "test.db")


def _pos(**overrides):
    base = {
        "last_close": 100.0, "volume": 1_000_000, "news": [],
        "ma200_cross": None, "ma200_cross_months_since_prior": None,
        "is_new_52w_high": False, "is_new_52w_low": False,
        "volume_ratio": 1.0,
        "week52_pct": 41.0, "pct_vs_ma200": -3.0, "relative_strength_6m_pct": 12.0,
    }
    base.update(overrides)
    return base


def test_build_email_no_signals_skips_llm():
    import main

    watchlist = {"NVDA": _pos()}
    with patch("main.interpret_signals") as mock_interpret:
        body = main.build_email(watchlist, {}, {}, {})

    mock_interpret.assert_not_called()
    assert "신호 0건" in body


def test_build_email_focus_block_shows_ranked_list_instead_of_severity_groups():
    import main

    watchlist = {"NVDA": _pos(ma200_cross="golden", ma200_cross_months_since_prior=1.0)}
    email_config = {"blocks": ["focus", "positions"]}

    with patch("main.interpret_signals", return_value="해설"):
        body = main.build_email(watchlist, {}, {}, {}, None, email_config)

    assert "🎯 오늘 볼 순서" in body
    assert "🟡 관찰" not in body


def test_build_email_no_email_config_defaults_to_all_blocks_including_focus():
    # report.DEFAULT_BLOCKS enables "focus", and the actual default
    # config/report.json ships with it enabled too — so a caller that passes
    # no email_config at all sees the ranked view, not just severity groups.
    import main

    watchlist = {"NVDA": _pos(ma200_cross="golden", ma200_cross_months_since_prior=1.0)}

    with patch("main.interpret_signals", return_value="해설"):
        body = main.build_email(watchlist, {}, {}, {}, None, None)

    assert "🎯 오늘 볼 순서" in body


def test_build_email_excluding_focus_from_blocks_keeps_severity_groups():
    import main

    watchlist = {"NVDA": _pos(ma200_cross="golden", ma200_cross_months_since_prior=1.0)}
    email_config = {"blocks": ["positions"]}

    with patch("main.interpret_signals", return_value="해설"):
        body = main.build_email(watchlist, {}, {}, {}, None, email_config)

    assert "🟡 관찰" in body
    assert "🎯" not in body


def test_build_email_calendar_block_disabled_hides_calendar():
    import main
    from datetime import date, timedelta

    soon = (date.today() + timedelta(days=2)).isoformat()
    fundamentals = {"NVDA": {"next_earnings_date": soon, "ex_dividend_date": None}}
    watchlist = {"NVDA": _pos(ma200_cross="golden", ma200_cross_months_since_prior=1.0)}
    email_config = {"blocks": ["positions"]}

    with patch("main.interpret_signals", return_value="해설"):
        body = main.build_email(watchlist, fundamentals, {}, {}, None, email_config)

    assert "이번 주" not in body


def test_has_reportable_content_true_with_signal():
    import main

    watchlist = {"NVDA": _pos(ma200_cross="golden", ma200_cross_months_since_prior=1.0)}
    assert main._has_reportable_content(watchlist, {}, None, "2026-08-02") is True


def test_has_reportable_content_true_with_failure_even_without_signal():
    import main

    watchlist = {"NVDA": {"error": "boom"}}
    assert main._has_reportable_content(watchlist, {}, None, "2026-08-02") is True


def test_has_reportable_content_false_on_quiet_day():
    import main

    watchlist = {"NVDA": _pos()}
    assert main._has_reportable_content(watchlist, {}, None, "2026-08-02") is False


def test_build_email_passes_resolved_config_to_signal_evaluation():
    # Regression: build_email must actually forward per-symbol profile config
    # through to signals.evaluate, not just accept and ignore the parameter.
    import main

    watchlist = {"NVDA": _pos(volume_ratio=5.0)}  # would fire volume_spike globally
    resolved_config = {"NVDA": {"signals": ["ma200_cross"], "thresholds": {}}}

    with patch("main.interpret_signals") as mock_interpret:
        body = main.build_email(watchlist, {}, {}, {}, resolved_config)

    mock_interpret.assert_not_called()
    assert "거래량" not in body


def test_build_email_with_signal_calls_llm():
    import main

    watchlist = {"NVDA": _pos(ma200_cross="golden", ma200_cross_months_since_prior=2.0)}
    fundamentals = {"NVDA": {"trailing_pe": 30.0, "target_mean_price": 150.0}}

    with patch("main.interpret_signals", return_value="해설") as mock_interpret:
        body = main.build_email(watchlist, fundamentals, {}, {})

    mock_interpret.assert_called_once()
    assert "200일선 상향 돌파" in body
    assert "해설" in body


def test_build_email_does_not_write_snapshots_as_a_side_effect():
    # Regression: build_email used to save history rows itself. That's now
    # main()'s job (a fixed pipeline step, not hidden inside "build the email").
    import main
    import history

    watchlist = {"NVDA": _pos()}
    fundamentals = {"NVDA": {"trailing_pe": 30.0}}
    with patch("main.interpret_signals"):
        main.build_email(watchlist, fundamentals, {}, {})

    today_str = __import__("datetime").date.today().isoformat()
    assert history.get_snapshot("NVDA", today_str) is None


def test_save_snapshots_persists_position_and_fundamentals():
    import main
    import history

    watchlist = {"NVDA": _pos(last_close=100.0)}
    fundamentals = {"NVDA": {"trailing_pe": 30.0, "target_mean_price": 150.0}}
    today_str = __import__("datetime").date.today().isoformat()

    main._save_snapshots(watchlist, fundamentals, today_str)

    snap = history.get_snapshot("NVDA", today_str)
    assert snap["last_close"] == 100.0
    assert snap["trailing_pe"] == 30.0


def test_save_snapshots_skips_errored_symbols():
    import main
    import history

    watchlist = {"NVDA": {"error": "boom"}}
    today_str = __import__("datetime").date.today().isoformat()

    main._save_snapshots(watchlist, {}, today_str)

    assert history.get_snapshot("NVDA", today_str) is None


def test_build_email_attaches_yfinance_news_to_llm_payload():
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
        main.build_email(watchlist, {}, {}, {})

    assert captured["signals"][0]["related_news"][0]["title"] == "NVDA rallies"


def test_build_email_matches_general_news_by_symbol_and_dedupes():
    import main

    watchlist = {"NVDA": _pos(
        ma200_cross="golden", ma200_cross_months_since_prior=1.0,
        news=[{"title": "NVDA existing", "url": "http://a.com"}],
    )}
    news_data = {"articles": [
        {"title": "NVDA rallies on earnings", "url": "http://b.com"},
        {"title": "Completely unrelated market news", "url": "http://c.com"},
        {"title": "NVDA existing", "url": "http://a.com"},  # duplicate url
    ]}

    captured = {}

    def fake_interpret(signals):
        captured["signals"] = signals
        return "해설"

    with patch("main.interpret_signals", side_effect=fake_interpret):
        main.build_email(watchlist, {}, {}, news_data)

    related = captured["signals"][0]["related_news"]
    urls = [a["url"] for a in related]
    assert "http://b.com" in urls
    assert "http://c.com" not in urls
    assert urls.count("http://a.com") == 1


def test_build_email_shows_failed_symbols_when_no_real_signals():
    # Regression: total collection failure must not look identical to a
    # genuinely quiet day.
    import main

    watchlist = {"NVDA": {"error": "boom"}}
    with patch("main.interpret_signals") as mock_interpret:
        body = main.build_email(watchlist, {}, {}, {})

    mock_interpret.assert_not_called()
    assert "수집 실패" in body
    assert "오늘은 관심종목에 특이사항이 없습니다" not in body


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
    events = main._ticker_calendar_events(fundamentals, {}, today)
    assert any("NVDA 실적" in e for e in events)
    assert not any("AAPL" in e for e in events)


def test_ticker_calendar_events_uses_display_name():
    import main
    from datetime import date, timedelta

    today = date(2026, 8, 2)
    soon = (today + timedelta(days=3)).isoformat()
    fundamentals = {"005930.KS": {"next_earnings_date": soon, "ex_dividend_date": None}}
    names = {"005930.KS": "삼성전자"}

    events = main._ticker_calendar_events(fundamentals, names, today)
    assert any("삼성전자" in e for e in events)


def test_ticker_calendar_events_skips_errored_symbols():
    import main
    from datetime import date

    events = main._ticker_calendar_events({"NVDA": {"error": "boom"}}, {}, date(2026, 8, 2))
    assert events == []


def test_symbol_names_extracts_from_fundamentals():
    import main

    fundamentals = {
        "NVDA": {"name": "NVIDIA Corporation"},
        "AAPL": {"error": "boom"},
        "TSLA": {"name": None},
    }
    names = main._symbol_names(fundamentals)
    assert names == {"NVDA": "NVIDIA Corporation"}


def test_build_latest_payload_includes_positions_and_focus_and_status():
    import main

    watchlist = {"NVDA": _pos(ma200_cross="golden", ma200_cross_months_since_prior=1.0),
                 "AAPL": {"error": "rate limited"}}
    fundamentals = {"NVDA": {"name": "NVIDIA", "trailing_pe": 30.0}}
    resolved_config = {"NVDA": {"signals": None, "thresholds": {}, "profile": "core_holding"}}

    payload = main.build_latest_payload(
        watchlist, fundamentals, {}, {}, resolved_config, [], None,
    )

    assert payload["schema_version"] == 1
    assert payload["status"]["ok"] is False
    assert payload["status"]["failed_symbols"] == [{"symbol": "AAPL", "reason": "rate limited"}]
    assert len(payload["positions"]) == 1
    assert payload["positions"][0]["symbol"] == "NVDA"
    assert payload["positions"][0]["profile"] == "core_holding"
    assert len(payload["focus"]) == 1
    assert payload["focus"][0]["symbol"] == "NVDA"


def test_build_latest_payload_ok_status_when_nothing_failed():
    import main

    watchlist = {"NVDA": _pos()}
    payload = main.build_latest_payload(watchlist, {}, {}, {}, {}, [], None)
    assert payload["status"]["ok"] is True
    assert payload["focus"] == []


def test_build_latest_payload_passes_through_discovery():
    import main

    watchlist = {"NVDA": _pos()}
    discovery_list = [{"symbol": "AMD", "name": "AMD", "why": "당일 기사 3건 언급"}]
    payload = main.build_latest_payload(watchlist, {}, {}, {}, {}, [], None, discovery_list)
    assert payload["discovery"] == discovery_list


def test_build_latest_payload_defaults_discovery_to_empty_list():
    import main

    payload = main.build_latest_payload({"NVDA": _pos()}, {}, {}, {}, {}, [], None)
    assert payload["discovery"] == []


def test_build_email_discovery_block_renders_candidates():
    import main

    watchlist = {"NVDA": _pos()}
    email_config = {"blocks": ["positions", "discovery"]}
    discovery_list = [{"symbol": "AMD", "name": "AMD", "why": "당일 기사 3건 언급"}]

    body = main.build_email(watchlist, {}, {}, {}, None, email_config, None, discovery_list)

    assert "AMD" in body
    assert "당일 기사 3건 언급" in body


def test_build_email_discovery_omitted_without_block():
    import main

    watchlist = {"NVDA": _pos()}
    discovery_list = [{"symbol": "AMD", "name": "AMD", "why": "당일 기사 3건 언급"}]

    body = main.build_email(watchlist, {}, {}, {}, None, {"blocks": ["positions"]}, None, discovery_list)

    assert "AMD" not in body


def test_collect_all_merges_news_and_economic_cal_errors():
    import main

    with patch("main.news.fetch", return_value={"articles": [], "errors": ["feed X failed"]}), \
         patch("main.economic_cal.fetch", return_value={"events": [], "errors": ["FRED: timeout"]}):
        result = main.collect_all([])

    assert "feed X failed" in result["_errors"]
    assert "FRED: timeout" in result["_errors"]


def test_collect_all_records_collector_exception():
    import main

    with patch("main.news.fetch", side_effect=Exception("boom")), \
         patch("main.economic_cal.fetch", return_value={}):
        result = main.collect_all([])

    assert any("news" in e for e in result["_errors"])
    assert result["news"] is None


def test_collect_all_records_timeout_for_outstanding_futures():
    import time
    import main

    def slow_fetch():
        time.sleep(0.3)
        return {}

    with patch("main.news.fetch", side_effect=slow_fetch), \
         patch("main.economic_cal.fetch", return_value={}), \
         patch("main.COLLECT_TIMEOUT_SECONDS", 0.01):
        result = main.collect_all([])

    assert any("timed out" in e for e in result["_errors"])
    assert result["news"] is None


def test_collect_all_does_not_reference_removed_market_collectors():
    import main
    assert not hasattr(main, "us_market")
    assert not hasattr(main, "kr_market")


def test_main_skips_send_when_configured_and_quiet(monkeypatch, tmp_path):
    import main

    monkeypatch.setattr("config.validate", lambda: None)
    monkeypatch.setattr(main.store, "load_watchlist", lambda: {"version": 2, "profiles": {}, "symbols": [{"symbol": "NVDA"}]})
    monkeypatch.setattr(main.store, "watchlist_symbols", lambda wl: ["NVDA"])
    monkeypatch.setattr(main.store, "resolve_all_symbols", lambda wl: {"NVDA": {}})
    monkeypatch.setattr(main.store, "load_report_config", lambda: {
        "email": {"blocks": ["positions"], "send_when_no_signal": "skip", "recipients": ["a@test.com"]},
        "focus": {},
    })
    monkeypatch.setattr(main, "collect_all", lambda symbols: {
        "watchlist": {"NVDA": _pos()}, "fundamentals": {}, "news": {}, "economic_cal": {}, "_errors": [],
    })
    monkeypatch.setattr(main.publish, "save_latest", lambda payload: None)
    mock_send = MagicMock()
    monkeypatch.setattr(main, "send", mock_send)

    main.main()

    mock_send.assert_not_called()


def test_main_sends_when_quiet_but_policy_is_one_line(monkeypatch):
    import main

    monkeypatch.setattr("config.validate", lambda: None)
    monkeypatch.setattr(main.store, "load_watchlist", lambda: {"version": 2, "profiles": {}, "symbols": [{"symbol": "NVDA"}]})
    monkeypatch.setattr(main.store, "watchlist_symbols", lambda wl: ["NVDA"])
    monkeypatch.setattr(main.store, "resolve_all_symbols", lambda wl: {"NVDA": {}})
    monkeypatch.setattr(main.store, "load_report_config", lambda: {
        "email": {"blocks": ["positions"], "send_when_no_signal": "one_line", "recipients": ["a@test.com"]},
        "focus": {},
    })
    monkeypatch.setattr(main, "collect_all", lambda symbols: {
        "watchlist": {"NVDA": _pos()}, "fundamentals": {}, "news": {}, "economic_cal": {}, "_errors": [],
    })
    monkeypatch.setattr(main.publish, "save_latest", lambda payload: None)
    mock_send = MagicMock()
    monkeypatch.setattr(main, "send", mock_send)

    main.main()

    mock_send.assert_called_once()


def test_build_email_preserves_briefing_when_llm_unavailable(caplog):
    import main

    with patch("main.interpret_signals", side_effect=RuntimeError("모든 모델 실패: 404")):
        body = main.build_email(
            {"NVDA": _pos(ma200_cross="golden")}, {},
            {"events": [{"name": "주요 거시 일정"}]}, {},
        )
    assert "200일선 상향 돌파" in body
    assert "주요 거시 일정" in body
    assert "AI 해설을 일시적으로 제공하지 못했습니다." in body
    assert "투자 참고용" in body
    assert "404" not in body
    assert "모든 모델 실패: 404" in caplog.text


def test_main_sends_report_and_persists_outputs_when_llm_unavailable(monkeypatch):
    import main

    monkeypatch.setattr("config.validate", lambda: None)
    monkeypatch.setattr(main.store, "load_watchlist", lambda: {})
    monkeypatch.setattr(main.store, "watchlist_symbols", lambda wl: ["NVDA"])
    monkeypatch.setattr(main.store, "resolve_all_symbols", lambda wl: {"NVDA": {}})
    monkeypatch.setattr(main.store, "load_report_config", lambda: {
        "email": {"blocks": ["positions"], "recipients": ["a@test.com"]},
    })
    monkeypatch.setattr(main, "collect_all", lambda symbols: {
        "watchlist": {"NVDA": _pos(ma200_cross="golden")},
        "fundamentals": {}, "news": {}, "economic_cal": {}, "_errors": [],
    })
    with patch("main.interpret_signals", side_effect=RuntimeError("모든 모델 실패: 404")), \
         patch("main.discovery_engine.build_discovery", return_value=[]), \
         patch("main.publish.save_latest") as save_latest, \
         patch("main.send") as send, patch("main.send_error") as send_error:
        main.main()
    send.assert_called_once()
    assert send.call_args.kwargs == {"to": "a@test.com"}
    assert "200일선 상향 돌파" in send.call_args.args[0]
    assert "AI 해설을 일시적으로 제공하지 못했습니다." in send.call_args.args[0]
    send_error.assert_not_called()
    save_latest.assert_called_once()
    import history
    assert history.get_snapshot("NVDA", main.date.today().isoformat()) is not None
